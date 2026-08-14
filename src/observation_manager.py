#!/bin/python3

"""
Observation Manager

Create the database manager, which should be able to gather the new images from within a set of directories (whose could be defined in a config file)
Decide if we go for a config file or if we just use environment variables to set the directories to be monitored
The manager must be able to handle a large number of directories and images within
The code needs to keep track of the images that have already been processed
The list of new images at any given moment should be handled to the data_collector.py, which will extract the metadata, validate them and return as a pandas df
Finally, the manager haddles the df to the insertdb.py module for database insertion

Copyright (c) 2026, LNA - Laboratório Nacional de Astrofísica, Brazil. All rights reserved.
"""

import os
from json import load
import time
import argparse
import logging
import subprocess

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
                        help="List of test images to process in test mode")
    parser.add_argument('--log-level', type=str, default='WARNING',
                        help='Logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL)')
    parser.add_argument('--log-file', type=str, default='observation_manager.log',
                        help='Path to the log file')
    parser.add_argument('--debug', action='store_true',
                        help='Enable debug mode (sets log level to DEBUG)')
    parser.add_argument('--verbose', '-v', action='store_true',
                        help='Enable verbose logging')

    return parser.parse_args()


def get_git_branch():
    try:
        # Returns the name of the current branch
        branch = subprocess.check_output(
            ['git', 'rev-parse', '--abbrev-ref', 'HEAD'],
            stderr=subprocess.DEVNULL
        ).decode('utf-8').strip()
        return branch
    except Exception:
        # Fallback if git is not initialized or not installed
        return "dev"


def get_schema_from_branch(branch):
    if branch == 'main':
        return 'prod'
    elif branch == 'cyc':
        return 'cyc'
    elif branch == 'dev':
        return 'dev'
    elif '_dev' in branch:
        return 'public'  # or 'test'
    else:
        return 'public'  # Default fallback


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

        # Map string log level to logging integer constant
        level_map = {
            'DEBUG': logging.DEBUG,
            'INFO': logging.INFO,
            'WARNING': logging.WARNING,
            'ERROR': logging.ERROR,
            'CRITICAL': logging.CRITICAL
        }

        # Override to DEBUG if --debug is passed
        log_level_int = logging.DEBUG if args.debug else level_map.get(
            args.log_level.upper(), logging.WARNING)

        self.logger = setup_logging(
            loglevel=log_level_int,
            logfile=args.log_file,
            verbose=args.verbose
        )

        self.debug = args.debug
        self.test = args.test

        self.processed_images = set()

        # Models are kept here in case database_checker or file_watcher needs them,
        # but DataCollector now relies on Pydantic instead.
        self.models_dir = os.path.join(self.root_dir, 'models')
        self.primary_model = self.load_primary_model(
            self.models_dir, self.logger)
        self.instrument_models = self.load_instrument_models(
            self.config, self.models_dir, self.logger)

        self.last_check_time = time.time()
        self.cadence = args.cadence

    @staticmethod
    def load_config(config_path):
        with open(config_path, 'r') as f:
            return load(f)

    @staticmethod
    def load_primary_model(models_dir, logger=logging.getLogger()):
        """Get the primary model from the models directory."""
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
        """Load instrument models from the configuration file."""
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

    # Get schema from git branch
    git_branch = get_git_branch()
    db_schema_from_branch = get_schema_from_branch(git_branch)
    if db_schema_from_branch != db_schema:
        observation_manager.logger.warning(
            f"Git branch '{git_branch}' suggests using database schema '{db_schema_from_branch}', but config specifies '{db_schema}'.")
        observation_manager.logger.warning(
            "Please select which branch you want to use:"
            "1 - Use schema from config file"
            "2 - Use schema from git branch"
        )

        # Only prompt if we are in an interactive terminal
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
        # If test images are provided, process them directly
        observation_manager.logger.info(
            f"Processing test images: {args.test_images}")
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

        except Exception as e:
            observation_manager.logger.error(
                f'Error processing test images: {e}')
        exit(0)

    # After collecting storage directories, validate
    if not watcher.directories:
        observation_manager.logger.critical(
            'No valid directories found to monitor'
        )
        raise ValueError('No valid directories found to monitor')

    if args.check_db:
        db = InsertDB(
            config=observation_manager.config,
            args=args,
            logger=observation_manager.logger
        )

        checker = DatabaseChecker(
            directories=watcher.directories,
            db=db,
            date=args.date
        )

        checker.run()
        exit()

    # Enter main watch loop
    try:
        for new_images in watcher.watch():
            if not new_images:
                continue

            observation_manager.logger.info(
                f"Processing {len(new_images)} new images.")
            observation_manager.logger.debug(
                "Starting data collection process...")

            try:
                # Updated DataCollector signature to match the refactored module
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
                continue

            # If no valid data was collected, move to next batch
            if p_df.empty:
                observation_manager.logger.warning(
                    "No valid data collected from this batch. Skipping insertion.")
                continue

            try:
                db_inserter = InsertDB(
                    config=observation_manager.config,
                    args=args,
                    logger=observation_manager.logger
                )

                # insert_batch no longer takes debug arg; returns (success_bool, error_count)
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

            except Exception as e:
                observation_manager.logger.error(
                    f"Critical error during database insertion: {e}")
                continue

    except KeyboardInterrupt:
        print("\nProgram interrupted by the user. Exiting gracefully.")
