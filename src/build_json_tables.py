#!/bin/python

"""
Create JSON files from CSV tables containing the column definitions
for the database. The base column in the CSV file for data collection
is 202A, which contains the in-discussion definitions that are 
currently agreed upon.
"""

import os
import pandas as pd
import json
import argparse


def parse_args():
    parser = argparse.ArgumentParser(
        description="Create JSON files from CSV tables containing the column definitions for the database."
    )
    parser.add_argument('model_type',
                        type=str,
                        choices=['primary', 'inst_spec'],
                        help="Type of model to build: 'primary' for primary data model, 'inst_spec' for instrument-specific model."
                        )
    parser.add_argument(
        "--data-path",
        type=str,
        default="resources",
        help="Path to the directory containing the CSV files."
    )
    parser.add_argument(
        "--output-path",
        type=str,
        default="data",
        help="Path to the directory where the JSON files will be saved."
    )
    parser.add_argument(
        "--csv-filename",
        type=str,
        default="LNA-DXU-Header-standards-mandatory.csv",
        help="Name of the CSV file containing the column definitions."
    )
    parser.add_argument(
        "--instrument",
        type=str,
        default=None,
        help="Name of the instrument for instrument-specific model (required if model_type is 'inst_spec')."
    )
    return parser.parse_args()


def main(args):
    # get path where this script is located
    script_dir = os.path.dirname(os.path.abspath(__file__))
    resources_path = os.path.join(script_dir, '..', args.data_path)
    model_path = os.path.join(script_dir, '..', args.output_path)
    csv_path = os.path.join(resources_path, args.csv_filename)
    csv_table = pd.read_csv(csv_path)

    if args.model_type == 'primary':
        print("Building primary data model...")
        json_filename = "primary_table.json"
        csv_table = csv_table[csv_table['INST_SPEC'] == 'n']
    elif args.model_type == 'inst_spec':
        if not args.instrument:
            raise ValueError(
                "Instrument name must be provided for instrument-specific model.")
        print(
            f"Building instrument-specific data model for {args.instrument}...")
        json_filename = f"{args.instrument.lower()}.json"
        csv_table = csv_table[csv_table['INST_SPEC'] == 'y']
    else:
        raise ValueError(
            "Invalid model type. Must be 'primary' or 'inst_spec'.")

    # tables will be located in a back directory "data"
    json_path = os.path.join(model_path, json_filename)
    if os.path.exists(json_path):
        print(f"Warning: {json_path} already. Renaming existing file to {
              json_path}.bak")
        os.rename(json_path, json_path + ".bak")
    json_table = []

    for line in csv_table.itertuples():
        if not pd.isna(line.S2026A):
            colname = line.S2026A
            entry = {
                "colname": colname,
            }
            is_nullable = line.Nullable
            if not is_nullable:
                entry["nullable"] = False
            else:
                default_value = line.Default
                if default_value is not None and not pd.isna(default_value):
                    entry["default_value"] = default_value
            datatype = line.Type
            if datatype is None or pd.isna(datatype):
                raise ValueError(
                    f"Datatype is required for column {colname} but is missing.")
            else:
                entry["datatype"] = datatype
            allowed_values = line.Allowed_Values
            if allowed_values is not None and not pd.isna(allowed_values):
                entry["allowed_values"] = allowed_values
            description = line.Comment
            if description is not None and not pd.isna(description):
                entry["description"] = description
            json_table.append(entry)

    with open(json_path, "w") as json_file:
        json.dump(json_table, json_file, indent=4)

    print(f"JSON table written to {json_path}")


if __name__ == "__main__":
    args = parse_args()
    main(args)
