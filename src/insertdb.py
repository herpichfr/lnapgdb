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
from sqlalchemy import create_engine, MetaData, Table, insert, text
from sqlalchemy.orm import sessionmaker
from model import Base
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
    parser.add_argument('--debug',
                        action='store_true',
                        help='Enable debug mode with pdb breakpoints.')
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
    Base.metadata.reflect(bind=engine)  # Reflect the existing database schema
    Session = sessionmaker(bind=engine)
    return Session()


def add_outofmodel_columns(args):
    """
    Here is reserved space to add out-of-model columns to the database tables.
    This is for columns that are. They need to be defined first in the
    model.py module and their values must be defined in this function.
    """
    # NOTE: Add the full file path to the primary data for reference
    outofmodel_data = {}
    full_file_path = os.path.abspath(args.fits_file)
    outofmodel_data['raw_path'] = full_file_path

    # NOTE: Add instrument-specific out-of-model data based on the INSTRUME
    # key in the header

    # This is a test. Remove it and add real out-of-model data as needed
    outofmodel_data['test_key'] = 'test_value'

    return outofmodel_data


def insert_data(
        session,
        primary_data,
        instrument_data,
        args,
        logger=logging.getLogger(__name__)
):
    """
    Insert data into the database based on the header data.
    """

    metadata = MetaData()
    engine = session.get_bind()

    # Gather out-of-model data to be inserted into the database
    additional_data = add_outofmodel_columns(args)
    # Get column names from the primary table to filter the additional data
    primary_cols = Table('primary_table', metadata,
                         autoload_with=engine).columns.keys()
    instrument_cols = Table(primary_data['INSTRUME'].lower(), metadata,
                            autoload_with=engine).columns.keys()
    # Filter the additional data to include only keys that are valid columns
    additional_primary = {}
    additional_instrument = {}
    for col in additional_data.keys():
        if col in primary_cols:
            additional_primary[col] = additional_data[col]
        elif col in instrument_cols:
            additional_instrument[col] = additional_data[col]
        else:
            logger.warning(
                f"Out-of-model data key '{col}' is not a valid column in \
                either the primary table or the instrument table and will be \
                ignored.")

    # Update the primary and instrument data with the additional out-of-model data
    if additional_primary:
        logger.info(
            f"Adding out-of-model data to primary data: {additional_primary}")
        primary_data.update(additional_primary)
    if additional_instrument:
        logger.info(
            f"Adding out-of-model data to instrument data: {additional_instrument}")
        instrument_data.update(additional_instrument)

    try:
        primary_t = Table('primary_table', metadata, autoload_with=engine)
        logger.info("Inserting data into the primary_table...")
        session.execute(insert(primary_t).values(**primary_data))

        # Get the ID of the newly inserted primary entry to use as a foreign key in the instrument table
        query = text(
            "SELECT id FROM public.primary_table ORDER BY id DESC LIMIT 1")
        primary_id = session.execute(query).scalar()
        instrument_data['id'] = primary_id

        # Determine the instrument type and insert into the corresponding instrument table
        if 'INSTRUME' in primary_data:
            instrument_is = primary_data['INSTRUME'].lower()
            logger.info(f"Instrument type identified: {instrument_is}")
            try:
                logger.info(f"Attempting to load the instrument table for '{
                            instrument_is}'...")
                instrument_t = Table(
                    instrument_is, metadata, autoload_with=engine)
                logger.info(f"Successfully loaded the instrument table for '{
                            instrument_is}'.")
            except Exception as e:
                logger.error(
                    f"Keyword INSTRUME does not correspond to a valid instrument table. Error: {e}")
                return False
        else:
            logger.critical(
                "Keyword INSTRUME is missing from the primary data, which is required to determine the instrument table for insertion.")
            return False
        #
        logger.info("Inserting data into the instrument table...")
        session.execute(insert(instrument_t).values(**instrument_data))

        logger.info("Committing the transaction to the database...")
        session.commit()
        logger.info("Data inserted successfully into the database.")
    except Exception as e:
        logger.error(f"An error occurred during data insertion: {e}")
        logger.info("Rolling back the transaction...")
        session.rollback()
        if args.debug:
            print(
                'Failed to insert primary data into the database. Rolling back the transaction...')
            import pdb
            pdb.set_trace()
        logger.error(f"Error inserting data into the database: {e}")
        return False
    finally:
        if args.debug:
            print('Data insertion process completed. Closing the database session...')
            import pdb
            pdb.set_trace()
        session.close()

    return True


def main(args):
    """Collect metadata and insert into the database."""
    logger = setup_logging(args.verbose, args.logfile,
                           getattr(logging, args.loglevel))
    fits_file = args.fits_file
    header_keys = collect_header_keys(fits_file)
    if header_keys is None:
        logger.critical(
            f"Failed to collect header keys from FITS file '{fits_file}'. \
            Aborting data insertion.")
        return
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
    is_inserted = insert_data(session, primary_data,
                              instrument_data, args, logger)

    if is_inserted:
        logger.info(f"Data insertion successful for file '{fits_file}'.")
    else:
        logger.error(f"Data insertion failed for file '{fits_file}'.")


if __name__ == '__main__':
    args = parse_args()
    main(args)
