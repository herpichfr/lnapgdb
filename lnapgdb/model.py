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
from json import load
from datetime import datetime, timezone
from sqlalchemy import (
    create_engine, func, Column, Integer, String, Float,
    ForeignKey, Date, DateTime, Boolean, Numeric
)
from sqlalchemy.engine import URL
from sqlalchemy.ext.declarative import declarative_base

from .log_utils import ensure_not_root


# Define db_schema to be used globally in the module
db_schema = os.getenv('DB_SCHEMA', 'public')  # Default to 'public' if not set

Base = declarative_base()


class PrimaryTable(Base):
    __tablename__ = 'primary_table'
    # Schema for DB. Use public for local testing, and cyc, dev, prod for deployment.
    __table_args__ = {'schema': db_schema}

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
        print(f"Warning: No JSON model found for {
              table_class.__tablename__} at {json_path}")
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


def main():
    ensure_not_root()

    parser = argparse.ArgumentParser(
        description='Create LNA DB tables and add columns from JSON files.')
    parser.add_argument('--reset-db', action='store_true',
                        help='Drop all tables before creating (DANGEROUS)')
    args = parser.parse_args()

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
            f"WARNING: You are about to drop all tables from schema {
                db_schema}. "
            "This action is irreversible. Are you sure you want to continue?[y/N]: ")
        if user_input.lower() != 'y':
            print("Aborting operation.")
            return

        print("Dropping all tables")  # Drop existing tables
        Base.metadata.drop_all(engine)

    # Add columns from JSON files to each table class
    for table_class in [PrimaryTable, Sparc4, Echarpe, Robocam, Cam1]:
        add_columns_from_json(table_class)
        print(f"Added columns from JSON for table: {
              table_class.__tablename__}")

    Base.metadata.create_all(engine)  # Create tables with new columns
    print("Database schema successfully generated and applied.")


if __name__ == '__main__':
    main()
