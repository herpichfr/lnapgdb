#!/bin/python3

"""
This module collect the header information of a list of raw files, validate
the values against the data model defined in model.py, and format the data as
a pandas table to be uset for insertion into the database.
"""

import os
import glob
import logging
import argparse
import datetime
import pandas as pd
from astropy.io import fits
from concurrent.futures import ProcessPoolExecutor
from pydantic import BaseModel, Field, ValidationError, field_validator

# We use a module-level logger fetching strategy to avoid Multiprocessing Pickle errors


def get_worker_logger():
    return logging.getLogger("lnapgdb")

# ---------------------------------------------------------
# PYDANTIC MODELS (Replaces manual validate_data)
# ---------------------------------------------------------
# By defining these, Pydantic handles type coercion (str -> float),
# bounds checking (ge, le), and nullability automatically.


class PrimaryHeaderModel(BaseModel):
    INSTRUME: str = Field(..., description="Instrument name")
    FILENAME: str = Field(..., description="Original filename")

    # Example of bounds checking replacing the "between:X,Y" logic
    # ge = greater than or equal to, le = less than or equal to
    OBSLAT: float = Field(..., ge=-90.0, le=90.0)
    OBSLONG: float = Field(..., ge=-180.0, le=180.0)

    @field_validator('OBSLAT', 'OBSLONG', mode='before')
    @classmethod
    def convert_dms(cls, v):
        """Automatically converts DMS strings to floats before validation."""
        if isinstance(v, (int, float)):
            return float(v)
        try:
            parts = str(v).split(':')
            if len(parts) == 3:
                degrees, minutes, seconds = map(float, parts)
                # Handle negative degrees properly
                sign = -1 if degrees < 0 else 1
                return sign * (abs(degrees) + (minutes / 60) + (seconds / 3600))
            return float(v)
        except ValueError:
            raise ValueError(f"Invalid DMS format: {v}")

# ---------------------------------------------------------
# DATA COLLECTOR CLASS
# ---------------------------------------------------------


class DataCollector:
    def __init__(
            self,
            fits_files,
            db_schema='dev',
            nprocs=4,
            config=None,
            debug=False
    ):
        self.fits_files = fits_files
        self.db_schema = db_schema
        self.nprocs = nprocs
        self.config = config or {}
        self.debug = debug
        self.logger = get_worker_logger()

    @staticmethod
    def process_file(file_path):
        """
        Worker function. Must be static and not rely on 'self' to remain picklable 
        for ProcessPoolExecutor.
        """
        logger = get_worker_logger()
        logger.debug(f"Processing file: {file_path}")

        result = {
            'error': False,
            'file': file_path,
            'instrument_name': 'unknown',
            'primary': {},
            'instrument': {}
        }

        # 1. Read File Safely
        try:
            # ignore_missing_end is critical for astronomy pipelines
            with fits.open(file_path, ignore_missing_end=True, checksum=True) as hdul:
                raw_header = dict(hdul[0].header)
        except Exception as e:
            logger.error(f"Error opening file '{file_path}': {e}")
            result['error'] = True
            return result

        raw_header['FILENAME'] = os.path.basename(file_path)
        instrument = raw_header.get('INSTRUME', '').lower().strip()
        result['instrument_name'] = instrument or 'unknown'

        if not instrument:
            logger.critical(
                f"File '{file_path}' is missing 'INSTRUME' keyword.")
            result['error'] = True
            return result

        # 2. Validate using Pydantic (Replacing validate_data)
        try:
            # This single line handles type casting, bounds checking, and null checks!
            validated_primary = PrimaryHeaderModel(**raw_header)

            # Extract out-of-model fields
            primary_dict = validated_primary.model_dump()
            primary_dict['raw_path'] = os.path.abspath(file_path)

            result['primary'] = primary_dict
            # Note: You would instantiate your specific instrument model here too
            # result['instrument'] = Sparc4Model(**raw_header).model_dump()

            logger.debug(f"File '{file_path}' passed validation.")

        except ValidationError as e:
            logger.error(f"Validation failed for '{file_path}': {e}")
            result['error'] = True

        return result

    def collect_data(self):
        """Collect and validate FITS header data in parallel."""
        files_to_process = self.fits_files[:
                                           10] if self.debug else self.fits_files

        if not files_to_process:
            return pd.DataFrame(), pd.DataFrame()

        # Execute processing
        if self.debug or self.nprocs <= 1:
            self.logger.info("Processing sequentially.")
            data = [self.process_file(f) for f in files_to_process]
        else:
            self.logger.info(f"Processing {len(files_to_process)} files using {
                             self.nprocs} workers.")
            with ProcessPoolExecutor(max_workers=self.nprocs) as executor:
                data = list(executor.map(self.process_file, files_to_process))

        # Split results
        valid_data = [d for d in data if not d['error']]
        failed_data = [d for d in data if d['error']]

        self.logger.info(f"Successfully processed {len(
            valid_data)} files. Failed: {len(failed_data)}")

        # Handle Failures
        if failed_data:
            self._log_failures(failed_data)

        if not valid_data:
            return pd.DataFrame(), pd.DataFrame()

        # Convert to DataFrames
        primary_df = pd.DataFrame([d['primary'] for d in valid_data])
        instrument_df = pd.DataFrame([d['instrument'] for d in valid_data])

        return primary_df, instrument_df

    def _log_failures(self, failed_data):
        """Handles logging of failed files grouped by instrument."""
        data_root = self.config.get("data_root", "log")
        failed_by_inst = {}

        for item in failed_data:
            inst = item.get('instrument_name', 'unknown')
            failed_by_inst.setdefault(inst, []).append(item['file'])

        for inst, files in failed_by_inst.items():
            failed_dir = os.path.join(data_root, f"{inst}_failed")
            os.makedirs(failed_dir, exist_ok=True)

            log_path = os.path.join(failed_dir, "failed_fits.log")
            with open(log_path, "a") as f:
                for file in files:
                    f.write(f"{datetime.datetime.now().isoformat()} - {file}\n")

            self.logger.info(f"Saved {len(files)} failed {
                             inst} logs to: {log_path}")


# ---------------------------------------------------------
# EXECUTION
# ---------------------------------------------------------
if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument('--fits_files', required=True,
                        help="Glob pattern for FITS files.")
    parser.add_argument('--nprocs', type=int, default=4)
    parser.add_argument('--debug', action='store_true')
    args = parser.parse_args()

    files = glob.glob(args.fits_files)

    collector = DataCollector(
        fits_files=files, nprocs=args.nprocs, debug=args.debug)
    primary_df, instrument_df = collector.collect_data()

    print(f"Collected {len(primary_df)} primary records.")
