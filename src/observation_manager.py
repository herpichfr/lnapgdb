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
import glob
import time
import argparse
import logging
from miscellaneous import setup_logging
from data_collector import DataCollector
from insertdb import InsertDB


def parse_arguments():
    parser = argparse.ArgumentParser(description='Observation Manager')
    parser.add_argument('storage_dirs', nargs='*', default=[],
                        help='Root directories to monitor for new images')
    parser.add_argument('--config', type=str, default='config.json',
                        help='Path to the configuration file')
    parser.add_argument('--db_schema', type=str,
                        choices=['public', 'dev', 'cyc', 'prod'],
                        default='public',
                        help='Database schema to use for insertion')
    parser.add_argument('--nprocs', '-n', type=int, default=1,
                        help='Number of processes to use for parallel processing')
    parser.add_argument('--cadence', type=int, default=10,
                        help='Time interval (in seconds) to check for new images')
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

    return parser.parse_args()


class ObservationManager:
    def __init__(self, args):
        self.storage_dirs = args.storage_dirs
        self.root_dir = os.path.dirname(
            os.path.dirname(os.path.abspath(__file__)))
        self.config = self.load_config(os.path.join(
            self.root_dir, 'config', args.config))
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
    def load_primary_model(models_dir, logger=logging.getLogger()):
        """Get the primary model from the models directory."""
        primary_model_file = os.path.join(models_dir, 'primary_table.json')
        if os.path.exists(primary_model_file):
            logger.info(f'Loading primary model from {primary_model_file}')
            with open(primary_model_file, 'r') as f:
                primary_model_mapping = load(f)
        else:
            logger.critical(f'Primary model file not found: {
                            primary_model_file}')
            raise FileNotFoundError(f'Primary model file not found: {
                                    primary_model_file}')

        primary_model = {}
        for col in primary_model_mapping:
            colname = col['colname']
            primary_model[colname] = col

        return primary_model

    @staticmethod
    def load_instrument_models(config, models_dir, logger=logging.getLogger()):
        """Load instrument models from the configuration file."""

        instrument_models = {}
        for instrument in config.get('instruments'):
            instrument_models[instrument] = {}
            model_file = os.path.join(models_dir, f'{instrument}.json')
            if os.path.exists(model_file):
                logger.info(f'Loading model for {
                            instrument} from {model_file}')
                with open(model_file, 'r') as f:
                    instrument_models_mapping = load(f)
            else:
                logger.critical(f'Model file for {
                    instrument} not found: {model_file}')
                raise FileNotFoundError(f'Model file for {
                                        instrument} not found: {model_file}')

            for col in instrument_models_mapping:
                colname = col['colname']
                instrument_models[instrument][colname] = col

        return instrument_models

    def get_new_images(self):
        """
        Scan the root directories for new images and return a list of new image paths.
        """

        new_images = []

        # NOTE: For testing purposes
        if self.test:  # Get images from the root_dirs independently from the date
            self.logger.info(
                'Running in test mode: scanning for all images in the storage directories')
            new_images = glob.glob(os.path.join(
                self.storage_dirs[0], '*.fits'), recursive=True)
        else:
            # TODO: Implement a more efficient way to track new images
            for root_dir in self.storage_dirs:
                for dirpath, _, filenames in os.walk(root_dir):
                    for filename in filenames:
                        if filename.lower().endswith(('.fits', '.fit', '.fts')):
                            image_path = os.path.join(dirpath, filename)
                            if image_path not in self.processed_images:
                                new_images.append(image_path)
                                self.processed_images.add(image_path)

        return new_images


if __name__ == "__main__":
    args = parse_arguments()
    observation_manager = ObservationManager(args)
    # '/storage/raw_data/sparc4/channel1/20[2-9][0-9][0-3][0-9]/*.fits'
    # '/storage/raw_data/echarpe/channel1/20[2-9][0-9][0-3][0-9]/*.fits'

    new_images = observation_manager.get_new_images()

    instruments = observation_manager.config.get('instruments', [])

    for instrument in instruments:
        instrument_path_pattern = '/storage/raw_data/sparc4/channel1/20[2-9][0-9][0-3][0-9]/'
        # TODO: Think in a way to recover thousands of new images without breaking the pipeline.
        instrument_images = [img for img in new_images if instrument in img]
        observation_manager.logger.info(
            f'Found {len(instrument_images)} new images for instrument {instrument}')

    data_collector = DataCollector(
        new_images,
        primary_model=observation_manager.primary_model,
        instrument_models_cache=observation_manager.instrument_models,
        db_schema=args.db_schema,
        nprocs=args.nprocs,
        logger=observation_manager.logger,
        verbose=args.verbose,
        logfile=args.log_file,
        debug=args.debug,
    )

    p_df, i_df = data_collector.collect_data()

    # NOTE: This is the end for testing
    db_inserter = InsertDB(
        config=args.config,
        logger=observation_manager.logger
    )
    db_inserter.insert_batch(p_df, i_df, db_schema=args.db_schema)

    import pdb
    pdb.set_trace()
