#!/bin/python3
# Author: Herpich F. R. fabiorafaelh@gmail.com
# 2024-02-11
# Create a database to store my coin collection data

import os
import argparse
import json
import numpy as np
import pandas as pd
from astropy.time import Time
import datetime
from sqlalchemy import create_engine
from sqlalchemy import Column, Integer, Sequence, String, Float, ForeignKey, TIMESTAMP, Boolean, MetaData
from sqlalchemy.orm import sessionmaker, declarative_base


Base = declarative_base()


class CatalogueRef(Base):
    __tablename__ = 'catalogue_ref'
    id = Column(Integer, Sequence('catalogue_ref_id_seq'), primary_key=True)
    krause = Column(String(10), nullable=True, default='KM# 0')
    numista = Column(String(10), nullable=True, default='N# 0')


class Country(Base):
    __tablename__ = 'countries'
    id = Column(Integer, Sequence('countries_id_seq'), primary_key=True)
    country = Column(String(50), unique=False, nullable=True)
    # code = Column(Integer, unique=True, nullable=False)


class Collectibles(Base):
    __tablename__ = 'collectibles'
    id = Column(Integer, Sequence('coin_id_seq'), primary_key=True)
    name = Column(String(50), nullable=False)
    catalogue_id = Column(Integer, ForeignKey(
        'catalogue_ref.id'), nullable=False)
    country_id = Column(Integer, ForeignKey('countries.id'), nullable=False)
    collectible_type = Column(String(50), nullable=True, default='coin', info={
                              'valid': ['coin',
                                        'banknote',
                                        'stamp',
                                        'medal',
                                        'token',
                                        'book',
                                        'other']})
    year = Column(Integer)
    value = Column(Integer, comment='Face value', default=0)
    currency = Column(String(50), nullable=True, default='ND')
    mint = Column(String(50), nullable=True, default='ND')
    material = Column(String(50), nullable=True, default='ND')
    diameter = Column(Float, nullable=True, default=0)
    thickness = Column(Float, nullable=True, default=0)
    weight = Column(Float, nullable=True, default=0)
    quantity = Column(String(15), nullable=True, default='ND')
    grade = Column(String(50), nullable=True, default='ND')
    date_acquired = Column(TIMESTAMP, nullable=True,
                           default=Time.now().datetime)
    cost = Column(String(10), nullable=True, default='ND')
    catvalue = Column(String(10), nullable=True, default='ND')
    provenance = Column(String(50), nullable=True, default='ND')
    certified = Column(Integer, nullable=True, default=0, info={
                       'valid': [0, 1]})
    certified_by = Column(String(50), nullable=True, default='ND')
    notes = Column(String(200), nullable=True, default='ND')


def update_db(df, engine, args):

    print('creating session')
    Session = sessionmaker(bind=engine)
    print('starting session')
    session = Session()
    metadata = MetaData()
    metadata.reflect(engine)

    catalogue_ref = metadata.tables['catalogue_ref']
    catalogue_ref_columns = [
        col for col in catalogue_ref.columns.keys()]
    # get column types:
    try:
        session.bulk_insert_mappings(catalogue_ref,
                                     df[catalogue_ref_columns].to_dict(orient='records'))
    except KeyError:
        for col in catalogue_ref_columns:
            if col not in df.columns and col != 'id':
                df[col] = ['ND'] * len(df)
        df['id'] = df.index + len(session.query(CatalogueRef).all()) + 1

        if df['krause'].isna().any():
            fill_krause = ['ND' + str(i)
                           for i in df['id'][df['krause'].isna()]]
            df['krause'][df['krause'].isna()] = fill_krause
        df[catalogue_ref_columns].to_sql('catalogue_ref', engine,
                                         if_exists='append', index=False)
    session.commit()

    for index, row in df.iterrows():
        print(index, ':', row['name'])

        query_country = session.query(Country.country).filter_by(
            country=row['country']).first()
        if query_country is not None:
            print('country %s already in db...' % row['country'])
        else:
            country = Country(country=row['country'])
            session.add(country)
            print('commiting country', row['country'])
            session.commit()

    collectibles = metadata.tables['collectibles']
    collectibles_columns = [col for col in collectibles.columns.keys()]
    collect_col_types = {
        col: collectibles.columns[col].type for col in collectibles_columns}
    for col in collectibles_columns:
        if col not in ['id', 'catalogue_id', 'country_id']:
            col_type = collect_col_types[col].python_type
            if col not in df.columns:
                if col_type == str:
                    df[col] = ['ND'] * len(df)
                elif (col_type == int) or (col_type == float):
                    df[col] = [0] * len(df)
                elif col_type == datetime.datetime:
                    df[col] = [Time.now().datetime] * len(df)
                elif col_type == bool:
                    df[col] = [0] * len(df)
                else:
                    df[col] = [None] * len(df)
            if (np.nan in df[col]) or (None in df[col]) or (df[col].isna().any()):
                if col_type == str:
                    df[col] = df[col].replace({np.nan: 'ND', None: 'ND'})
                elif (col_type == int) or (col_type == float):
                    df[col] = df[col].replace({np.nan: 0, None: 0})
                elif col_type == datetime.datetime:
                    df[col] = df[col].replace({np.nan: Time.now().datetime,
                                               None: Time.now().datetime})
                elif col_type == bool:
                    df[col] = df[col].replace({np.nan: 0, None: 0})
                else:
                    df[col] = df[col].replace({np.nan: 'ND', None: 'ND'})

    import pdb
    pdb.set_trace()
    df['catalogue_id'] = [session.query(CatalogueRef.id).filter_by(
        krause=krause).first() for krause in df['krause']]
    df['catalogue_id'] = df['catalogue_id'].apply(lambda x: str(x[0]))
    country_id = [session.query(Country.id).filter_by(
        country=country).first() for country in df['country']]
    df['country_id'] = country_id
    df['country_id'] = df['country_id'].apply(lambda x: x[0])
    df[collectibles_columns].to_sql('collectibles', engine,
                                    if_exists='append', index=False)
    session.commit()
    print('all data commited')
    session.close()


def reset_db(engine):
    """Drop all tables and create new ones"""
    print('creating tables')
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)


def load_data(data):
    """Load data from csv file"""
    df = pd.read_csv(data)
    print('data loaded')
    return df


def get_credentials():
    """Get database credentials from config file"""
    cred_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

    with open(os.path.expanduser(f'{cred_dir}/config/config.json'), 'r') as f:
        data = json.load(f)
    return data['collectionsdb']


def main(args):
    data = get_credentials()
    username = data['username']
    password = data['password']
    host = data['host']
    port = data['port']
    database = data['database']
    dburl = f"postgresql://{username}:{password}@{host}:{port}/{database}"
    engine = create_engine(dburl, echo=False)

    if args.reset:
        reset_db(engine)

    if args.update:
        df = load_data(args.data)
        update_db(df, engine, args)


def parse_args():
    parser = argparse.ArgumentParser(
        description='Create a database to store my coin collection data')
    parser.add_argument('-r', '--reset', action='store_true',
                        help='reset the database')
    parser.add_argument('-u', '--update', action='store_true',
                        help='update the database')
    parser.add_argument('-d', '--data', default='data.csv',
                        help='csv file with the data to be loaded')
    args = parser.parse_args()
    return args


if __name__ == "__main__":

    args = parse_args()
    main(args)
