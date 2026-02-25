#!/bin/python3

"""
This module collect the header information of a list of raw files, validate
the values against the data model defined in model.py, and format the data as
a pandas table to be uset for insertion into the database.
"""

import os
import pandas as pd
from astropy.io import fits
from json import load
import glob
import argparse
from miscellaneous import setup_logging
import logging
from concurrent.futures import ProcessPoolExecutor
from bisect import bisect_right
from functools import partial


def parse_args():
    parser = argparse.ArgumentParser(
        description="Collect and validate FITS header data for database insertion.")
    parser.add_argument(
        '--directory', '-d', required=True, help="Directory containing FITS files.")
    parser.add_argument(
        '--db_schema', '-s', default='dev', help="Database schema to use (default: dev).")
    parser.add_argument(
        '--nprocs', '-n', type=int, default=4, help="Number of parallel processes to use (default: 4).")
    parser.add_argument(
        '--verbose', '-v', action='store_true', help="Enable verbose logging.")
    parser.add_argument(
        '--logfile', '-l', default='log/data_collection.log', help="Log file path (default: log/data_collection.log).")
    parser.add_argument(
        '--debug', action='store_true', help="Run in test mode with limited files for quick testing.")
    return parser.parse_args()


class DataCollector:
    def __init__(self,
                 directory,
                 db_schema='dev',
                 nprocs=4,
                 verbose=False,
                 logfile='log/data_collection.log',
                 debug=False):
        self.directory = directory
        self.db_schema = db_schema
        self.nprocs = nprocs
        self.logger = setup_logging(verbose=verbose, logfile=logfile)
        self.debug = debug
        self.data_dir = os.path.join(os.path.dirname(
            os.path.dirname(os.path.abspath(__file__))), 'data')
        self.last_processed_file = None  # To track the last processed file

        # Pre-load primary data model
        self.primary_model = self.get_primary_model()
        # Pre-cache instrument models to avoid repeated file reads
        self.instrument_models_cache = {
            'sparc4': self.get_instrument_model('sparc4'),
            'echarpe': self.get_instrument_model('echarpe')
        }

    def collect_new_files(self):
        """Collect and validate FITS header data for database insertion."""
        self.logger.info(
            f"Starting data collection from directory: {self.directory}")

        # Get list of FITS files in the directory
        fits_files = sorted(glob.glob(os.path.join(self.directory, "*.fits")))
        self.logger.info(
            f"Found {len(fits_files)} FITS files in the directory.")

        # Filter out already processed files
        if self.last_processed_file:
            # Binary search to find the index of the last processed file
            index = bisect_right(fits_files, self.last_processed_file)
            fits_files = fits_files[index:]
            self.logger.info(
                f"{len(fits_files)} new FITS files to process after filtering.")

        if not fits_files:
            self.logger.info("No new FITS files to process.")
            return []

        return fits_files

    @staticmethod
    def process_file(file, primary_model=None, instrument_models_cache=None, logger=logging.getLogger(__name__)):
        """Process a single FITS file: extract header, validate, and return data."""
        logger.debug(f"Processing file: {file}")
        try:
            with fits.open(file, checksum=True) as hdul:
                header = hdul[0].header

                # primary_model = DataCollector.get_primary_model()
                instrument = header.get('INSTRUME', None).lower(
                ) if header.get('INSTRUME', None) else None
                if instrument is None:
                    logger.critical(
                        f"File '{file}' is missing 'INSTRUME' keyword in header.")
                    return None
                instrument_model = instrument_models_cache.get(
                    instrument, None) if instrument_models_cache else DataCollector.get_instrument_model(instrument)
                if not instrument_model:
                    logger.critical(
                        f"File '{file}' has unknown instrument '{instrument}' in header.")
                    return None

                is_valid, primary_data, instrument_data = DataCollector.validate_data(
                    header, primary_model, instrument_model, logger)

                if is_valid:
                    logger.debug(
                        f"File '{file}' passed validation successfully.")

                    return {**primary_data, **instrument_data}
                else:
                    logger.error(
                        f"File '{file}' failed validation and will be skipped.")
                    return None
        except Exception as e:
            logger.error(f"Error processing file '{file}': {e}")
            return None

    def collect_data(self):
        """Collect and validate FITS header data for database insertion."""
        new_fits_files = self.collect_new_files()
        if not new_fits_files:
            return pd.DataFrame()  # Return empty DataFrame if no new files

        worker = partial(self.process_file,
                         primary_model=self.primary_model,
                         instrument_models_cache=self.instrument_models_cache,
                         logger=self.logger)

        if self.debug or len(new_fits_files) < self.nprocs or self.nprocs <= 1:
            self.logger.warning(
                "Debug mode enabled or not enough files for parallel processing. Processing sequentially.")
            data = [worker(file) for file in new_fits_files]
        else:
            self.logger.info(
                f"Processing {len(new_fits_files)} files using {self.nprocs} parallel processes.")
            # NOTE: The multiprocessing part is not yet tested
            with ProcessPoolExecutor(max_workers=self.nprocs) as executor:
                data = list(executor.map(worker, new_fits_files))

        # Filter out None results (failed validations)
        valid_data = [d for d in data if d is not None]
        self.logger.info(f"Successfully processed {len(valid_data)} files.")

        self.last_processed_file = new_fits_files[-1] if new_fits_files else self.last_processed_file
        print(f"Last processed file: {self.last_processed_file}")

        return pd.DataFrame(valid_data)

    @staticmethod
    def validate_data(
            header_data,
            primary_model,
            instrument_model,
            logger=logging.getLogger(__name__)
    ):
        """Validate header data against primary and instrument models."""

        primary_data = {}
        instrument_data = {}

        for key, value in header_data.items():
            if key in primary_model:
                is_nullable = primary_model[key].get('nullable', True)

                if not is_nullable and value is None:
                    logger.critical(
                        f"Key '{key}' is not defined in the primary model and \
                        cannot be null.")
                    return False, primary_data, instrument_data

                allowed_values, datatype, minmax = DataCollector.get_allowed_values(
                    primary_model, key)

                # Make sure the datatype coresponds to the datatype defined in the model
                try:
                    value = datatype(value)
                except ValueError as e:
                    logger.error(
                        f"Key '{key}' has value '{value}' which cannot be \
                        converted to the required datatype '{datatype.__name__}'. \
                        Error: {e}")
                    return False, primary_data, instrument_data

                if minmax:
                    if not (isinstance(value, datatype) and allowed_values[0] <= value <= allowed_values[1]):
                        logger.error(
                            f"Key '{key}' has value '{value}' which is not within \
                            the allowed range:\
                            {allowed_values[0]} - {allowed_values[1]}.")
                        return False, primary_data, instrument_data
                    else:
                        logger.debug(
                            f"Key '{key}' has value '{value}' which is within the \
                            allowed range:\
                            {allowed_values[0]} - {allowed_values[1]}.")
                else:
                    if allowed_values and value not in allowed_values:
                        logger.error(
                            f"Key '{key}' has value '{value}' which is not in the \
                            allowed values: {allowed_values}.")
                        return False, primary_data, instrument_data

                primary_data[key] = value

            elif key in instrument_model:
                is_nullable = instrument_model[key].get('nullable', True)
                if not is_nullable:
                    logger.critical(
                        f"Key '{key}' is not defined in the instrument model and \
                        cannot be null.")
                    return False, primary_data, instrument_data

                allowed_values, datatype, minmax = DataCollector.get_allowed_values(
                    instrument_model, key)

                try:
                    value = datatype(value)
                except ValueError as e:
                    logger.error(
                        f"Key '{key}' has value '{value}' which cannot be \
                        converted to the required datatype \
                        '{datatype.__name__}'. Error: {e}")
                    return False, primary_data, instrument_data

                if minmax:
                    if not (isinstance(value, datatype) and allowed_values[0] <= value <= allowed_values[1]):
                        logger.error(
                            f"Key '{key}' has value '{value}' which is not within \
                            the allowed range: \
                            {allowed_values[0]} - {allowed_values[1]}.")
                        return False, primary_data, instrument_data
                    else:
                        logger.debug(
                            f"Key '{key}' has value '{value}' which is within the \
                            allowed range: \
                            {allowed_values[0]} - {allowed_values[1]}.")

                instrument_data[key] = value
            else:
                logger.warning(
                    f"Key '{key}' is not defined in either the primary model or \
                    the instrument model and will be ignored.")

        # NOTE: Loop through the primary model and instrument model to check if
        # there are any required keys that are missing in the header data
        for key, value in primary_model.items():
            if not value.get('nullable', True) and key not in primary_data:
                logger.critical(
                    f"Key '{key}' is required in the primary model but is missing \
                    in the header data.")
                return False, primary_data, instrument_data
        for key, value in instrument_model.items():
            if not value.get('nullable', True) and key not in instrument_data:
                logger.critical(
                    f"Key '{key}' is required in the instrument model but is \
                    missing in the header data.")
                return False, primary_data, instrument_data

        logger.info("Header data validation successful.")
        return True, primary_data, instrument_data

    @staticmethod
    def get_allowed_values(data_model, key):

        datatypes_mapping = {
            'string': str,
            'integer': int,
            'float': float,
            'boolean': bool
        }
        datatype = data_model[key].get('datatype', None)
        datatype = datatypes_mapping.get(
            datatype.lower(), str) if datatype else str
        # if datatype is bool, allowed values are True and False
        if datatype == bool:
            allowed_values = [True, False]
            minmax = False
        else:
            allowed_values = data_model[key].get('allowed_values', None)
            if allowed_values is not None:
                if 'between' in allowed_values.lower():
                    allowed_values = allowed_values.split(':')[
                        1].split(',')
                    min_val, max_val = allowed_values
                    # Trasnform min_val and max_val to the correct datatype
                    if 'inf' in min_val.lower():
                        min_val = float('-inf')
                    else:
                        min_val = datatypes_mapping.get(data_model[key].get(
                            'datatype', 'string').lower(), str)(min_val)
                    if 'inf' in max_val.lower():
                        max_val = float('inf')
                    else:
                        max_val = datatypes_mapping.get(data_model[key].get(
                            'datatype', 'string').lower(), str)(max_val)
                    allowed_values = (min_val, max_val)
                    minmax = True
                elif ',' in allowed_values:
                    allowed_values = allowed_values.split(
                        ',') if allowed_values else None
                    minmax = False
                else:
                    allowed_values = [
                        allowed_values] if allowed_values else None
                    minmax = False
            else:
                minmax = False

        return allowed_values, datatype, minmax

    @staticmethod
    def get_primary_model():
        """Get the primary model class based on the header data."""
        # This function should determine which primary model to use based on the
        # header data. For example, if the header contains a key 'INSTRUME' with
        # value 'SPARC4', then the primary model should be Sparc4. If the header
        # contains a key 'INSTRUME' with value 'ECHARPE', then the primary model
        # should be Echarpe.
        # data directory
        data_dir = os.path.join(os.path.dirname(
            os.path.dirname(os.path.abspath(__file__))), 'data')
        # Load the JSON file in the one-directory-up 'data' folder
        with open(os.path.expanduser(f'{data_dir}/primary_table.json'), 'r') as f:
            primary_model_mapping = load(f)

        primary_model = {}
        for col in primary_model_mapping:
            colname = col['colname']
            primary_model[colname] = col

        return primary_model

    @staticmethod
    def get_instrument_model(instrument):
        """Get the instrument model class based on the header data."""
        if instrument is None:
            raise ValueError("Instrument key is missing in the header data.")

        data_dir = os.path.join(os.path.dirname(
            os.path.dirname(os.path.abspath(__file__))), 'data')
        with open(os.path.expanduser(f'{data_dir}/{instrument.lower()}.json'), 'r') as f:
            instrument_model_mapping = load(f)
        instrument_model = {}
        for col in instrument_model_mapping:
            colname = col['colname']
            instrument_model[colname] = col
        return instrument_model


if __name__ == "__main__":
    args = parse_args()
    collector = DataCollector(
        directory=args.directory,
        db_schema=args.db_schema,
        nprocs=args.nprocs,
        verbose=args.verbose,
        logfile=args.logfile,
        debug=args.debug
    )
    data_df = collector.collect_data()
    print(data_df.head())
