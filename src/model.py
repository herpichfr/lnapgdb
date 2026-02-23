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
from sqlalchemy import create_engine, func, Column, Integer, String, Float, ForeignKey, Date, DateTime, Boolean, Numeric
from sqlalchemy.ext.declarative import declarative_base
from json import load
from datetime import datetime, timezone
import argparse

parser = argparse.ArgumentParser(
    description='Create LNA DB tables and add columns from JSON files.')
parser.add_argument('--db_schema',
                    default='public',
                    choices=['public', 'cyc', 'dev', 'prod'],
                    help='Database schema to use (default: public)'
                    )
args = parser.parse_args()

db_schema = args.db_schema

Base = declarative_base()


class PrimaryTable(Base):
    __tablename__ = 'primary_table'
    # Schema for DB. Use public for local testing, and cyc, dev, prod for deployment.
    __table_args__ = {'schema': db_schema}

    id = Column(Integer, primary_key=True, nullable=False)
    instrume = Column('INSTRUME', String, nullable=False,
                      info={'description': 'Instrument used'})
    raw_path = Column(String, nullable=False,
                      info={'description': 'Path to raw file'})
    date_insert = Column(DateTime(timezone=True),
                         server_default=func.now(),
                         default=lambda: datetime.now(timezone.utc),
                         nullable=False,
                         info={'description': 'Date of insertion into the DB'})

    # NOTE: Model columns are added dynamically from the JSON files

    # Polymorphic identity for inheritance
    __mapper_args__ = {
        'polymorphic_identity': 'primary_table',
        'polymorphic_on': instrume
    }


class Sparc4(Base):
    __tablename__ = 'sparc4'
    __table_args__ = {'schema': 'public'}  # Optional schema

    id = Column(Integer, ForeignKey('public.primary_table.id',
                ondelete='CASCADE'), primary_key=True)

    __mapper_args__ = {
        'polymorphic_identity': 'sparc4',
    }


class Echarpe(Base):
    __tablename__ = 'echarpe'
    __table_args__ = {'schema': 'public'}  # Optional schema

    id = Column(Integer, ForeignKey('public.primary_table.id',
                ondelete='CASCADE'), primary_key=True)

    __mapper_args__ = {
        'polymorphic_identity': 'echarpe',
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

    with open(os.path.expanduser(f'{cred_dir}/config.json'), 'r') as f:
        data = load(f)
    return data['lnapgdatabase']


def add_columns_from_json(table_class):
    if not hasattr(table_class, '__tablename__'):
        raise ValueError("Provided class must have a __tablename__ attribute.")
    json_path = f'data/{table_class.__tablename__.lower()}.json'
    with open(json_path) as f:
        table_cols = load(f)
    for col in table_cols:
        colname = col['colname']
        # NOTE: Colname INSTRUME is reserved for the polymorphic identity, but
        # it needs to be defined in the JSON files either way. However, if it
        # is defined in the JSON file, it will be ignored and not added as a
        # column to the table.
        if colname.upper() == 'INSTRUME':
            continue
        default_value = col.get('default', None)
        # Map SQLAlchemy type
        type_class = map_type_to_sqlalchemy(col['datatype'])
        is_nullable = col.get('nullable', True)
        description = col.get('description', '')
        if 'allowed_values' in col.keys():
            allowed_values = col['allowed_values'].split(',')
            # Add a check constraint for allowed values
            new_column = Column(type_class,
                                nullable=is_nullable,
                                default=default_value,
                                info={'allowed_values': allowed_values,
                                      'description': description})
        else:
            new_column = Column(type_class,
                                nullable=is_nullable,
                                default=default_value,
                                info={'description': description})
        setattr(table_class, colname, new_column)
        table_class.__table__.append_column(new_column)


def main():
    creds = get_db_credentials()
    engine = create_engine(
        f"postgresql://{creds['username']}:{creds['password']
                                            }@{creds['host']}:{creds['port']}/{creds['database']}"
    )
    Base.metadata.drop_all(engine)  # Drop existing tables
    print("Database and tables created successfully!")
    add_columns_from_json(PrimaryTable)
    print("Columns added to PrimaryTable successfully!")
    add_columns_from_json(Sparc4)
    print("Columns added to Sparc4 successfully!")
    Base.metadata.create_all(engine)  # Create tables with new columns


if __name__ == '__main__':
    # NOTE: File execution is SUCCESSFULL.
    # Creating new columns from JSON
    main()
