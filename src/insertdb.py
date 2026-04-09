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
from sqlalchemy import create_engine, MetaData, text
from sqlalchemy.orm import sessionmaker
from miscellaneous import setup_logging
from json import load
import argparse


def parse_args():
    parser = argparse.ArgumentParser(
        description='Insert data into the LNA DB.')
    parser.add_argument('--dataframes', '-d',
                        nargs=2,
                        required=True,
                        help='Paths to the primary and instrument pandas dataframes.')
    parser.add_argument('--config', '-c',
                        type=str,
                        default='config.json',
                        help='Path to the configuration file (default: config.json)')
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
    return parser


class InsertDB:
    def __init__(self, config, args=None, logger=None):
        self.root_dir = os.path.dirname(
            os.path.dirname(os.path.abspath(__file__)))
        if type(config) is str:
            self.config = self._load_config(os.path.join(
                self.root_dir, 'config', config))
        else:
            self.config = config

        self.db_schema = self.config.get('db_schema', 'public')

        if logger is not None:
            self.logger = logger
        elif args is not None:
            self.logger = logger if logger is not None else setup_logging(
                args.loglevel, args.logfile, args.verbose)
        else:
            self.logger = setup_logging('INFO', None, False)

        self.debug = args.debug if args is not None else False
        # Setup Engine
        creds = self._get_db_credentials()
        self.engine = create_engine(
            f"postgresql://{creds['username']}:{creds['password']}@"
            f"{creds['host']}:{creds['port']}/{creds['database']}"
        )
        self.Session = sessionmaker(bind=self.engine)
        self.metadata = MetaData()

    def _load_config(self, config_path):
        with open(config_path, 'r') as f:
            return load(f)

    def _get_db_credentials(self):
        # Access your credentials config as before
        cred_path = os.path.join(os.path.dirname(
            os.path.dirname(os.path.abspath(__file__))), 'credentials/config.json')
        with open(cred_path, 'r') as f:
            return load(f)['lnapgdatabase']
        
    

    def insert_batch(self, primary_df, instrument_df, db_schema=None, debug=None):
        """
        Inserts dataframes into the database. 
        Handles the Foreign Key relationship automatically.
        """
        if primary_df.empty:
            self.logger.warning(
                "Primary dataframe is empty. No data to insert.")
            return False, 0

        self.debug = debug if debug is not None else self.debug

        db_schema = self.db_schema if db_schema is None else db_schema

        session = self.Session()

        # Retrive latest primary key id from primary table
        query = text(f"SELECT MAX(id) FROM {db_schema}.primary_table")
        result = session.execute(query).fetchone()
        last_primary_id = result[0] if result[0] is not None else 0
        # Create an array of ints to be used as primary keys for the new rows in the primary table
        new_primary_ids = list(
            range(last_primary_id + 1, last_primary_id + 1 + len(primary_df)))
        primary_df['id'] = new_primary_ids
        instrument_df['id'] = new_primary_ids

        if self.debug:
            primary_df.to_sql('primary_table', self.engine,
                              schema=db_schema, if_exists='append', index=False)
            import pdb
            pdb.set_trace()

        else:

            try:
                primary_df.to_sql('primary_table', self.engine,
                                  schema=db_schema, if_exists='append', index=False)
                self.logger.info(
                    f"Inserted {len(primary_df)} rows into primary_table.")
            except Exception as e:
                self.logger.error(f"Error inserting into primary_table: {e}")
                session.rollback()
                return False, 1

        instrument = primary_df['INSTRUME'].iloc[0].lower()
        if self.debug:
            instrument_df.to_sql(instrument, self.engine,
                                 schema=db_schema, if_exists='append', index=False)
            import pdb
            pdb.set_trace()
        else:
            try:
                instrument_df.to_sql(instrument, self.engine,
                                     schema=db_schema, if_exists='append', index=False)
                self.logger.info(
                    f"Inserted {len(primary_df)} rows into primary_table for instrument {instrument}."
                )
            except Exception as e:
                self.logger.error(f"Error inserting into {instrument} table: {e}")
                session.rollback()
                return False, 2

        self.logger.info(
            f"Successfully inserted {len(primary_df)} rows into the database.")
        session.commit()
        session.close()

        return True, 0
    


if __name__ == "__main__":
    parser = parse_args()
    args = parser.parse_args()

    logger = setup_logging(args.loglevel, args.logfile, args.verbose)
    insert_db = InsertDB(
        config=args.config,
        args=args,
        logger=logger
    )

    # Load dataframes
    import pandas as pd
    primary_df = pd.read_csv(args.dataframes[0])
    instrument_df = pd.read_csv(args.dataframes[1])

    # Insert data into the database
    insert_db.insert_batch(primary_df, instrument_df, args.db_schema)
