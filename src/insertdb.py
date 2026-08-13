#!/bin/python3

"""
This module inserts data into the LNA DB. The data is loaded from the FITS
files generated during observations. The data is inserted into the database
using SQLAlchemy to handle a postgreSQL database. 

The inserted data must comply with the schema and basic rules defined in the
model.py module.
"""

import os
import argparse
from json import load
import logging
import pandas as pd
from sqlalchemy import create_engine, text
from sqlalchemy.engine import URL

from log_utils import setup_logging


def parse_args():
    parser = argparse.ArgumentParser(
        description='Insert data into the LNA DB.')
    parser.add_argument('--dataframes', '-d',
                        nargs=2,
                        required=True,
                        help='Paths to the primary and instrument pandas dataframes (CSV).')
    parser.add_argument('--config', '-c',
                        type=str,
                        default='config.json',
                        help='Path to the configuration file (default: config.json)')
    parser.add_argument('--db-schema', '-s',
                        type=str,
                        dest='db_schema',
                        help='Target database schema. Overrides config default.')
    parser.add_argument('--verbose', '-v',
                        action='store_true',
                        help='Enable verbose logging.')
    parser.add_argument('--logfile', '-l',
                        type=str,
                        help='Path to the log file. If not provided, logs print to console.')
    parser.add_argument('--loglevel',
                        type=str,
                        choices=['DEBUG', 'INFO',
                                 'WARNING', 'ERROR', 'CRITICAL'],
                        default='INFO', help='Logging level. Default is INFO.')
    parser.add_argument('--debug',
                        action='store_true',
                        help='Enable debug mode logs.')
    return parser


class InsertDB:
    def __init__(self, config, args=None, logger=None):
        self.root_dir = os.path.dirname(
            os.path.dirname(os.path.abspath(__file__)))

        if isinstance(config, str):
            self.config = self._load_config(os.path.join(
                self.root_dir, 'config', config))
        else:
            self.config = config

        # Schema fallback hierarchy: args -> config -> 'public'
        self.db_schema = getattr(args, 'db_schema', None) or self.config.get(
            'db_schema', 'public')
        self.debug = getattr(args, 'debug', False)

        # Retrieve or setup logger
        if logger is not None:
            self.logger = logger
        else:
            self.logger = logging.getLogger("lnapgdb")
            if not self.logger.hasHandlers():
                setup_logging(
                    loglevel=logging.DEBUG if self.debug else logging.INFO)

        # Setup Engine securely using URL.create (matching model.py)
        creds = self._get_db_credentials()
        db_url = URL.create(
            drivername=creds.get('driver', 'postgresql'),
            username=creds.get('username') or creds.get('user'),
            password=creds['password'],
            host=creds['host'],
            port=creds['port'],
            database=creds['database']
        )
        self.engine = create_engine(db_url)

    def _load_config(self, config_path):
        with open(config_path, 'r') as f:
            return load(f)

    def _get_db_credentials(self):
        cred_path = os.path.join(
            self.root_dir, 'credentials', 'db_config.json')
        with open(cred_path, 'r') as f:
            data = load(f)

        if self.debug:
            self.logger.debug(f"Loaded DB credentials for host: {
                              data['db']['host']}")

        return data['db']

    def insert_batch(self, primary_df, instrument_df, db_schema=None):
        """
        Inserts dataframes into the database.
        Handles the Foreign Key relationship safely inside a single transaction.
        """
        if primary_df.empty:
            self.logger.warning(
                "Primary dataframe is empty. No data to insert.")
            return False, 0

        target_schema = db_schema or self.db_schema

        # Use an engine.begin() context block.
        # This guarantees atomicity: it commits on success, and rolls back on exception.
        try:
            with self.engine.begin() as conn:
                # Lock the table in exclusive mode to prevent concurrency race conditions
                # from other pipeline instances when doing MAX(id).
                conn.execute(
                    text(f"LOCK TABLE {target_schema}.primary_table IN EXCLUSIVE MODE"))

                query = text(f"SELECT MAX(id) FROM {
                             target_schema}.primary_table")
                result = conn.execute(query).fetchone()
                last_primary_id = result[0] if result[0] is not None else 0

                # Generate new primary keys
                new_primary_ids = list(
                    range(last_primary_id + 1, last_primary_id + 1 + len(primary_df)))

                primary_df['id'] = new_primary_ids
                instrument_df['id'] = new_primary_ids

                if self.debug:
                    self.logger.debug(f"Inserting IDs {new_primary_ids[0]} to {
                                      new_primary_ids[-1]}")

                # Note: We pass `con=conn` so pandas shares the active transaction context
                primary_df.to_sql('primary_table', con=conn,
                                  schema=target_schema, if_exists='append', index=False)
                self.logger.info(
                    f"Inserted {len(primary_df)} rows into primary_table.")

                instrument = primary_df['INSTRUME'].iloc[0].lower()
                instrument_df.to_sql(instrument, con=conn,
                                     schema=target_schema, if_exists='append', index=False)
                self.logger.info(f"Inserted {len(instrument_df)} rows into {
                                 instrument} table.")

            self.logger.info(f"Successfully committed {
                             len(primary_df)} records to the database.")
            return True, 0

        except Exception as e:
            self.logger.error(
                f"Error inserting batch. Transaction rolled back. Reason: {e}")
            return False, 1


if __name__ == "__main__":
    parser = parse_args()
    args = parser.parse_args()

    logger = setup_logging(loglevel=args.loglevel,
                           logfile=args.logfile, verbose=args.verbose)

    insert_db = InsertDB(
        config=args.config,
        args=args,
        logger=logger
    )

    # Load dataframes
    primary_df = pd.read_csv(args.dataframes[0])
    instrument_df = pd.read_csv(args.dataframes[1])

    # Insert data into the database
    insert_db.insert_batch(primary_df, instrument_df, args.db_schema)
