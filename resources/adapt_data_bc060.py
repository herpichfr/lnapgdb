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
import pandas as pd
import argparse


def parse_args():
    parser = argparse.ArgumentParser(
        description="Adapt headers and directories names for BC060 data \
        so it is compliant with the LNADB data model."
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
        os.path.dirname(os.path.dirname(__file__)), f"models/{instrume}.json")
    inst_model = json.load(open(instrume_model, "r"))
    inst_model_keys = {}
    for item in inst_model:
        keyname = item["colname"]
        is_nullable = item.get("nullable", True)
        has_default = item.get("default", None)
        data_type = item.get("datatype", "str")
        description = item.get("description", "")
        inst_model_keys[keyname] = {
            "nullable": is_nullable,
            "default_value": has_default,
            "datatype": data_type,
            "description": description,
        }
    return inst_model_keys


def get_primary_model():
    """
    Get the primary model for the given camera.

    Returns
    -------
    dict
        Primary model for the given camera.
    """
    # Get directory one level above filepath location
    base_dir = os.path.dirname(os.path.dirname(__file__))
    primary_model_path = os.path.join(
        base_dir, "models/primary_table.json")
    primary_model = json.load(open(primary_model_path, "r"))
    primary_model_keys = {}
    for item in primary_model:
        keyname = item["colname"]
        is_nullable = item.get("nullable", True)
        has_default = item.get("default_value", None)
        data_type = item.get("datatype", "str")
        description = item.get("description", "")
        primary_model_keys[keyname] = {
            "nullable": is_nullable,
            "default": has_default,
            "datatype": data_type,
            "description": description,
        }
    return primary_model_keys


