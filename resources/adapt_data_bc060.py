#!/bin/python

"""
Adapt headers and directories names for Cam1 data so it is compliant with
the LNADB data model. This script will need to be run as a service until
we implement the robotization of the data acquisition.

@author: Herpich, F. R. email: fherpich@lna.br
"""

import os
from astropy.io import fits
from astropy.time import Time
import numpy as np
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
    parser.add_argument(
        "--calendar",
        type=str,
        required=True,
        help="Path to the calendar CSV file.",
    )
    parser.add_argument(
        "--clobber",
        action="store_true",
        help="Overwrite existing files in the new directory.",
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


def get_telescope_properties(telescope_orig_name):
    """
    Get the properties of the given telescope.

    Parameters
    ----------
    telescope_name : str
        Name of the telescope.

    Returns
    -------
    dict
        Properties of the given telescope.
    """
    telescope_names = {
        "BC060": ["BC060", "IAG", "0.60m(BC)"],
        "PE160": ["PE160"]
    }
    # NOTE: The legacy telescope value contains the name and may have attached
    # the focal reducer separated by space
    telescope_array = telescope_orig_name.split(" ")
    if len(telescope_array) > 1:
        telescope_name = telescope_array[0]
    else:
        telescope_name = telescope_orig_name
    # Check if the telescope name is in the dictionary and select the equivalent name atributed to the list where the telescope is located
    for key, value in telescope_names.items():
        if telescope_name in value:
            telescope_value = key
            break
        else:
            telescope_value = None

    if "reducer" in telescope_array:
        has_reducer = True
    else:
        has_reducer = False

    return telescope_value, has_reducer


def adapt_headers_and_directories(fits_file, new_fits_path, obs_data):
    """
    Adapt headers and directories names for instruments used in IAG telescope.

    Parameters
    ----------
    directory : str 
        Directory containing the raw data.
    raw_dir : str
        Directory where the formated raw data is stored.
    """  # TODO: Correct parameters
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
            # NOTE: Keywords INSTRUME and OBSERVER present in the header
            # are not compatible with the LNADB data model. Moving their
            # values to legacy keywords INST INSTRUME and OPER OBSERVER,
            # respectively.
            header["INST INSTRUME"] = (instrument,
                                       header.comments["INSTRUME"])
            header["OPER OBSERVER"] = (header.get("OBSERVER", None),
                                       header.comments["OBSERVER"])
            header["TEL TELESCOP"] = (header.get("TELESCOP", None),
                                      header.comments["TELESCOP"])
            instrument_name = instrument.split('+')[0]
            header["INSTRUME"] = (instrument_name,
                                  primary_model["INSTRUME"]["description"])
            detector_name = instrument.split('+')[1]
            instrument_model = get_data_model(instrument_name.lower())
            header["DETECTOR"] = (detector_name,
                                  instrument_model["DETECTOR"]["description"])
            header["OBSERVER"] = (primary_model["OBSERVER"]["default"],
                                  primary_model["OBSERVER"]["description"])
            telescope_name = header.get("TELESCOP", None)
            telescope_value, has_reducer = get_telescope_properties(
                telescope_name)
            header["TELESCOP"] = (telescope_value,
                                  primary_model["TELESCOP"]["description"])
            header["FOCRED"] = (has_reducer,
                                primary_model["FOCRED"]["description"])
            header["PROPID"] = (obs_data["propid"],
                                primary_model["PROPID"]["description"])
            header["PI-COI"] = (obs_data["pi_coi"],
                                primary_model["PI-COI"]["description"])
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
        print(f"Adapted header and saved new fits file to {new_fits_path}.")
    else:
        print(f"Failed to adapt header for {fits_file}.")
        import pdb
        pdb.set_trace()

    return failed_fits


def get_calendar(args):
    """
    Get calendar to define the projects associated to a given observation.

    Parameters
    ----------
    args : Namespace
        Command line arguments.

    Returns
    -------
    calendar : dict
        Dictionary with the calendar information.
    """
    calendar = pd.read_csv(args.calendar, sep=',', header=0)
    night_starts = [Time(date, format='isot', scale='utc')
                    for date in calendar['yyyy-mm-dd']]
    propid = calendar["PropID-BC060"]
    pi_coi = calendar["PrincipalInvestigatorIAG"]

    bc060_calendar = {}
    bc060_calendar["night_starts"] = night_starts
    bc060_calendar["propid"] = propid
    bc060_calendar["pi_coi"] = pi_coi

    return bc060_calendar


def main(args, new_data_dir):

    # collect all fits files in the directory and its subdirectories
    directory = args.directory
    fits_files = []
    for root, _, files in os.walk(directory):
        for file in files:
            if file.endswith(".fits"):
                fits_files.append(os.path.join(root, file))

    # Get calendar
    cal = get_calendar(args)
    obs_starts = Time.strptime(
        new_data_dir.split("/")[-1], "%Y%m%d", scale='utc')
    _match_date = cal["night_starts"] == obs_starts
    if not np.any(_match_date):
        print(f"No matching date found in calendar for {obs_starts}.")
        raise ValueError(
            f"No matching date found in calendar for {obs_starts}.")
    elif sum(_match_date) > 1:
        print(f"Multiple matching dates found in calendar for {obs_starts}.")
        raise ValueError(
            f"Multiple matching dates found in calendar for {obs_starts}.")
    else:
        propid = np.array(cal["propid"])[_match_date][0]
        pi_coi = np.array(cal["pi_coi"])[_match_date][0]
        obs_date = {"propid": propid, "pi_coi": pi_coi}

    for fits_file in fits_files:
        new_fits_file = os.path.join(new_data_dir, os.path.basename(fits_file))
        if os.path.exists(new_fits_file):
            if not args.clobber:
                print(f"File {new_fits_file} already exists. Skipping.")
                continue
            else:
                print(f"File {new_fits_file} already exists. Overwriting.")
                os.remove(new_fits_file)
        failed_fits = adapt_headers_and_directories(
            fits_file, new_fits_file, obs_date)
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
