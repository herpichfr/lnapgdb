#!/bin/python

"""
Modify the SPARC4 headers while copying the images to a new directory.
This is necessary now due to divergencies between the data and the DB
data model for ingestion. The script can later be modified to adapt
data from different instruments.

Date of creation: 2026-04-30
"""

import os
from astropy.io import fits
import argparse


def parse_args():
    parser = argparse.ArgumentParser(
        description='Modify SPARC4 headers and copy images to a new directory.')
    parser.add_argument('--input_dir',
                        type=str,
                        required=True,
                        help='Directory containing the original FITS files.')
    parser.add_argument('--output_dir',
                        type=str,
                        required=True,
                        help='Directory to save the modified FITS files.')
    parser.add_argument('--night',
                        type=str,
                        default=None,
                        help='Night of observation in YYYYMMDD format.')
    parser.add_argument('--clobber', action='store_true',
                        help='Overwrite existing files in the output directory.')

    return parser.parse_args()


def keys_to_modify():
    return {
        'PROJID': 'PROPID',
    }


def keys_to_add():
    return {
        'TELESCOP': ('PE160', "Telescope name"),
        'SITEID': ('OPD', "Observatory/Site"),
        # NOTE: This will be set based on the file creation date in isot format.
        'DATEFILE': (None, "File creation date"),
        # NOTE: This will be calculated and added to the header.
        'CHECKSUM': (None, "HDU checksum"),
        # NOTE: This will be calculated and added to the header.
        'DATASUM': (None, "Data checksum"),
    }


def mofity_and_copy_file(input_file, output_file, clobber=False):
    with fits.open(input_file) as hdul:
        header = hdul[0].header

        # Modify keys. Get old value and description, and set them to the new key.
        for old_key, new_key in keys_to_modify().items():
            if old_key in header:
                old_value = header[old_key]
                old_comment = header.comments[old_key]
                header[new_key] = (old_value, old_comment)
                del header[old_key]

        # Add new keys
        for key, value in keys_to_add().items():
            if key in header:
                continue
            if value is not None:
                header[key] = value

        # Update DATEFILE based on file creation date
        header['DATEFILE'] = os.path.getctime(input_file)

        # Calculate CHECKSUM and DATASUM
        hdul.verify('fix')
        hdul.flush()  # Ensure changes are written to the file before calculating checksums
        hdul[0].add_checksum()

        print(f"Copying {input_file} to {output_file} with modified headers.")
        hdul.writeto(output_file, overwrite=clobber)


def main(args):
    root_dir = args.input_dir
    output_dir = args.output_dir

    # NOTE: Inside root_dir, there are dirs:
    acs_dirs = ['win_sparc4acs1', 'win_sparc4acs2',
                'win_sparc4acs3', 'win_sparc4acs4']
    # Inside each of these dirs, there are NIGHT dirs
    # Inside each NIGHT dir, there are the FITS files.
    night_dirs = []
    latest_copied_files = {'win_sparc4acs1': None, 'win_sparc4acs2': None,
                           'win_sparc4acs3': None, 'win_sparc4acs4': None}
    for acs_dir in acs_dirs:
        acs_path = os.path.join(root_dir, acs_dir)
        if not os.path.isdir(acs_path):
            continue
        if args.night is None:
            # Select latest night dir in sparc4acs1
            night_dir = sorted([d for d in os.listdir(
                acs_path) if os.path.isdir(os.path.join(acs_path, d))])[-1]
            night_dirs.append(os.path.join(acs_path, night_dir))
        else:
            night_dir = os.path.join(acs_path, args.night)
            if os.path.isdir(night_dir):
                night_dirs.append(night_dir)

        # If acs_dir is not present in output_dir, create it
        output_acs_dir = os.path.join(output_dir, acs_dir)
        if not os.path.isdir(output_acs_dir):
            os.makedirs(output_acs_dir)
        # If night_dir is not present in output_acs_dir, create it
        output_night_dir = os.path.join(
            output_acs_dir, os.path.basename(night_dir))
        if not os.path.isdir(output_night_dir):
            os.makedirs(output_night_dir)

        # Compare files in night_dir from both input and output dirs
        # Get only one file each time, always starting from the first non existing file in output dir
        input_files = sorted(
            [f for f in os.listdir(night_dir) if f.endswith('.fits')])
        output_files = sorted([f for f in os.listdir(
            output_night_dir) if f.endswith('.fits')])
        if len(output_files) > 0 and not args.clobber:
            latest_copied_file = output_files[-1]
            latest_copied_files[acs_dir] = latest_copied_file
            next_file_to_copy = [
                f for f in input_files if f > latest_copied_file][0]
        else:
            next_file_to_copy = input_files[0]

        mofity_and_copy_file(os.path.join(night_dir, next_file_to_copy),
                             os.path.join(output_night_dir, next_file_to_copy),
                             clobber=args.clobber)

    print("Images copied with modified headers. Latest copied files:")
    for acs_dir, latest_file in latest_copied_files.items():
        print(f"{acs_dir}: {latest_file}")


if __name__ == "__main__":
    args = parse_args()
    main(args)
