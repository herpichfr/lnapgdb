#!/bin/python

"""
Create JSON files from CSV tables containing the column definitions
for the database. Each model has its own CSV file under the models
directory (e.g. primary_table.csv, sparc4.csv, cam1.csv, robocam.csv),
already filtered to that model's rows via its INSTRUME column. This
script reads every such CSV (or a selected subset) and writes the
matching JSON file, deriving the output filename from the CSV
basename.
"""

import os
import sys
import pandas as pd
import json
import argparse


def parse_args():
    parser = argparse.ArgumentParser(
        description="Create JSON files from CSV tables containing the column definitions for the database."
    )
    parser.add_argument(
        "models",
        type=str,
        nargs="*",
        help="Model names or CSV paths to process. If omitted, every *.csv file in --models-path is processed."
    )
    parser.add_argument(
        "--models-path",
        type=str,
        default="models",
        help="Path to the directory containing the CSV files."
    )
    parser.add_argument(
        "--output-path",
        type=str,
        default=None,
        help="Path to the directory where the JSON files will be saved. Defaults to --models-path."
    )
    parser.add_argument(
        "--no-backup",
        action="store_true",
        help="Do not back up an existing JSON file before overwriting it."
    )
    return parser.parse_args()


def resolve_csv_path(model, models_path):
    if os.path.exists(model):
        return model
    filename = model if model.endswith(".csv") else f"{model}.csv"
    return os.path.join(models_path, filename)


def build_table(csv_path, output_path, make_backup):
    basename = os.path.splitext(os.path.basename(csv_path))[0]
    expected_model = "primary" if basename == "primary_table" else basename

    print(f"Building data model for {basename}...")
    csv_table = pd.read_csv(csv_path)

    json_filename = f"{basename}.json"
    json_path = os.path.join(output_path, json_filename)
    if os.path.exists(json_path):
        if make_backup:
            print(f"Warning: {json_path} already exists. Renaming existing file to {json_path}.bak")
            os.rename(json_path, json_path + ".bak")
        else:
            print(f"Warning: {json_path} already exists and will be overwritten (--no-backup).")

    json_table = []

    for line in csv_table.itertuples():
        if pd.isna(line.KWS2026A):
            continue

        colname = str(line.KWS2026A).strip()

        instrume = line.INSTRUME
        if instrume is not None and not pd.isna(instrume):
            associations = [a.strip() for a in str(instrume).split(",")]
            if expected_model not in associations:
                print(
                    f"Warning: {basename}.csv row {colname}: INSTRUME {associations} "
                    f"does not include expected model '{expected_model}'",
                    file=sys.stderr
                )

        entry = {"colname": colname}

        entry["mandatory"] = str(line.Mandatory).strip()

        is_nullable = line.Nullable
        if not is_nullable:
            entry["nullable"] = False

        default_value = line.Default
        if default_value is not None and not pd.isna(default_value):
            entry["default_value"] = str(default_value).strip()

        datatype = line.Type
        if datatype is None or pd.isna(datatype):
            raise ValueError(
                f"Datatype is required for column {colname} but is missing.")
        entry["datatype"] = str(datatype).strip()

        allowed_values = line.Allowed_Values
        if allowed_values is not None and not pd.isna(allowed_values):
            entry["allowed_values"] = str(allowed_values).strip()

        description = line.Comment
        if description is not None and not pd.isna(description):
            entry["description"] = str(description).strip()

        json_table.append(entry)

    with open(json_path, "w") as json_file:
        json.dump(json_table, json_file, indent=4)

    print(f"JSON table written to {json_path}")


def main(args):
    script_dir = os.path.dirname(os.path.abspath(__file__))
    models_path = os.path.join(script_dir, '..', args.models_path)
    output_path = args.output_path if args.output_path is not None else args.models_path
    output_path = os.path.join(script_dir, '..', output_path)

    if args.models:
        csv_paths = [resolve_csv_path(m, models_path) for m in args.models]
    else:
        csv_paths = sorted(
            os.path.join(models_path, f)
            for f in os.listdir(models_path)
            if f.endswith(".csv")
        )

    for csv_path in csv_paths:
        build_table(csv_path, output_path, make_backup=not args.no_backup)


if __name__ == "__main__":
    args = parse_args()
    main(args)
