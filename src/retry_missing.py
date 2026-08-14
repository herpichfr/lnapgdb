#!/bin/env python3

"""
Retry Missing Files

Reads a log file containing missing FITS file paths, extracts their metadata 
using DataCollector, and inserts them into the database using InsertDB.

Usage:
python3 retry_missing.py --missing-log missing_files_20260812.log --db_schema prod
"""

import os
import argparse
import logging
from json import load

from log_utils import setup_logging
from data_collector import DataCollector
from insertdb import InsertDB


def parse_arguments():
    parser = argparse.ArgumentParser(
        description='Retry Missing FITS Files Ingestion')
    parser.add_argument('--missing-log', type=str, required=True,
                        help='Path to the log file containing missing file paths (e.g., missing_files_20260812.log)')
    parser.add_argument('--config', type=str, default='config.json',
                        help='Path to the configuration file')
    parser.add_argument('--db_schema', type=str, default='public',
                        help='Database schema to use for insertion')
    parser.add_argument('--nprocs', '-n', type=int, default=1,
                        help='Number of processes to use for parallel processing')
    parser.add_argument('--log-file', type=str, default='retry_missing.log',
                        help='Path to the output execution log file')
    return parser.parse_args()


def load_config(config_name):
    # Assuming config is in a 'config' directory at the project root
    root_dir = os.path.dirname(os.path.abspath(__file__))
    config_path = os.path.join(root_dir, 'config', config_name)
    with open(config_path, 'r') as f:
        return load(f)


def main():
    args = parse_arguments()
    logger = setup_logging(loglevel=logging.INFO,
                           logfile=args.log_file, verbose=True)
    logger.info("Not implemented/tested yet. Exiting.")
    return

    if not os.path.exists(args.missing_log):
        logger.critical(f"Missing files log not found: {args.missing_log}")
        return

    # 1. Read and validate missing files
    files_to_process = []
    with open(args.missing_log, 'r', encoding='utf-8') as f:
        for line in f:
            filepath = line.strip()
            if filepath and os.path.exists(filepath):
                files_to_process.append(filepath)
            elif filepath:
                logger.warning(f"File no longer exists on disk: {filepath}")

    if not files_to_process:
        logger.info("No valid files to process. Exiting.")
        return

    logger.info(f"Found {len(files_to_process)
                         } valid files to retry from {args.missing_log}.")

    # 2. Load Configuration
    try:
        config = load_config(args.config)
    except Exception as e:
        logger.critical(f"Failed to load config: {e}")
        return

    # 3. Collect Data
    logger.info("Starting DataCollector...")
    try:
        data_collector = DataCollector(
            fits_files=files_to_process,
            db_schema=args.db_schema,
            nprocs=args.nprocs,
            config=config,
            debug=False
        )
        p_df, i_df = data_collector.collect_data()
    except Exception as e:
        logger.error(f"Error during data collection: {e}")
        return

    if p_df.empty:
        logger.warning(
            "No valid data could be extracted from the missing files.")
        return

    # 4. Insert Data
    logger.info("Starting database insertion...")
    try:
        db_inserter = InsertDB(
            config=config,
            args=args,
            logger=logger
        )

        inserted, error_count = db_inserter.insert_batch(
            p_df, i_df, db_schema=args.db_schema
        )

        if inserted:
            logger.info(f"✅ Successfully inserted missing records. Failed on {
                        error_count} records.")

            # Optional: Rename the log file so it isn't accidentally processed again
            processed_log_name = f"{args.missing_log}.processed"
            os.rename(args.missing_log, processed_log_name)
            logger.info(f"Renamed {args.missing_log} to {processed_log_name}")

        else:
            logger.error(
                f"❌ Failed to insert missing batch. Errors encountered: {error_count}")

    except Exception as e:
        logger.error(f"Critical error during database insertion: {e}")


if __name__ == "__main__":
    main()
