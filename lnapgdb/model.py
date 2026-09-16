#!/bin/python3

"""
This module defines the LNA DB architeture, which is a representation of the
default JSON files located in the data directory in this repository.
The JSON files are loaded on an upstream script and passed to the definitions
on this modue as arguments.
This definition is based on a postgreSQL database, and is used to create the
database, and tables in the database, as well as to define the relationships
between the tables. The relations must be such that canscading deletion is
possible, and that the tables are normalized to the third normal form.

Copyright (c) 2025, LNA DB Team. All rights reserved.

This code is licensed under the LNA License v1.0. The code is provided "as is",
without warranty of any kind, express or implied. In no event shall the authors
or copyright holders be liable for any claim, damages or other liability,
whether in an action of contract, tort or otherwise, arising from, out of or in
connection with the code or the use or other dealings in the code.
"""
# NOTE: Authentication to the database depends on psycopg2 and
# pg_hba.conf settings.

import os
import argparse
from types import SimpleNamespace
from json import load
from datetime import datetime, timezone
from sqlalchemy import (
    create_engine, func, Column, Integer, String, Float,
    ForeignKey, Date, DateTime, Boolean, Numeric, Index, text
)
from sqlalchemy.engine import URL
from sqlalchemy.ext.declarative import declarative_base

try:
    from .log_utils import ensure_not_root
    from .coords import ra_to_degrees, dec_to_degrees
except ImportError:
    # Allow running this file directly without the package having been
    # installed, by putting the repo root on sys.path and importing lnapgdb
    # as a regular top-level package instead.
    import sys
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from lnapgdb.log_utils import ensure_not_root
    from lnapgdb.coords import ra_to_degrees, dec_to_degrees


def build_models(db_schema):
    """
    Build a fresh declarative Base and the PrimaryTable/Sparc4/Echarpe/
    Robocam/Cam1 classes bound to the given schema. Each call creates its
    own Base, so calling this more than once (e.g. with different schemas)
    does not collide with a previous call's table/mapper registry.
    """
    Base = declarative_base()

    class PrimaryTable(Base):
        __tablename__ = 'primary_table'
        # Schema for DB. Use public for local testing, and cyc, dev, prod for deployment.
        __table_args__ = (
            Index('ix_primary_table_ra_deg', 'ra_deg'),
            Index('ix_primary_table_dec_deg', 'dec_deg'),
            {'schema': db_schema},
        )

        id = Column(Integer, primary_key=True, nullable=False)

        # NOTE: Add columns that needs special handling here

        # NOTE: Define FILENAME column with a unique constraint
        # This definition is also included in the datamodel for documentation
        # purposes, but added here to ensure it is always present in the table.
        filename = Column('FILENAME', String, nullable=False, unique=True,
                          info={'description': 'Original filename'})
        # Add column instrume for polymorphic identity
        instrume = Column('INSTRUME', String, nullable=False,
                          info={'description': 'Instrument used'})

        # NOTE: Out-of-model columns
        raw_path = Column(String, nullable=False,
                          info={'description': 'Path to raw file'})
        date_insert = Column(DateTime(timezone=True),
                             server_default=func.now(),
                             default=lambda: datetime.now(timezone.utc),
                             nullable=False,
                             info={'description': 'Date of insertion into the DB'})
        status_code = Column(Integer, nullable=True, default=0,
                             info={'description': 'Status code of ingestion'})
        user_comment = Column(String, nullable=True,
                              info={'description': 'User comment on the ingestion process'})
        ra_deg = Column(Float, nullable=True,
                        info={'description': 'Right ascension in decimal degrees '
                                             '(J2000.0), derived from RA'})
        dec_deg = Column(Float, nullable=True,
                         info={'description': 'Declination in decimal degrees '
                                              '(J2000.0), derived from DEC'})

        # NOTE: Model columns are added dynamically from the JSON files

        # Polymorphic identity for inheritance
        __mapper_args__ = {
            'polymorphic_identity': 'primary_table',
            'polymorphic_on': instrume
        }

    class Sparc4(PrimaryTable):
        __tablename__ = 'sparc4'
        __table_args__ = {'schema': db_schema}

        id = Column(Integer, ForeignKey(f'{db_schema}.primary_table.id',
                    ondelete='CASCADE'), primary_key=True)

        __mapper_args__ = {
            'polymorphic_identity': 'sparc4',
        }

    class Echarpe(PrimaryTable):
        __tablename__ = 'echarpe'
        __table_args__ = {'schema': db_schema}

        id = Column(Integer, ForeignKey(f'{db_schema}.primary_table.id',
                    ondelete='CASCADE'), primary_key=True)

        __mapper_args__ = {
            'polymorphic_identity': 'echarpe',
        }

    class Robocam(PrimaryTable):
        __tablename__ = 'robocam'
        __table_args__ = {'schema': db_schema}

        id = Column(Integer, ForeignKey(f'{db_schema}.primary_table.id',
                                        ondelete='CASCADE'), primary_key=True)

        __mapper_args__ = {
            'polymorphic_identity': 'robocam'
        }

    class Cam1(PrimaryTable):
        __tablename__ = 'cam1'
        __table_args__ = {'schema': db_schema}

        id = Column(Integer, ForeignKey(f'{db_schema}.primary_table.id',
                                        ondelete='CASCADE'), primary_key=True)

        __mapper_args__ = {
            'polymorphic_identity': 'cam1'
        }

    return SimpleNamespace(
        Base=Base,
        PrimaryTable=PrimaryTable,
        Sparc4=Sparc4,
        Echarpe=Echarpe,
        Robocam=Robocam,
        Cam1=Cam1,
    )


