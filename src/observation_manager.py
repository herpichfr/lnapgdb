#!/bin/python3

"""
Observation Manager

Create the database manager, which should be able to gather the new images from within a set of directories (whose could be defined in a config file)
Decide if we go for a config file or if we just use environment variables to set the directories to be monitored
The manager must be able to handle a large number of directories and images within
The code needs to keep track of the images that have already been processed
The list of new images at any given moment should be handled to the data_collector.py, which will extract the metadata, validate them and return as a pandas df
Finally, the manager handles the df to the insertdb.py module for database insertion

Copyright (c) 2026, LNA - Laboratório Nacional de Astrofísica, Brazil. All rights reserved.
"""

import os
import glob
from json import load
import time
import argparse
import logging
import subprocess
from datetime import datetime

from log_utils import setup_logging
from data_collector import DataCollector
from insertdb import InsertDB

from file_watcher import FileWatcher
# from database_checker import DatabaseChecker


def parse_arguments():
    parser = argparse.ArgumentParser(description='Observation Manager')
    parser.add_argument('--storage_dirs', nargs='*', default=[],
                        help='Root directories to monitor for new images')
    parser.add_argument('--config', type=str, default='config.json',
                        help='Path to the configuration file')
    parser.add_argument('--db_schema', type=str,
                        default='public',
                        choices=['public', 'dev', 'cyc', 'prod'],
                        help='Database schema to use for insertion')
    parser.add_argument('--nprocs', '-n', type=int, default=1,
                        help='Number of processes to use for parallel processing')
    parser.add_argument('--test', action='store_true',
                        help='Run in test mode (processes a predefined set of test images)')
    parser.add_argument('--watch-dir', nargs='+',
                        help='Directories to watch for new images')
    parser.add_argument('--cadence', type=int, default=10,
                        help='Time interval (in seconds) to check for new images')
    parser.add_argument('--avoid_work_hours', action='store_true',
                        help="Stop watching directories during the night.")
    parser.add_argument("--check-db", action="store_true",
                        help="Check if FITS files are already inserted in the database.")
    parser.add_argument("--date", type=str, help="Data no formato YYYYMMDD")
    parser.add_argument("--test_images", nargs="+",
                        help="List of test images to process in test mode. "
                             "Accepts literal file paths and/or quoted glob "
                             "patterns (e.g. '/mnt/sparc4/*/20260829/*.fits'), "
                             "which are expanded internally so the shell never "
                             "has to expand large file lists itself.")
    parser.add_argument('--log-level', type=str, default='WARNING',
                        help='Logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL)')
    parser.add_argument('--log-file', type=str, default='observation_manager.log',
                        help='Path to the log file')
    parser.add_argument('--failed-files-log', type=str,
                        default=os.environ.get(
                            'FAILED_FILES_LOG_PATH', 'failed_files.log'),
                        help='Path to the file recording failed FITS files')
    parser.add_argument('--debug', action='store_true',
                        help='Enable debug mode (sets log level to DEBUG)')
    parser.add_argument('--verbose', '-v', action='store_true',
                        help='Enable verbose logging')

    return parser.parse_args()


def get_git_branch():
    try:
        branch = subprocess.check_output(
            ['git', 'rev-parse', '--abbrev-ref', 'HEAD'],
            stderr=subprocess.DEVNULL
        ).decode('utf-8').strip()
        return branch
    except Exception:
        return "dev"


def get_schema_from_branch(branch):
    if branch == 'main':
        return 'prod'
    elif branch == 'cyc':
        return 'cyc'
    elif branch == 'dev':
        return 'dev'
    elif '_dev' in branch:
        return 'public'
    else:
        return 'public'


