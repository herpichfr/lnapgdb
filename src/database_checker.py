#!/bin/env python3

import os
from pathlib import Path
from datetime import datetime, timedelta
from sqlalchemy import text


class DatabaseChecker:
    def __init__(self, directories, db, date=None, extensions=None, schema="public"):
        self.directories = directories
        self.db = db
        self.schema = schema
        self.extensions = extensions or {'.fits', '.fit', '.fts'}

        # Default to yesterday if no date is provided
        self.date = date or (
            datetime.now() - timedelta(days=1)
        ).strftime("%Y%m%d")

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
                                # Resolve to absolute path to match DB entries
                                files.append(str(Path(entry.path).resolve()))
            except OSError as e:
                print(f"Warning: Could not read directory {current_dir}: {e}")

        return files

    def scan_files(self):
        """Scans all monitored directories for the specific date folder."""
        files = []

        for directory in self.directories:
            date_directory = Path(directory) / self.date

            if not date_directory.exists():
                print(f"Directory not found: {date_directory}")
                continue

            # Fast scan the date directory
            files.extend(self._fast_scan_fits(date_directory))

        return files

    def get_registered_files(self):
        """Search all database paths that contain the folder date."""
        # Use dynamic schema injected from the observation manager
        query = text(f"""
            SELECT raw_path
            FROM {self.schema}.primary_table
            WHERE raw_path LIKE :date_filter
        """)

        # LIKE ensures that we will only bring the data from that night, saving memory.
        date_filter = f"%{self.date}%"

        with self.db.engine.connect() as conn:
            result = conn.execute(
                query, {"date_filter": date_filter}).fetchall()

        # Return a set of strings for O(1) lookup speeds
        return {row[0] for row in result}

    def run(self):
        files = self.scan_files()

        if not files:
            print(f"Nenhum arquivo local encontrado no disco para a data: {
                  self.date}")
            return

        print(f"Avaliando {len(
            files)} arquivos no disco. Buscando no banco de dados schema '{self.schema}'...")

        db_files = self.get_registered_files()

        # Cross-reference
        missing_files = [file for file in files if file not in db_files]

        print(f"Arquivos faltantes: {len(missing_files)}")

        if missing_files:
            log_name = f"missing_files_{self.date}.log"

            # Log to file for batch processing/retry
            with open(log_name, "w", encoding="utf-8") as f:
                for file in missing_files:
                    f.write(f"{file}\n")

            print(f"Log de arquivos faltando salvo em: {log_name}")
        else:
            print(
                "✅ Sucesso! Todos os arquivos do disco estão presentes no banco de dados.")