def adapt_headers_and_directories(fits_file, raw_dir, new_fits_path):
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
        "ACSVRSN": "DLLVER",
        "TEXPTIME": "EXPOSURE",
        "CCDTEMP": "TEMP",  # NOTE: Comma used as decimal
        "EMGAIN": "EMREALGN",
        "CCDSERN": "SERNO",
        "NFRAMES": "FRMCNT",
        "DATE-OBS": "FRAME",  # NOTE: Need to format o isot
        "EQUINOX": "EPOCH",
        "MJD-OBS": "JD",  # NOTE: Need to converto from JD to MJD
        "LST": "ST",
        "TCSHA": "HA",
        "FILENAME": "IMAGE",
        "TELFOCUS": "FOCUSVAL",
        "PRESSURE": "W-BAR",  # NOTE: Comma used as decimal
        "EXTTEMP": "W-TEMP",  # NOTE: Comma used as decimal
        "HUMIDITY": "W-HUM",  # NOTE: Comma used as decimal
    }

    primary_model = get_primary_model()
    failed_fits = False

    with fits.open(fits_file) as hdul:
        header = hdul[0].header.copy()
        data = hdul[0].data.copy()
        instrument = header.get("INSTRUME", None)
        if instrument is None:
            print(f"INSTRUME keyword not found in {fits_file}. Skipping.")
            failed_fits = True
        else:
            # Add current INSTRUME as HIERARCH keyword to preserve original value
            header["INST INSTRUME"] = (instrument,
                                       header.comments["INSTRUME"])
            instrument_name = instrument.split('+')[0]
            header["INSTRUME"] = (instrument_name,
                                  primary_model["INSTRUME"]["description"])
            detector_name = instrument.split('+')[1]
            instrument_model = get_data_model(instrument_name.lower())
            header["DETECTOR"] = (detector_name,
                                  instrument_model["DETECTOR"]["description"])
        if not failed_fits:
            for keyname in primary_model.keys():
                if keyname not in header:
                    if keyname in synonym_keys:
                        synonym_key = synonym_keys[keyname]
                        if synonym_key in header:
                            header[keyname] = (header[synonym_key],
                                               primary_model[keyname]["description"])
                        else:
                            if primary_model[keyname]["nullable"]:
                                header[keyname] = (primary_model[keyname]["default"],
                                                   primary_model[keyname]["description"])
                            else:
                                print(f"Required keyword {keyname} not found in {
                                    fits_file}. Skipping.")
                                failed_fits = True
                    else:
                        if primary_model[keyname]["nullable"]:
                            header[keyname] = (primary_model[keyname]["default"],
                                               primary_model[keyname]["description"])
                        elif primary_model[keyname]["default"] is not None:
                            header[keyname] = (primary_model[keyname]["default"],
                                               primary_model[keyname]["description"])
                        else:
                            print(f"Required keyword {keyname} not found in {
                                fits_file}. Skipping.")
                            failed_fits = True

                # NOTE: Lots of keywords are floats. However, in the header,
                # their value uses comma as decimal separator. We need to
                # convert them to float.
                if primary_model[keyname]["datatype"] == "float":
                    try:
                        header[keyname] = (float(str(header[keyname]).replace(',', '.')),
                                           primary_model[keyname]["description"])
                    except ValueError:
                        print(f"Could not convert {keyname} to float in {
                              fits_file}. Skipping.")
                        failed_fits = True
            for keyname in instrument_model.keys():
                if keyname not in header:
                    if keyname in synonym_keys:
                        synonym_key = synonym_keys[keyname]
                        if synonym_key in header:
                            header[keyname] = (header[synonym_key],
                                               instrument_model[keyname]["description"])
                        else:
                            if instrument_model[keyname]["nullable"]:
                                header[keyname] = (instrument_model[keyname]["default"],
                                                   instrument_model[keyname]["description"])
                            else:
                                print(f"Required keyword {keyname} not found in {
                                    fits_file}. Skipping.")
                                failed_fits = True
                    else:
                        if instrument_model[keyname]["nullable"]:
                            header[keyname] = (instrument_model[keyname]["default"],
                                               instrument_model[keyname]["description"])
                        elif instrument_model[keyname]["default"] is not None:
                            header[keyname] = (instrument_model[keyname]["default"],
                                               instrument_model[keyname]["description"])
                        else:
                            print(f"Required keyword {keyname} not found in {
                                fits_file}. Skipping.")
                            failed_fits = True
                if instrument_model[keyname]["datatype"] == "float":
                    try:
                        header[keyname] = (float(str(header[keyname]).replace(',', '.')),
                                           instrument_model[keyname]["description"])
                    except ValueError:
                        print(f"Could not convert {keyname} to float in {
                              fits_file}. Skipping.")
                        failed_fits = True
    if not failed_fits:
        # Create new fits file with adapted header and data
        new_fits_file = fits.HDUList(
            [fits.PrimaryHDU(data=data, header=header)])
        # Update CHECKSUM and DATASUM keywords in the header
        new_fits_file[0].verify('fix')
        new_fits_file.writeto(new_fits_path)
        print(f"Adapted header and saved new fits file to {new_path}.")

    return failed_fits


def main(args, new_data_dir):

    # collect all fits files in the directory and its subdirectories
    directory = args.directory
    fits_files = []
    for root, _, files in os.walk(directory):
        for file in files:
            if file.endswith(".fits"):
                fits_files.append(os.path.join(root, file))

    for fits_file in fits_files[:1]:
        new_fits_file = os.path.join(new_data_dir, os.path.basename(fits_file))
        if os.path.exists(new_fits_file):
            print(f"File {new_fits_file} already exists. Skipping.")
            continue
        failed_fits = adapt_headers_and_directories(
            fits_file, new_data_dir, new_fits_file)
        if failed_fits:
            print(f"Failed to adapt header for {fits_file}.")


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
    _night = args.directory.split("/")[-1]
    _year = _night[:2]
    _month = month_conversion[_night[2:5].lower()]
    _day = _night[5:7]
    _date_dir = f"20{_year}{_month}{_day}"
    raw_dir = "/ssdsto1/data/bc060/"
    new_data_dir = os.path.join(raw_dir, _date_dir)
    if not os.path.exists(new_data_dir):
        os.makedirs(new_data_dir)

    main(args, new_data_dir)
