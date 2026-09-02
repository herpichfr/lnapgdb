# 🌌 BancoINA – Astronomical Image Database (FITS)
Postgresql database for LNA observations

## 📖 About the Project

O **BancoINA** is a system designed for the storage, organization, and management of astronomical data in the **FITS (Flexible Image Transport System)** format.

The project aims to facilitate the ingestion, querying, and retrieval of astronomical data while preserving the metadata required for scientific research and long-term data management.


## ✨ Features

- Import FITS files
- Automatic extraction of FITS headers
- Storage of metadata in PostgreSQL
- Query and retrieval of stored data
- Visualization of file information



## 🛠 Technologies

- Python
- PostgreSQL



## 📂 Project Structure

```text
lnapgdb/
│
├── config/
├── credentials/
├── data/
├── figures/
├── lnapgdb/         # installable Python package (was "src/")
├── models/
├── resources/
├── venv/
├── LICENSE
├── pyproject.toml
├── README.md
└── ...
```



## 🚀 Getting Started

### 1. Clone the repository

```bash
git clone https://github.com/herpichfr/lnapgdb.git
```

### 2. Navigate to the project directory

```bash
cd lnapgdb
```
### 3. Create and activate a virtual environment

```bash
python3 -m venv venv
source venv/bin/activate
```

> ⚠️ Do not create the virtual environment or run any of the commands below
> as `root`, and never invoke them with `sudo`. The tool refuses to start
> when it detects either, since it writes logs and inserts data on behalf of
> the regular observing account, not `root`.

### 4. Install the package

Installing in **editable** mode is the supported method, since the tool
resolves `config/`, `credentials/` and `models/` relative to the location of
the `lnapgdb/` package on disk — keep the git checkout in place after
installing.

```bash
pip install -e .
```

This reads all dependencies from `pyproject.toml` and also installs a set of
console commands onto your `PATH` (inside the virtualenv):

- `lnapgdb-observation-manager`
- `lnapgdb-data-collector`
- `lnapgdb-database-checker`
- `lnapgdb-insert-db`
- `lnapgdb-retry-missing`
- `lnapgdb-build-model`

`pip install -r requirements.txt` still works too — it simply runs the same
editable install.

### 5. Configure the database

- Create the PostgreSQL database.

- Import the SQL schema (if available).

- Configure the required environment variables.

- Add machine-specific credentials to `credentials/db_config.json` (this
  directory is gitignored and never committed).

### 6. Run the project

```bash
lnapgdb-observation-manager
# equivalent to: python -m lnapgdb.observation_manager
```

### 📄 Logs

All log files (main run logs, failed-file logs, missing-file reports, etc.)
are written to a `logs/` folder in the **home directory of the user running
the code** (`~/logs`), which is created automatically if it doesn't exist
yet. Log files are never written inside the package/installation directory.
---

## 📁 FITS Format

This project uses the FITS (Flexible Image Transport System) format, the standard format in astronomy for storing scientific images and observational data.

The metadata contained in FITS headers are automatically extracted and stored in a PostgreSQL database, enabling efficient querying and organization of astronomical observations.



## 🎯 Objectives

- Preserve scientific metadata.
- Facilitate data access for researchers.
- Provide a scalable platform for managing astronomical datasets.


## 📌 Roadmap

- [x] FITS file import
- [x] Automatic metadata extraction
- [ ] Support for multiple observatories


## 📄 Licença

This project is licensed under the **LNA General License Agreement v1**.

For more information, see the `LICENSE` file.


Developed for **BancoINA**, a system for storing and managing astronomical metadata extracted from FITS files.


---
