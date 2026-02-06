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
# NOTE: Authentication to the database depends on psycopg2 and pg_hba.conf settings.
import os
from sqlalchemy import create_engine, Column, Integer, String, Float, ForeignKey, Date, DateTime, Boolean, Numeric
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship, sessionmaker
from json import load

Base = declarative_base()


class PrimaryTable(Base):
    __tablename__ = 'primary_table'
    __table_args__ = {'schema': 'public'}  # Optional schema

    id = Column(Integer, primary_key=True)
    # Add other columns dynamically


class CommonKeywords(Base):
    __tablename__ = 'common_keywords'
    __table_args__ = {'schema': 'public'}  # Optional schema

    id = Column(Integer, primary_key=True)
    # Add other columns dynamically


def map_type_to_sqlalchemy(type_str):
    type_mapping = {
        'integer': Integer,
        'int': Integer,
        'int4': Integer,
        'string': String,
        'str': String,
        'varchar': String,
        'text': String,
        'boolean': Boolean,
        'bool': Boolean,
        'numeric': Numeric,
        'float': Float,
        'float4': Float,
        'float8': Float,
        'date': Date,
        'timestamp': DateTime,
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
    json_path = f'data/{table_class.__name__.lower()}.json'
    with open(json_path) as f:
        config = load(f)
    for col in config['columns']:
        # Map SQLAlchemy type
        type_class = map_type_to_sqlalchemy(col['type'])
        # Create column dynamically
        setattr(table_class, col['name'], Column(type_class, nullable=True))


def main():
    creds = get_db_credentials()
    engine = create_engine(
        f"postgresql://{creds['username']}:{creds['password']
                                            }@{creds['host']}/{creds['database']}"
    )
    Base.metadata.drop_all(engine)  # Drop existing tables
    Base.metadata.create_all(engine)
    print("Database and tables created successfully!")


if __name__ == '__main__':
    main()

# Uncomment to use dynamically loaded columns:
# add_columns_from_json(PrimaryTable)
# add_columns_from_json(CommonKeywords)