class ObservationManager:
    def __init__(self, args):
        self.storage_dirs = args.storage_dirs
        self.root_dir = os.path.dirname(
            os.path.dirname(os.path.abspath(__file__)))

        try:
            self.config = self.load_config(os.path.join(
                self.root_dir, 'config', args.config))
        except Exception as e:
            raise RuntimeError(f'Error loading config file: {e}')

        self.db_schema = self.config.get('db_schema') if self.config.get(
            'db_schema') else args.db_schema

        level_map = {
            'DEBUG': logging.DEBUG,
            'INFO': logging.INFO,
            'WARNING': logging.WARNING,
            'ERROR': logging.ERROR,
            'CRITICAL': logging.CRITICAL
        }

        log_level_int = logging.DEBUG if args.debug else level_map.get(
            args.log_level.upper(), logging.WARNING)

        # Ensure parent directory for main log file exists
        if args.log_file:
            log_dir = os.path.dirname(os.path.abspath(args.log_file))
            os.makedirs(log_dir, exist_ok=True)

        self.logger = setup_logging(
            loglevel=log_level_int,
            logfile=args.log_file,
            verbose=args.verbose
        )

        # Setup and validate failed files log path
        self.failed_files_log = args.failed_files_log
        if self.failed_files_log:
            failed_dir = os.path.dirname(
                os.path.abspath(self.failed_files_log))
            try:
                os.makedirs(failed_dir, exist_ok=True)
            except Exception as e:
                self.logger.error(
                    f"Could not create directory for failed files log ({failed_dir}): {e}")

        self.debug = args.debug
        self.test = args.test

        self.processed_images = set()

        self.models_dir = os.path.join(self.root_dir, 'models')
        self.primary_model = self.load_primary_model(
            self.models_dir, self.logger)
        self.instrument_models = self.load_instrument_models(
            self.config, self.models_dir, self.logger)

        self.last_check_time = time.time()
        self.cadence = args.cadence

    def write_failed_files(self, file_paths, reason="Unknown error"):
        """Directly record failed files to the designated log path."""
        if not self.failed_files_log or not file_paths:
            return

        try:
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            with open(self.failed_files_log, "a") as f:
                for path in file_paths:
                    f.write(f"{timestamp}\t{path}\t{reason}\n")
        except Exception as e:
            self.logger.error(f"Failed writing to failed files log ({
                              self.failed_files_log}): {e}")

    @staticmethod
    def load_config(config_path):
        with open(config_path, 'r') as f:
            return load(f)

    @staticmethod
    def load_primary_model(models_dir, logger=logging.getLogger()):
        primary_model_file = os.path.join(models_dir, 'primary_table.json')
        if os.path.exists(primary_model_file):
            logger.info(f'Loading primary model from {primary_model_file}')
            with open(primary_model_file, 'r') as f:
                primary_model_mapping = load(f)
        else:
            logger.critical(
                f'Primary model file not found: {primary_model_file}')
            raise FileNotFoundError(
                f'Primary model file not found: {primary_model_file}')

        primary_model = {}
        for col in primary_model_mapping:
            colname = col['colname']
            primary_model[colname] = col

        return primary_model

    @staticmethod
    def load_instrument_models(config, models_dir, logger=logging.getLogger()):
        instrument_models = {}

        for instrument_name, instrument_data in config.get('instruments', {}).items():
            instrument_models[instrument_name] = {}

            model_name = instrument_data.get('model_name')
            if not model_name:
                logger.critical(f'Model name not defined for {
                                instrument_name}')
                raise ValueError(f'Model name not defined for {
                                 instrument_name}')

            model_file = os.path.join(models_dir, model_name)

            if os.path.exists(model_file):
                logger.info(f'Loading model for {
                            instrument_name} from {model_file}')
                with open(model_file, 'r') as f:
                    instrument_models_mapping = load(f)
            else:
                logger.critical(f'Model file for instrument {
                                instrument_name} not found: {model_file}')
                raise FileNotFoundError(
                    f'Model file for {instrument_name} not found: {model_file}')

            if not isinstance(instrument_models_mapping, list):
                raise ValueError(f'Invalid model format for {instrument_name}')

            for col in instrument_models_mapping:
                colname = col['colname']
                instrument_models[instrument_name][colname] = col

        return instrument_models


