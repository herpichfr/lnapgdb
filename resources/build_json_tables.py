#!/bin/python

"""Create JSON tables from CSV files to use as base to build
the database tables."""

import os
import pandas as pd
import json

# get path where this script is located
script_dir = os.path.dirname(os.path.abspath(__file__))

# tables will be located in a back directory "data"
data_path = os.path.join(script_dir, "..", "data")
csv_path = os.path.join(data_path, "HDU0.csv")
csv_table = pd.read_csv(csv_path)
json_path = os.path.join(data_path, "HDU0.json")
json_table = []
# add a primary key to json table
pk_entry = {
    "colname": "id",
    "default_value": None,
    "datatype": "INTEGER",
    "allowed_values": None,
    "description": "Primary key"
}
json_table.append(pk_entry)

for line in csv_table.itertuples():
    if not pd.isna(line.NoirLab):
        colname = line.NoirLab
        default_value = line.Example
        datatype = line.Type
        allowed_values = line.Allowed_Values if not pd.isna(
            line.Allowed_Values) else None
        description = line.Comment if not pd.isna(line.Comment) else ""
        entry = {
            "colname": colname,
            "default_value": default_value,
            "datatype": datatype,
            "allowed_values": allowed_values,
            "description": description
        }
        json_table.append(entry)

with open(json_path, "w") as json_file:
    json.dump(json_table, json_file, indent=4)

print(f"JSON table written to {json_path}")