def map_type_to_sqlalchemy(type_str):
    type_mapping = {
        'integer': Integer,
        'Integer': Integer,
        'int': Integer,
        'int4': Integer,
        'string': String,
        'String': String,
        'str': String,
        'varchar': String,
        'text': String,
        'boolean': Boolean,
        'Boolean': Boolean,
        'bool': Boolean,
        'numeric': Numeric,
        'float': Float,
        'Float': Float,
        'float4': Float,
        'float8': Float,
        'date': Date,
        'timestamp': DateTime,
        'datetime': DateTime,
    }
    return type_mapping.get(type_str.lower(), String)


def get_db_credentials():
    """Get DB credentials from the the credentials config file."""
    cred_dir = os.path.join(os.path.dirname(
        os.path.dirname(os.path.abspath(__file__))), 'credentials')

    with open(os.path.join(f'{cred_dir}/db_config.json'), 'r') as f:
        data = load(f)
    return data['db']


def add_columns_from_json(table_class):
    if not hasattr(table_class, '__tablename__'):
        raise ValueError("Provided class must have a __tablename__ attribute.")

    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    json_path = os.path.join(
        base_dir,
        'models',
        f'{table_class.__tablename__.lower()}.json'
    )
    # Fail gracefully if a JSON model doesn't exist for a table yet
    if not os.path.exists(json_path):
        print(f"Warning: No JSON model found for {table_class.__tablename__} at {json_path}")
        return

    with open(json_path) as f:
        table_cols = load(f)

    for col in table_cols:
        colname = col['colname']
        # NOTE: Colname INSTRUME is reserved for the polymorphic identity, but
        # it needs to be defined in the JSON files either way. However, if it
        # is defined in the JSON file, it will be ignored and not added as a
        # column to the table. Same happens with FILENAME, which is defined
        # with a unique constraint in the PrimaryTable, but is also included in
        # the JSON files for documentation purposes.
        if colname.upper() in ['INSTRUME', 'FILENAME']:
            continue

        # Map SQLAlchemy type
        type_class = map_type_to_sqlalchemy(col['datatype'])
        new_column = Column(
            type_class,
            nullable=col.get('nullable', True),
            default=col.get('default_value', None),
            unique=col.get('unique', False),
            info={
                'allowed_values': col.get('allowed_values', None),
                'description': col.get('description', '')
            }
        )

        setattr(table_class, colname, new_column)
        table_class.__table__.append_column(new_column)


def sync_schema(engine, db_schema):
    """
    Idempotently add the ra_deg/dec_deg columns and their indexes to an
    existing primary_table, without touching anything else. Safe to re-run
    against an already-synced, populated dev/cyc/prod schema.
    """
    alter_statements = [
        f'ALTER TABLE {db_schema}.primary_table ADD COLUMN IF NOT EXISTS ra_deg  double precision;',
        f'ALTER TABLE {db_schema}.primary_table ADD COLUMN IF NOT EXISTS dec_deg double precision;',
    ]
    index_statements = [
        f'CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_primary_table_ra_deg  ON {db_schema}.primary_table (ra_deg);',
        f'CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_primary_table_dec_deg ON {db_schema}.primary_table (dec_deg);',
    ]

    with engine.begin() as conn:
        for statement in alter_statements:
            print(f"Executing: {statement}")
            conn.execute(text(statement))

    # NOTE: CREATE INDEX CONCURRENTLY cannot run inside a transaction block,
    # so it needs a connection with autocommit rather than the default
    # transactional one used above for the ALTER TABLE statements.
    autocommit_engine = engine.execution_options(isolation_level="AUTOCOMMIT")
    with autocommit_engine.connect() as conn:
        for statement in index_statements:
            print(f"Executing: {statement}")
            conn.execute(text(statement))

    print("Schema sync complete: ra_deg/dec_deg columns and indexes are present.")


