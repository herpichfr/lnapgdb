#!/bin/python3

"""
This module inserts data into the LNA DB. The data is loaded from the FITS
files generated during observations. The data is inserted into the database
using SQLAlchemy to handle a postgreSQL database. The data is inserted into
the tables defined in the model.py module, which defines the architecture of
the database. The data is inserted in a way that maintains the relationships
between the tables, and allows for cascading deletion. The data is inserted
in a way that maintains the normalization of the database to the third normal
form. The data is inserted in a way that maintains the integrity of the
database, and allows for efficient querying of the data.

The inserted data must comply with the schema and basic rules defined in the
model.py module.
"""

import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from model import Base, PrimaryTable, Sparc4, Echarpe
import argparse
from astropy.io import fits
import logging
from json import load


def parse_args():
    parser = argparse.ArgumentParser(
        description='Insert data into the LNA DB.')
    parser.add_argument('fits_file', type=str,
                        help='Path to the FITS file to be inserted into the database.')
    parser.add_argument('--verbose', '-v', action='store_true',
                        help='Enable verbose logging.')
    parser.add_argument('--logfile', '-l', type=str,
                        help='Path to the log file. If not provided, logs will be printed to the console.')
    parser.add_argument('--loglevel', type=str, choices=['DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL'],
                        default='INFO', help='Logging level. Default is INFO.')
    return parser.parse_args()


def setup_logging(verbose=False, logfile=None, loglevel=logging.INFO):
    logger = logging.getLogger(__name__)
    logger.setLevel(loglevel if verbose else logging.WARNING)

    formatter = logging.Formatter(
        '%(asctime)s [%(levelname)s] @%(module)s.%(funcName)s() %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S')

    if logfile:
        fh = logging.FileHandler(logfile)
        fh.setLevel(loglevel)
        fh.setFormatter(formatter)
        logger.addHandler(fh)
    else:
        ch = logging.StreamHandler()
        ch.setLevel(loglevel)
        ch.setFormatter(formatter)
        logger.addHandler(ch)
    return logger


def collect_header_keys(fits_file):
    try:
        with fits.open(fits_file) as hdul:
            header = hdul[0].header
    except Exception as e:
        print(f"Error reading FITS file: {e}")
        return None
    # Transform the header into a dictionary of key-value pairs
    header_data = {key: header[key] for key in header.keys()}
    return header_data


def get_primary_model():
    """Get the primary model class based on the header data."""
    # This function should determine which primary model to use based on the
    # header data. For example, if the header contains a key 'INSTRUME' with
    # value 'SPARC4', then the primary model should be Sparc4. If the header
    # contains a key 'INSTRUME' with value 'ECHARPE', then the primary model
    # should be Echarpe. If the header does not contain a key 'INSTRUME', then
    # the primary model should be PrimaryTable.
    # data directory
    data_dir = os.path.join(os.path.dirname(
        os.path.dirname(os.path.abspath(__file__))), 'data')
    # Load the JSON file in the one-derectory-up 'data' folder
    with open(os.path.expanduser(f'{data_dir}/primary_table.json'), 'r') as f:
        primary_model_mapping = load(f)

    primary_model = {}
    for col in primary_model_mapping:
        colname = col['colname']
        primary_model[colname] = col

    return primary_model


def validate_data(header_data, primary_model):
    """Validate the header data against the primary model schema."""
    datatypes_mapping = {
        'string': str,
        'integer': int,
        'float': float,
        'boolean': bool
    }

    for key, value in header_data.items():
        is_nullable = primary_model[key].get('nullable', True)
        datatype = primary_model[key].get('datatype', None)
        datatype = datatypes_mapping.get(
            datatype.lower(), str) if datatype else str
        # if datatype is bool, allowed values are True and False
        if datatype == bool:
            allowed_values = [True, False]
        else:
            allowed_values = primary_model[key].get('allowed_values', None)
            if '-' in allowed_values:
                allowed_values = allowed_values.split('-')
                minmax = True
            elif ',' in allowed_values:
                allowed_values = allowed_values.split(
                    ',') if allowed_values else None
                minmax = False
            else:
                allowed_values = [allowed_values] if allowed_values else None
                minmax = False
            allowed_values = [val.strip().format(datatype=datatype)
                              for val in allowed_values] if allowed_values else None

        if key in primary_model:
            if not is_nullable and value is None:
                raise ValueError(f"Key '{key}' cannot be null.")
            # TODO: Implement type checking and conversion based on the datatype defined in the primary model
            # Take into account for the possibility of min and max or fixed allowed values
            if allowed_values and value not in allowed_values:
                raise ValueError(
                    f"Key '{key}' has value '{value}' which is not in the allowed values: {allowed_values}.")
        elif key not in primary_model:
            if not is_nullable:
                raise ValueError(
                    f"Key '{key}' is not defined in the primary model and cannot be null.")

        import pdb
        pdb.set_trace()


def insert_data(session, header_data):
    """Insert data into the database based on the header data."""


def main(args):
    """Collect metadata and insert into the database."""
    logger = setup_logging(args.verbose, args.logfile,
                           getattr(logging, args.loglevel))
    fits_file = args.fits_file
    header_keys = collect_header_keys(fits_file)
    primary_model = get_primary_model()
    validate_data(header_keys, primary_model)

    import pdb
    pdb.set_trace()


if __name__ == '__main__':
    args = parse_args()
    main(args)
