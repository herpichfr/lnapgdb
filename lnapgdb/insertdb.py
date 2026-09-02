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

from .log_utils import setup_logging, ensure_not_root


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
    def __init__(
            self,
            config,
            args=None,
            logger=None
    ):
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

    def _allocate_sequence_ids(self, conn, target_schema, count):
        """Atomically allocates a block of sequence IDs from PostgreSQL."""
        table_spec = f"{target_schema}.primary_table"

        # Try pg_get_serial_sequence first
        query = text("""
            SELECT nextval(pg_get_serial_sequence(:table_name, 'id')) 
            FROM generate_series(1, :count)
        """)
        try:
            result = conn.execute(
                query, {"table_name": table_spec, "count": count}
            )
            ids = [row[0] for row in result.fetchall()]
            if ids and ids[0] is not None:
                return ids
        except Exception:
            pass

        # Fallback: Query explicitly named sequence if pg_get_serial_sequence returns NULL
        seq_name = f"{target_schema}.primary_table_id_seq"
        fallback_query = text(
            f"SELECT nextval('{seq_name}') FROM generate_series(1, :count)"
        )
        result = conn.execute(fallback_query, {"count": count})
        return [row[0] for row in result.fetchall()]

    def insert_batch(self, primary_df, instrument_df, db_schema=None):
        if primary_df.empty:
            self.logger.warning(
                "Primary dataframe is empty. No data to insert.")
            return False, 0

        target_schema = db_schema or self.db_schema
        instrument = primary_df['INSTRUME'].iloc[0].lower()
        batch_size = len(primary_df)

        try:
            with self.engine.begin() as conn:
                # NO TABLE LOCK NEEDED!
                # Fetch N unique sequence IDs atomically from Postgres
                new_primary_ids = self._allocate_sequence_ids(
                    conn, target_schema, batch_size)

                p_df_batch = primary_df.copy()
                i_df_batch = instrument_df.copy()

                p_df_batch['id'] = new_primary_ids
                i_df_batch['id'] = new_primary_ids

                p_df_batch.to_sql(
                    'primary_table', con=conn, schema=target_schema, if_exists='append', index=False)
                i_df_batch.to_sql(
                    instrument, con=conn, schema=target_schema, if_exists='append', index=False)

            self.logger.info(f"Successfully committed {
                             batch_size} records (Batch mode).")
            return True, 0

        except Exception as e:
            self.logger.warning(
                f"Batch insertion failed. Reason: {e}. "
                "Falling back to row-by-row insertion to isolate the bad file(s)."
            )
            return self._insert_row_by_row(primary_df, instrument_df, target_schema, instrument)

    def _insert_row_by_row(
        self, primary_df, instrument_df, target_schema, instrument
    ):
        """Slow path: Inserts rows individually without table locking deadlocks."""
        successful_inserts = 0
        failed_files = []

        for i in range(len(primary_df)):
            p_row = primary_df.iloc[[i]].copy()
            i_row = instrument_df.iloc[[i]].copy()
            filename = p_row["FILENAME"].iloc[0]

            try:
                with self.engine.begin() as conn:
                    # Atomically fetch next sequence ID directly without table locking
                    seq_query = text(f"""
                        SELECT nextval(pg_get_serial_sequence('{target_schema}.primary_table', 'id'))
                    """)
                    res = conn.execute(seq_query).fetchone()

                    if res and res[0] is not None:
                        new_id = res[0]
                    else:
                        # Fallback if sequence lookup fails: fetch MAX(id) safely inside transaction
                        max_query = text(
                            f"SELECT COALESCE(MAX(id), 0) + 1 FROM"
                            f" {target_schema}.primary_table"
                        )
                        new_id = conn.execute(max_query).scalar()

                    p_row["id"] = new_id
                    i_row["id"] = new_id

                    p_row.to_sql(
                        "primary_table",
                        con=conn,
                        schema=target_schema,
                        if_exists="append",
                        index=False,
                    )
                    i_row.to_sql(
                        instrument,
                        con=conn,
                        schema=target_schema,
                        if_exists="append",
                        index=False,
                    )

                successful_inserts += 1

            except Exception as e:
                self.logger.error(
                    f"Failed to ingest file '{filename}'. Reason: {e}"
                )
                failed_files.append(filename)

        self.logger.info(
            f"Row-by-row recovery complete. Inserted: {successful_inserts},"
            f" Failed: {len(failed_files)}"
        )

        return (
            (True, 0)
            if not failed_files
            else (False, len(failed_files))
        )


def main():
    ensure_not_root()

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


if __name__ == "__main__":
    main()
