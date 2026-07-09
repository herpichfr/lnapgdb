#!/bin/python2

"""
Adapt headers and directories names for Cam1 data so it is compliant with
the LNADB data model. This script will need to be run as a service until
we implement the robotization of the data acquisition.

@author: Herpich, F. R. email: fherpich@lna.br
"""

import os
from astropy.io import fits
import json
import glob
import argparse


def parse_args():
    parser = argparse.ArgumentParser(
        description="Adapt headers and directories names for Cam1 data so it is compliant with the LNADB data model."
    )
    parser.add_argument(
        "-d",
        "--directory",
        type=str,
        required=True,
        help="Directory containing the Cam1 data.",
    )
    return parser.parse_args()


def get_config():
    """
    Get the configuration of the DB structure.
    """
    config_file = os.path.join(os.path.dirname(
        __file__), "config/config.json")
    with open(config_file, "r") as f:
        config = json.load(f)
    return config


def get_data_model(instrume):
    """
    Get the data model for the given camera.

    Parameters
    ----------
    instrume : str
            Camera name.

    Returns
    -------
    dict
        Data model for the given camera.
    """
    instrume_model = os.path.join(
        os.path.dirname(__file__), f"models/{instrume}.json")
    inst_model = json.load(open(instrume_model, "r"))
    return inst_model


def adapt_headers_and_directories(directory, raw_dir):
    """
    Adapt headers and directories names for instruments used in IAG telescope.

    Parameters
    ----------
    directory : str
        Directory containing the raw data.
    raw_dir : str
        Directory where the formated raw data is stored.
    """
    synonym_keys = {
        "TELESCOP": "TELESCOP",
    }
    # collect all fits files in the directory and its subdirectories
    fits_files = []
    failed_files = []
    for root, dirs, files in os.walk(directory):
        for file in files:
            if file.endswith(".fits"):
                fits_files.append(os.path.join(root, file))

    primary_model_path = os.path.join(
        os.path.dirname(__file__), "models/primary_table.json")
    primary_model = json.load(open(primary_model_path, "r"))

    for fits_file in fits_files:
        with fits.open(fits_file, mode="update") as hdul:
            header = hdul[0].header
            instrument = header.get("INSTRUME", None)
            if instrument is None:
                print(f"INSTRUME keyword not found in {fits_file}. Skipping.")
                failed_files.append(fits_file)
                continue
            for key in header.keys():
                if key in synonym_keys.keys():
                    header[synonym_keys[key]] = header[key]
            for key in primary_model.keys():
                keyname = key["colname"]
                is_nullable = key.get("nullable", True)
                has_default = key.get("default", None)
                data_type = key.get("datatype", "str")
                description = key.get("description", "")
                if keyname not in header and has_default is not None:
                    header[keyname] = (has_default, description)
                elif keyname not in header and not is_nullable:
                    print(
                        f"Required keyword {keyname} not found in {fits_file}. Skipping.")
                    failed_files.append(fits_file)
                    continue


if __name__ == "__main__":
    args = parse_args()
    month_conversion = {
        "jan": "01",
        "feb": "02",
        "mar": "03",
        "apr": "04",
        "mai": "05",
        "jun": "06",
        "jul": "07",
        "aug": "08",
        "sep": "09",
        "out": "10",
        "nov": "11",
        "dec": "12",
    }
    _year = args.directory[:2]
    _month = month_conversion[args.directory[2:5].lower()]
    _day = args.directory[5:7]
    _date_dir = f"20{_year}{_month}{_day}"
    raw_dir = "/ssdsto1/data/bc060/"
    if not os.path.exists(os.path.join(raw_dir, _date_dir)):
        os.makedirs(os.path.join(raw_dir, _date_dir))

    adapt_headers_and_directories(args.directory, raw_dir)
