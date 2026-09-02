#!/bin/env python3

"""
Retry Missing Files

Reads the missing-files log written by database_checker.py (one FITS file
path per line) and retries ingestion of each file individually: metadata is
re-extracted with DataCollector and inserted with InsertDB one file at a
time, so a single bad file can never block the rest of the batch and every
failure is captured with its own reason.

Files that still fail after the retry are written back to the same
missing-files log (so a following run only has to deal with what's actually
still missing), with the reasons appended to a companion ``*.errors.log``
file. Once every file has been ingested successfully, the missing-files log
is renamed to ``*.resolved``.

Usage:
python3 -m lnapgdb.retry_missing --date 20260812 --db_schema prod
python3 -m lnapgdb.retry_missing --missing-log ~/logs/missing_files_20260812.log
"""

import os
import argparse
import logging
from json import load
from datetime import datetime

from .log_utils import setup_logging, get_log_dir, ensure_not_root
from .data_collector import DataCollector
from .insertdb import InsertDB
from .database_checker import default_check_date, missing_log_path


def parse_arguments():
    parser = argparse.ArgumentParser(
        description='Retry ingestion of FITS files reported missing by '
                     'database_checker.py, inserting each one individually.')
    parser.add_argument('--missing-log', type=str, default=None,
                        help='Path to the missing-files log written by '
                             'database_checker.py. Defaults to '
                             '<home>/logs/missing_files_<date>.log')
    parser.add_argument('--date', type=str, default=None,
                        help='Night to retry, format YYYYMMDD. Used to locate '
                             'the default missing-files log when --missing-log '
                             'is not given. Defaults to yesterday, matching '
                             "database_checker.py's own default.")
    parser.add_argument('--config', type=str, default='config.json',
                        help='Path to the configuration file')
    parser.add_argument('--db_schema', type=str, default='public',
                        help='Database schema to use for insertion')
    parser.add_argument('--log-file', type=str,
                        default=str(get_log_dir() / 'retry_missing.log'),
                        help='Path to the output execution log file')
    return parser.parse_args()


def load_config(config_name):
    # config/ lives at the project root, two levels above this module
    root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    config_path = os.path.join(root_dir, 'config', config_name)
    with open(config_path, 'r') as f:
        return load(f)


def write_retry_errors(missing_log, failures, logger):
    """Append timestamped failure reasons next to the missing-files log."""
    errors_log = f"{os.path.splitext(missing_log)[0]}.errors.log"
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    try:
        with open(errors_log, "a", encoding="utf-8") as f:
            for filepath, reason in failures:
                f.write(f"{timestamp}\t{filepath}\t{reason}\n")
        logger.info(f"Retry error details appended to: {errors_log}")
    except Exception as e:
        logger.error(f"Failed writing retry error log ({errors_log}): {e}")


def main():
    ensure_not_root()

    args = parse_arguments()
    logger = setup_logging(
        logger_name="lnapgdb.retry_missing",
        loglevel=logging.INFO,
        logfile=args.log_file,
        verbose=True,
    )

    missing_log = args.missing_log or str(
        missing_log_path(args.date or default_check_date()))

    if not os.path.exists(missing_log):
        logger.critical(f"Missing files log not found: {missing_log}")
        return

    # 1. Read and validate missing files
    files_to_process = []
    with open(missing_log, 'r', encoding='utf-8') as f:
        for line in f:
            filepath = line.strip()
            if filepath and os.path.exists(filepath):
                files_to_process.append(filepath)
            elif filepath:
                logger.warning(f"File no longer exists on disk: {filepath}")

    if not files_to_process:
        logger.info(f"No valid files to process from {missing_log}. Exiting.")
        return

    logger.info(
        f"Found {len(files_to_process)} valid files to retry from {missing_log}.")

    # 2. Load configuration
    try:
        config = load_config(args.config)
    except Exception as e:
        logger.critical(f"Failed to load config: {e}")
        return

    # 3. Retry each file individually, so one bad file never blocks the rest
    # and we know exactly which files still need attention afterwards.
    primary_model = DataCollector.get_primary_model()
    instrument_models_cache = {}
    db_inserter = InsertDB(config=config, args=args, logger=logger)

    succeeded = []
    still_failed = []  # list of (filepath, reason)

    for filepath in files_to_process:
        try:
            collector = DataCollector(
                fits_files=[filepath],
                primary_model=primary_model,
                instrument_models_cache=instrument_models_cache,
                db_schema=args.db_schema,
                nprocs=1,
                config=config,
                logger=logger,
            )
            p_df, i_df = collector.collect_data()
        except Exception as e:
            logger.error(f"Error collecting metadata for '{filepath}': {e}")
            still_failed.append((filepath, f"Metadata collection error: {e}"))
            continue

        if p_df.empty:
            logger.error(f"Metadata collection/validation failed for: {filepath}")
            still_failed.append(
                (filepath, "Metadata collection/validation failed"))
            continue

        try:
            inserted, error_count = db_inserter.insert_batch(
                p_df, i_df, db_schema=args.db_schema
            )
        except Exception as e:
            logger.error(f"Critical error inserting '{filepath}': {e}")
            still_failed.append((filepath, f"Insertion exception: {e}"))
            continue

        if inserted:
            logger.info(f"✅ Successfully re-ingested: {filepath}")
            succeeded.append(filepath)
        else:
            logger.error(f"❌ Database insertion failed for: {filepath}")
            still_failed.append(
                (filepath, f"Database insertion failed ({error_count} errors)"))

    logger.info(
        f"Retry finished. Re-ingested {len(succeeded)}/{len(files_to_process)} "
        f"files. Still missing: {len(still_failed)}."
    )

    # 4. Record the outcome so a future database_checker/retry_missing run
    # only has to deal with what's actually still missing.
    if still_failed:
        write_retry_errors(missing_log, still_failed, logger)
        with open(missing_log, 'w', encoding='utf-8') as f:
            for filepath, _ in still_failed:
                f.write(f"{filepath}\n")
        logger.warning(
            f"{len(still_failed)} file(s) are still missing after retry; "
            f"'{missing_log}' now reflects only those."
        )
    else:
        resolved_log_name = f"{missing_log}.resolved"
        os.rename(missing_log, resolved_log_name)
        logger.info(
            f"All files ingested. Renamed {missing_log} to {resolved_log_name}")


if __name__ == "__main__":
    main()