if __name__ == "__main__":
    args = parse_arguments()
    observation_manager = ObservationManager(args)
    db_schema = observation_manager.db_schema

    if args.watch_dir:
        watcher = FileWatcher(
            directories=args.watch_dir,
            poll_interval=args.cadence,
            exclude_today_dir=args.avoid_work_hours
        )
    else:
        watcher = FileWatcher(
            config=observation_manager.config,
            poll_interval=args.cadence,
            exclude_today_dir=args.avoid_work_hours
        )

    git_branch = get_git_branch()
    db_schema_from_branch = get_schema_from_branch(git_branch)
    if db_schema_from_branch != db_schema:
        observation_manager.logger.warning(
            f"Git branch '{git_branch}' suggests using database schema '{db_schema_from_branch}', but config specifies '{db_schema}'.")
        observation_manager.logger.warning(
            "Please select which branch you want to use:\n"
            "1 - Use schema from config file\n"
            "2 - Use schema from git branch"
        )

        if os.isatty(0):
            user_input = input("Enter 1 or 2 (default is 1): ").strip()
            if user_input == '2':
                db_schema = db_schema_from_branch
                observation_manager.logger.info(
                    f"Using database schema '{db_schema}' from git branch '{git_branch}'.")
            else:
                observation_manager.logger.info(
                    f"Using database schema '{db_schema}' from config file.")
            user_input = input("Do you want to continue? (y/n): ").strip()
            if user_input.lower() == 'n':
                observation_manager.logger.info("Exiting as per user request.")
                exit(0)
        else:
            observation_manager.logger.warning(
                "Non-interactive environment detected. Defaulting to schema from config file.")

    if args.test_images:
        expanded_images = []
        for pattern in args.test_images:
            if glob.has_magic(pattern):
                matches = glob.glob(pattern, recursive=True)
                if not matches:
                    observation_manager.logger.warning(
                        f"No files matched pattern: {pattern}")
                expanded_images.extend(matches)
            else:
                expanded_images.append(pattern)
        args.test_images = sorted(set(expanded_images))

        if not args.test_images:
            observation_manager.logger.error(
                "No test images found after expanding patterns/paths.")
            exit(1)

        observation_manager.logger.info(
            f"Processing {len(args.test_images)} test images.")
        try:
            data_collector = DataCollector(
                fits_files=args.test_images,
                primary_model=observation_manager.primary_model,
                instrument_models_cache=observation_manager.instrument_models,
                db_schema=db_schema,
                nprocs=args.nprocs,
                config=observation_manager.config,
                debug=args.debug
            )

            p_df, i_df = data_collector.collect_data()
            observation_manager.logger.debug(
                "Data collection process finished.")

            if p_df.empty:
                observation_manager.logger.warning(
                    "No valid data collected from test images. Exiting.")
                observation_manager.write_failed_files(
                    args.test_images, "Data collection returned empty dataframe")
                exit(0)

            db_inserter = InsertDB(
                config=observation_manager.config,
                args=args,
                logger=observation_manager.logger
            )

            inserted, error_count = db_inserter.insert_batch(
                p_df, i_df, db_schema=db_schema
            )

            if inserted:
                observation_manager.logger.info(
                    f"Successfully processed test images. Inserted records, failed on {
                        error_count} records."
                )
            else:
                observation_manager.logger.error(
                    f"Failed to process test images. Errors encountered: {
                        error_count}"
                )
                observation_manager.write_failed_files(
                    args.test_images, f"Database insertion failed on {error_count} records")

        except Exception as e:
            observation_manager.logger.error(
                f'Error processing test images: {e}')
            observation_manager.write_failed_files(
                args.test_images, f"Exception during processing: {e}")
        exit(0)

    if not watcher.directories:
        observation_manager.logger.critical(
            'No valid directories found to monitor')
        raise ValueError('No valid directories found to monitor')

    if args.check_db:
        observation_manager.logger.error(
            "Database check functionality is not implemented yet.")

    try:
        watcher_iter = iter(watcher.watch())

        while True:
            current_hour = datetime.now().hour
            if not (10 <= current_hour < 16):
                time.sleep(args.cadence)
                continue

            try:
                new_images = next(watcher_iter)
            except StopIteration:
                break

            if not new_images:
                continue

            observation_manager.logger.info(
                f"Processing {len(new_images)} new images.")
            observation_manager.logger.debug(
                "Starting data collection process...")

            try:
                data_collector = DataCollector(
                    fits_files=new_images,
                    primary_model=observation_manager.primary_model,
                    instrument_models_cache=observation_manager.instrument_models,
                    db_schema=db_schema,
                    nprocs=args.nprocs,
                    config=observation_manager.config,
                    debug=args.debug
                )

                p_df, i_df = data_collector.collect_data()
                observation_manager.logger.debug(
                    "Data collection process finished.")

            except Exception as e:
                observation_manager.logger.error(
                    f'Error collecting data from images: {e}')
                observation_manager.write_failed_files(
                    new_images, f"Collection error: {e}")
                continue

            if p_df.empty:
                observation_manager.logger.warning(
                    "No valid data collected from this batch. Skipping insertion.")
                observation_manager.write_failed_files(
                    new_images, "No valid metadata extracted")
                continue

            try:
                db_inserter = InsertDB(
                    config=observation_manager.config,
                    args=args,
                    logger=observation_manager.logger
                )

                inserted, error_count = db_inserter.insert_batch(
                    p_df, i_df, db_schema=db_schema
                )

                if inserted:
                    observation_manager.logger.info(
                        f"Successfully processed batch. Inserted records, failed on {
                            error_count} records."
                    )
                else:
                    observation_manager.logger.error(
                        f"Failed to process batch. Errors encountered: {
                            error_count}"
                    )
                    observation_manager.write_failed_files(
                        new_images, f"Batch DB insertion failed on {error_count} records")

            except Exception as e:
                observation_manager.logger.error(
                    f"Critical error during database insertion: {e}")
                observation_manager.write_failed_files(
                    new_images, f"Insertion exception: {e}")
                continue

    except KeyboardInterrupt:
        print("\nProgram interrupted by the user. Exiting gracefully.")