def backfill_coords(engine, db_schema, batch_size=5000):
    """
    Recompute ra_deg/dec_deg for rows that predate the ra_deg/dec_deg
    columns, in batches, committing per batch. Each coordinate is converted
    independently, matching the ingestion path: a row with an unparseable
    RA but a valid DEC still gets its dec_deg filled in. A value that is
    already present is never overwritten, and anything that cannot be
    parsed is left NULL and reported as skipped. Safe to re-run: a second
    pass reports 0 rows converted.
    """
    # NOTE: "RA"/"DEC" are created case-sensitively by add_columns_from_json
    # and must be double-quoted; ra_deg/dec_deg are lowercase and must not be.
    select_sql = text(
        f'SELECT id, "RA", "DEC", ra_deg, dec_deg '
        f'FROM {db_schema}.primary_table '
        f'WHERE ((ra_deg IS NULL AND "RA" IS NOT NULL) '
        f'    OR (dec_deg IS NULL AND "DEC" IS NOT NULL)) '
        f'  AND id > :last_id '
        f'ORDER BY id LIMIT :batch_size'
    )
    # NOTE: COALESCE keeps an already-populated column untouched, so passing
    # None for one coordinate only ever leaves that column as it was.
    update_sql = text(
        f'UPDATE {db_schema}.primary_table '
        f'SET ra_deg = COALESCE(ra_deg, :ra_deg), '
        f'    dec_deg = COALESCE(dec_deg, :dec_deg) WHERE id = :id'
    )

    converted = 0
    skipped = 0
    last_id = 0

    while True:
        with engine.begin() as conn:
            rows = conn.execute(
                select_sql, {'last_id': last_id, 'batch_size': batch_size}
            ).fetchall()
            if not rows:
                break

            updates = []
            for row in rows:
                ra_deg = ra_to_degrees(row.RA) if row.ra_deg is None else None
                dec_deg = (dec_to_degrees(row.DEC)
                           if row.dec_deg is None else None)

                if row.ra_deg is None and row.RA is not None and ra_deg is None:
                    print(f"Warning: row id={row.id} RA={row.RA!r} could not "
                          f"be converted to decimal degrees; leaving NULL.")
                if (row.dec_deg is None and row.DEC is not None
                        and dec_deg is None):
                    print(f"Warning: row id={row.id} DEC={row.DEC!r} could not "
                          f"be converted to decimal degrees; leaving NULL.")

                if ra_deg is None and dec_deg is None:
                    skipped += 1
                else:
                    updates.append({'id': row.id, 'ra_deg': ra_deg,
                                    'dec_deg': dec_deg})
                    converted += 1

            if updates:
                conn.execute(update_sql, updates)

            last_id = rows[-1].id
            print(f"Backfilled batch of {len(rows)} rows "
                  f"({len(updates)} converted, up to id={last_id}).")

    print(f"Backfill complete: {converted} rows converted, "
          f"{skipped} rows skipped (left NULL).")


def main():
    ensure_not_root()

    parser = argparse.ArgumentParser(
        description='Create LNA DB tables and add columns from JSON files.')
    parser.add_argument('--db_schema', '-s', default=None,
                        help='Database schema to use (default: DB_SCHEMA env '
                             'var, or public if that is not set either).')
    parser.add_argument('--reset-db', action='store_true',
                        help='Drop all tables before creating (DANGEROUS)')
    parser.add_argument('--sync-schema', action='store_true',
                        help='Idempotently add the ra_deg/dec_deg columns and '
                             'indexes to an existing primary_table')
    parser.add_argument('--backfill-coords', action='store_true',
                        help='Recompute ra_deg/dec_deg for existing rows that '
                             'predate the ra_deg/dec_deg columns')
    args = parser.parse_args()

    db_schema = args.db_schema or os.getenv('DB_SCHEMA', 'public')
    print(f"Using database schema: {db_schema}")

    models = build_models(db_schema)

    creds = get_db_credentials()

    # Use SQLAlchemy's secure URL builder instead of f-strings
    db_url = URL.create(
        drivername=creds.get('driver', 'postgresql'),
        username=creds.get('user') or creds.get('username'),
        password=creds['password'],
        host=creds['host'],
        port=creds['port'],
        database=creds['database']
    )

    engine = create_engine(db_url)

    if args.reset_db:
        user_input = input(
            f"WARNING: You are about to drop all tables from schema {db_schema}. "
            "This action is irreversible. Are you sure you want to continue?[y/N]: ")
        if user_input.lower() != 'y':
            print("Aborting operation.")
            return

        print("Dropping all tables")  # Drop existing tables
        models.Base.metadata.drop_all(engine)

    # Add columns from JSON files to each table class
    for table_class in [models.PrimaryTable, models.Sparc4, models.Echarpe,
                        models.Robocam, models.Cam1]:
        add_columns_from_json(table_class)
        print(f"Added columns from JSON for table: {table_class.__tablename__}")

    models.Base.metadata.create_all(engine)  # Create tables with new columns
    print("Database schema successfully generated and applied.")

    if args.sync_schema:
        sync_schema(engine, db_schema)

    if args.backfill_coords:
        backfill_coords(engine, db_schema)


if __name__ == '__main__':
    main()
