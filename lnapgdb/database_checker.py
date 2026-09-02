#!/bin/env python3

import os
import argparse
import logging
from json import load
from pathlib import Path
from datetime import datetime, timedelta
from sqlalchemy import text

from .log_utils import setup_logging, get_log_dir, ensure_not_root
from .insertdb import InsertDB
from .file_watcher import resolve_instrument_directories


def default_check_date():
    """Return the default night (YYYYMMDD) checked when no date is given: yesterday."""
    return (datetime.now() - timedelta(days=1)).strftime("%Y%m%d")


def missing_log_path(date):
    """
    Path of the missing-files log for a given night (YYYYMMDD). Written by
    DatabaseChecker.run() and read back by retry_missing.py, which uses this
    same function to locate the file and re-attempt ingestion of exactly the
    files it lists.
    """
    return get_log_dir() / f"missing_files_{date}.log"


class DatabaseChecker:
    def __init__(self, directories=None, config=None, db=None, date=None,
                 extensions=None, schema="public"):
        if config:
            self.directories = [
                full_path for _, full_path, exists in resolve_instrument_directories(config)
                if exists
            ]
        else:
            self.directories = [Path(d) for d in (directories or [])]

        self.db = db
        self.schema = schema
        self.extensions = extensions or {'.fits', '.fit', '.fts'}

        # Default to yesterday if no date is provided
        self.date = date or default_check_date()

    def _fast_scan_fits(self, directory_path):
        """Recursively find FITS files using the high-performance os.scandir."""
        files = []
        stack = [str(directory_path)]

        while stack:
            current_dir = stack.pop()
            try:
                with os.scandir(current_dir) as entries:
                    for entry in entries:
                        if entry.is_dir(follow_symlinks=False):
                            stack.append(entry.path)
                        elif entry.is_file(follow_symlinks=False):
                            _, ext = os.path.splitext(entry.name)
                            if ext.lower() in self.extensions:
                                files.append(entry.path)
            except OSError as e:
                print(f"Warning: Could not read directory {current_dir}: {e}")

        return files

    def _find_date_directories(self, root_directory):
        """
        Recursively locate every directory named exactly self.date under
        root_directory, regardless of nesting depth. This covers both flat
        layouts (root/YYYYMMDD, e.g. bc060) and nested ones (root/channel/
        YYYYMMDD, e.g. sparc4's per-camera mounts) without needing to know
        the layout ahead of time.
        """
        matches = []
        stack = [str(root_directory)]

        while stack:
            current_dir = stack.pop()
            try:
                with os.scandir(current_dir) as entries:
                    for entry in entries:
                        if not entry.is_dir(follow_symlinks=False):
                            continue
                        if entry.name == self.date:
                            matches.append(Path(entry.path))
                        else:
                            stack.append(entry.path)
            except OSError as e:
                print(f"Warning: Could not read directory {current_dir}: {e}")

        return matches

    def scan_files(self):
        """Recursively scans all active raw directories for the target date."""
        files = []

        for directory in self.directories:
            date_directories = self._find_date_directories(directory)

            if not date_directories:
                print(f"No '{self.date}' directory found under: {directory}")
                continue

            for date_directory in date_directories:
                files.extend(self._fast_scan_fits(date_directory))

        return files

    def get_registered_files(self):
        """
        Fetch filenames already ingested for this date. FILENAME is unique
        and always prefixed with the observation night (YYYYMMDD...), so a
        trailing-wildcard LIKE can use the unique index Postgres already
        maintains on that column instead of forcing a full table scan.
        """
        query = text(f"""
            SELECT "FILENAME"
            FROM {self.schema}.primary_table
            WHERE "FILENAME" LIKE :date_prefix
        """)

        date_prefix = f"{self.date}%"

        with self.db.engine.connect() as conn:
            result = conn.execute(
                query, {"date_prefix": date_prefix}).fetchall()

        return {row[0] for row in result}

    def run(self):
        """
        Scan disk, cross-reference against the DB, and log whichever files
        are missing. Returns the path to the missing-files log written (the
        same path retry_missing.py resolves via missing_log_path()), or None
        if there was nothing to report.
        """
        files = self.scan_files()

        if not files:
            print(f"Nenhum arquivo local encontrado no disco para a data: {
                  self.date}")
            return None

        print(f"Avaliando {len(
            files)} arquivos no disco. Buscando no banco de dados schema '{self.schema}'...")

        db_files = self.get_registered_files()

        # Cross-reference by filename, since that's what's actually unique in the DB
        missing_files = [
            file for file in files if os.path.basename(file) not in db_files]

        print(f"Arquivos faltantes: {len(missing_files)}")

        if missing_files:
            log_name = missing_log_path(self.date)

            # Log to file for batch processing/retry
            with open(log_name, "w", encoding="utf-8") as f:
                for file in missing_files:
                    f.write(f"{file}\n")

            print(f"Log de arquivos faltando salvo em: {log_name}")
            return str(log_name)
        else:
            print(
                "✅ Sucesso! Todos os arquivos do disco estão presentes no banco de dados.")
            return None


def parse_arguments():
    parser = argparse.ArgumentParser(
        description='Check whether all raw FITS files for a given night were ingested into the DB.')
    parser.add_argument('--config', type=str, default='config.json',
                        help='Path to the configuration file')
    parser.add_argument('--db_schema', type=str, default='public',
                        choices=['public', 'dev', 'cyc', 'prod'],
                        help='Database schema to check')
    parser.add_argument('--date', type=str,
                        help='Night to check, format YYYYMMDD. Defaults to yesterday.')
    parser.add_argument('--log-file', type=str,
                        default=str(get_log_dir() / 'database_checker.log'),
                        help='Path to the log file')
    parser.add_argument('--log-level', type=str, default='INFO',
                        help='Logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL)')
    parser.add_argument('--debug', action='store_true',
                        help='Enable debug mode (sets log level to DEBUG)')
    return parser.parse_args()


def main():
    ensure_not_root()

    args = parse_arguments()

    root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    with open(os.path.join(root_dir, 'config', args.config), 'r') as f:
        config = load(f)

    db_schema = config.get('db_schema') or args.db_schema

    level_map = {
        'DEBUG': logging.DEBUG, 'INFO': logging.INFO, 'WARNING': logging.WARNING,
        'ERROR': logging.ERROR, 'CRITICAL': logging.CRITICAL,
    }
    log_level_int = logging.DEBUG if args.debug else level_map.get(
        args.log_level.upper(), logging.INFO)

    logger = setup_logging(
        logger_name="lnapgdb.database_checker",
        loglevel=log_level_int,
        logfile=args.log_file,
        verbose=True,
    )

    # Reuse InsertDB purely for its credential loading / engine setup, so
    # the checker never has to duplicate (and risk drifting from) how the
    # ingestion process connects to Postgres. This opens a short-lived,
    # read-only-usage connection - it does not insert anything.
    db = InsertDB(config=config, args=args, logger=logger)

    checker = DatabaseChecker(
        config=config,
        db=db,
        date=args.date,
        schema=db_schema,
    )
    checker.run()


if __name__ == "__main__":
    main()
