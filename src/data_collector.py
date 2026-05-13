#!/bin/python3

"""
This module collect the header information of a list of raw files, validate
the values against the data model defined in model.py, and format the data as
a pandas table to be uset for insertion into the database.
"""

import os
import pandas as pd
from astropy.io import fits
import glob
import argparse
from miscellaneous import setup_logging
import logging
from concurrent.futures import ProcessPoolExecutor
from functools import partial
import datetime


def parse_args():
    parser = argparse.ArgumentParser(
        description="Collect and validate FITS header data for database insertion.")
    parser.add_argument(
        '--fits_files', '-f', required=True, help="List of FITS files.")
    parser.add_argument(
        '--db_schema', '-s', default=None,
        help="Database schema to use (default: dev).")
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
                 fits_files,
                 primary_model=None,
                 instrument_models_cache=None,
                 db_schema='dev',
                 nprocs=4,
                 logger=None,
                 verbose=False,
                 logfile='log/data_collection.log',
                 config=None,
                 debug=False):
        self.fits_files = fits_files
        self.primary_model = primary_model
        self.instrument_models_cache = instrument_models_cache or {}
        self.db_schema = db_schema
        self.nprocs = nprocs
        self.logger = logger if logger else setup_logging(
            verbose=verbose, logfile=logfile, loglevel=logging.DEBUG if debug else logging.INFO)
        self.debug = debug
        self.error_log_file = "failed_fits.log"
        self.config = config

    def __repr__(self):
        return f"DataCollector(fits_files='{self.fits_files}', db_schema='{self.db_schema}', nprocs={self.nprocs}, debug={self.debug})"

    @staticmethod
    def process_file(file, primary_model=None, instrument_models_cache=None, logger=logging.getLogger(__name__)):
        """Process a single FITS file: extract header, validate, and return data."""
        logger.debug(f"Processing file: {file}")
        raw_full_filename = os.path.abspath(file)

        try:
            with fits.open(file, checksum=True) as hdul:
                header = hdul[0].header
        except Exception as e:
            logger.error(f"Error opening file '{file}': {e}")
            return {
                'error': True,
                'file': file,
                'instrument_name': None
            }

        # primary_model = DataCollector.get_primary_model()
        instrument = header.get('INSTRUME', None).lower(
        ) if header.get('INSTRUME', None) else None

        if instrument is None:
            logger.critical(
                f"File '{file}' is missing 'INSTRUME' keyword in header.")
            return {
                'error': True,
                'file': file,
                'instrument_name': None
            }
        instrument_model = instrument_models_cache.get(
            instrument, None) if instrument_models_cache else DataCollector.get_instrument_model(instrument)

        if not instrument_model:
            logger.critical(
                f"File '{file}' has unknown instrument '{instrument}' in header.")
            return {
                'error': True,
                'file': file,
                'instrument_name': instrument
            }

        is_valid, primary_data, instrument_data = DataCollector.validate_data(
            header, primary_model, instrument_model, logger)

        # NOTE: Add out-of-model raw_path to the primary data. This needs to
        # happen here to garantee that the path is associated with the correct file
        primary_data['raw_path'] = raw_full_filename

        if is_valid:
            logger.debug(
                f"File '{file}' passed validation successfully.")

            return {
                'primary': primary_data,
                'instrument': instrument_data,
                'instrument_name': instrument,
                'file': file
            }
        else:
            logger.error(
                f"File '{file}' failed validation and will be skipped.")
            return {
                'error': True,
                'file': file,
                'instrument_name': instrument if 'instrument' in locals() else None
            }

    def collect_data(self):
        """Collect and validate FITS header data for database insertion."""
        new_fits_files = self.fits_files
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
            with ProcessPoolExecutor(max_workers=self.nprocs) as executor:
                data = list(executor.map(worker, new_fits_files))

        # NOTE: Save the filenames that failed validation for later review
        valid_data = [d for d in data if d and not d.get('error')]
        failed_data = [d for d in data if d and d.get('error')]
        self.logger.info(f"Successfully processed {len(valid_data)} files.")

        failed_dirs = {}
        if self.config:
            data_root = self.config.get("data_root", "")
            instruments = self.config.get("instruments", {})

            for name, data in instruments.items():
                failed_dir = data.get("failed_directory")
                if failed_dir:
                    full_path = os.path.join(data_root, failed_dir)
                    failed_dirs[name.lower()] = full_path

        #  Categorize errors by instrument
        failed_by_instrument = {}

        for item in failed_data:
            inst = item.get('instrument_name') or 'unknown'
            failed_by_instrument.setdefault(inst, []).append(item['file'])

        # Save in the correct directory
        for inst, files in failed_by_instrument.items():
            failed_dir = failed_dirs.get(inst)
            if not failed_dir:
                if self.config:
                    failed_dir = os.path.join(self.config.get(
                        "data_root", ""), "unknown/failed")
                else:
                    failed_dir = "log/unknown_failed"

            os.makedirs(failed_dir, exist_ok=True)

            log_path = os.path.join(failed_dir, "failed_fits.log")

            with open(log_path, "a") as f:
                for file in files:
                    f.write(f"{datetime.datetime.now()} - {file}\n")
            self.logger.info(f"Saved failed files log to: {log_path}")

        # Transform the list of dictionaries into two pandas DataFrame, one for primary and other for the instrumebt
        if not valid_data:
            return pd.DataFrame(), pd.DataFrame()

        primary_df = pd.DataFrame([d['primary'] for d in valid_data])
        instrument_df = pd.DataFrame([d['instrument'] for d in valid_data])

        return primary_df, instrument_df

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


if __name__ == "__main__":
    args = parse_args()
    fits_files = glob.glob(args.fits_files) if not args.debug else glob.glob(
        args.fits_files)[:10]
    collector = DataCollector(
        fits_files=fits_files,
        db_schema=args.db_schema,
        nprocs=args.nprocs,
        verbose=args.verbose,
        logfile=args.logfile,
        debug=args.debug
    )

    df = collector.collect_data()
