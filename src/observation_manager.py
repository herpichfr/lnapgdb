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
from pathlib import Path
import glob
import time
import argparse
import logging
import subprocess
from miscellaneous import setup_logging
from data_collector import DataCollector
from insertdb import InsertDB
from file_watcher import FileWatcher



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
    parser.add_argument('--log-level', type=str, default='WARNING',
                        help='Logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL)')
    parser.add_argument('--log-file', type=str, default='observation_manager.log',
                        help='Path to the log file')
    parser.add_argument('--debug', action='store_true',
                        help='Enable debug mode (sets log level to DEBUG)')
    parser.add_argument('--test', action='store_true',
                        help='Run in test mode (processes a predefined set of test images)')
    parser.add_argument('--verbose', '-v', action='store_true',
                        help='Enable verbose logging')
    parser.add_argument('--watch-dir', nargs='+', 
                        help='Directories to watch for new images')
    parser.add_argument('--cadence', type=int, default=10,
                        help='Time interval (in seconds) to check for new images')

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
        
        self.db_config = self.load_db_config(self.root_dir)
        self.db_schema = self.config.get('db_schema') if self.config.get(
            'db_schema') else args.db_schema
        
        self.logger = setup_logging(
            args.log_level, args.log_file, args.verbose)
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

    @staticmethod
    def load_config(config_path):
        with open(config_path, 'r') as f:
            return load(f)
    
    @staticmethod
    def load_db_config(root_dir):
        credentials_path = os.path.join(root_dir, 'credentials', 'db_config.json')

        if not os.path.exists(credentials_path):
            raise FileNotFoundError(
                f'Database credentials file not found: {credentials_path}'
            )

        with open(credentials_path, 'r') as f:
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
                logger.critical(f'Model name not defined for {instrument_name}')
                raise ValueError(f'Model name not defined for {instrument_name}')

            model_file = os.path.join(models_dir, model_name)

            if os.path.exists(model_file):
                logger.info(f'Loading model for {instrument_name} from {model_file}')
                with open(model_file, 'r') as f:
                    instrument_models_mapping = load(f)
            else:
                logger.critical(f'Model file for instrument {instrument_name} not found: {model_file}')
                raise FileNotFoundError(
                    f'Model file for {instrument_name} not found: {model_file}'
                )
            
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
            poll_interval=args.cadence
        )
    else:
        watcher = FileWatcher(
            config=observation_manager.config,
            poll_interval=args.cadence
        )
    

    # Get schema from git branch
    git_branch = get_git_branch()
    db_schema_from_branch = get_schema_from_branch(git_branch)
    if db_schema_from_branch != db_schema:
        observation_manager.logger.warning(
            f"Git branch '{git_branch}' suggests using database schema '{db_schema_from_branch}', but config specifies '{db_schema}'. Using '{db_schema}' as specified in config.")
        user_input = input("Do you want to continue? (Y/n): ")
        if user_input.lower() == 'n':
            observation_manager.logger.info("Exiting as per user request.")
            exit(0)


    # After collecting storage directories, validate
    if not watcher.directories:
        observation_manager.logger.critical(
            'No valid directories found to monitor'
        )
        raise ValueError('No valid directories found to monitor')
    
    if args.watch_dir:
        watcher = FileWatcher(
            directories=args.watch_dir,
            poll_interval=args.cadence
        )
    else:
        watcher = FileWatcher(
            config=observation_manager.config,
            poll_interval=args.cadence
        )

    for new_images in watcher.watch():    
        print(f"DEBUG: Processing {len(new_images)} new images")
        print("DEBUG: Starting data collection process...[observation_manager-270]")

        try:
            data_collector = DataCollector(
                new_images,
                primary_model=observation_manager.primary_model,
                instrument_models_cache=observation_manager.instrument_models,
                db_schema=db_schema,
                nprocs=args.nprocs,
                logger=observation_manager.logger,
                verbose=args.verbose,
                logfile=args.log_file,
                debug=args.debug,
            )

            p_df, i_df = data_collector.collect_data()
            print("DEBUG: Data collection process finished.[observation_manager-283]")
            print(f"DEBUG: Primary data (p_df): {p_df}")
            print(f"DEBUG: Instrument data (i_df): {i_df}")

        except Exception as e:
            observation_manager.logger.error(
                f'Error collecting data from images: {e}'
            )
            continue

        try:
            db_inserter = InsertDB(
                config=observation_manager.config,
                db_config=observation_manager.db_config,
                logger=observation_manager.logger
            )

            inserted, error_code = db_inserter.insert_batch(
                p_df, i_df, db_schema=db_schema, debug=args.debug
            )

            if inserted:
                observation_manager.logger.info(
                    f'Data inserted successfully into the database with code {error_code}'
                )
            else:
                observation_manager.logger.error(
                    f'Failed to insert data into the database with code {error_code}'
                )

        except Exception as e:
            observation_manager.logger.error(
                f'Error inserting data into database: {e}'
            )