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


def insert_data(session, header_data):
    """Insert data into the database based on the header data."""


def main(args):
    """Collect metadata and insert into the database."""
    logger = setup_logging(args.verbose, args.logfile,
                           getattr(logging, args.loglevel))
    fits_file = args.fits_file
    header_keys = collect_header_keys(fits_file)


if __name__ == '__main__':
    args = parse_args()
    main(args)
