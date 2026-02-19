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
from astropy.io import fits
from json import load
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from model import Base, PrimaryTable, Sparc4, Echarpe
import argparse
import logging


def parse_args():
    parser = argparse.ArgumentParser(
        description='Insert data into the LNA DB.')
    parser.add_argument('fits_file',
                        type=str,
                        help='Path to the FITS file to be inserted into \
                        the database.')
    parser.add_argument('--verbose', '-v',
                        action='store_true',
                        help='Enable verbose logging.')
    parser.add_argument('--logfile', '-l',
                        type=str,
                        help='Path to the log file. If not provided, logs \
                        will be printed to the console.')
    parser.add_argument('--loglevel',
                        type=str,
                        choices=['DEBUG', 'INFO',
                                 'WARNING', 'ERROR', 'CRITICAL'],
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


def validate_data(
        header_data,
        primary_model,
        instrument_model,
        logger=logging.getLogger(__name__)
):
    """Validate the header data against the primary model schema."""

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

            allowed_values, datatype, minmax = get_allowed_values(
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

            allowed_values, datatype, minmax = get_allowed_values(
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


def get_db_credentials():
    """Get DB credentials from the the credentials config file."""
    cred_dir = os.path.join(os.path.dirname(
        os.path.dirname(os.path.abspath(__file__))), 'credentials')

    with open(os.path.expanduser(f'{cred_dir}/config.json'), 'r') as f:
        data = load(f)
    return data['lnapgdatabase']


def create_db_session():
    """Create a database session."""
    creds = get_db_credentials()
    engine = create_engine(
        f"postgresql://{creds['username']}:{creds['password']
                                            }@{creds['host']}:{creds['port']}/{creds['database']}")
    Session = sessionmaker(bind=engine)
    return Session()


def insert_data(session, primary_data, instrument_data, primary_model, instrument_model):
    """Insert data into the database based on the header data."""


def main(args):
    """Collect metadata and insert into the database."""
    logger = setup_logging(args.verbose, args.logfile,
                           getattr(logging, args.loglevel))
    fits_file = args.fits_file
    header_keys = collect_header_keys(fits_file)
    primary_model = get_primary_model()
    instrument = header_keys['INSTRUME'] if 'INSTRUME' in header_keys else None
    instrument_model = get_instrument_model(instrument)
    valid, primary_data, instrument_data = validate_data(
        header_keys, primary_model, instrument_model, logger)
    if not valid:
        logger.critical(
            f"Data validation failed. Aborting data insertion for file \
            '{fits_file}'.")
        return
    else:
        # Check if the primary_data and instrument data are not empty
        if not primary_data:
            logger.critical(
                f"No valid data found for the primary model in file \
                '{fits_file}'.")
            return
        if not instrument_data:
            logger.critical(
                f"No valid data found for the instrument model in file \
                '{fits_file}'.")
            return
        logger.info(f"Data validation successful. Proceeding with data \
        insertion for file '{fits_file}'.")

    session = create_db_session()
    # TODO: Implement the insert_data function to handle the actual insertion
    # of data into the database based on the primary_data and instrument_data
    insert_data(session, primary_data, instrument_data,
                primary_model, instrument_model)
    # session.commit()
    logger.info(f"Data insertion successful for file '{fits_file}'.")


if __name__ == '__main__':
    args = parse_args()
    main(args)
