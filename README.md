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
├── data/
├── figures/
├── models/
├── resources/
├── src/
├── venv/
├── LICENSE
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
(optional but recommended)

```bash
python -m venv venv
```

**Linux/macOS**

```bash
source venv/bin/activate
```

**Windows**

```bash
venv\Scripts\activate
```

### 4. Install the dependencies

**Python**

```bash
pip install -r requirements.txt
```

### 5. Configure the database

- Create the PostgreSQL database.

- Import the SQL schema (if available).

- Configure the required environment variables.


### 6. Run the project

```bash
python src/observation_manager.py
```
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
