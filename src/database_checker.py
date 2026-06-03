import os
from pathlib import Path
from datetime import datetime, timedelta
from sqlalchemy import text

class DatabaseChecker:

    def __init__(self, directories, db, date=None, extensions=None):
        self.directories = directories
        self.db = db
        self.extensions = extensions or {'.fits', '.fit', '.fts'}
        self.date = date or (
            datetime.now() - timedelta(days=1)
        ).strftime("%Y%m%d")

    def scan_files(self):
        files = []

        for directory in self.directories:
            date_directory = Path(directory) / self.date

            if not date_directory.exists():
                print(f"Directory not found: {date_directory}")
                continue

            for path in date_directory.rglob('*'):
                if path.is_file() and path.suffix.lower() in self.extensions:
                    files.append(str(path.resolve()))

        return files
    
    def file_exists_in_db(self, filepath):
        with self.db.engine.connect() as conn:
                result = conn.execute(
                    text("""
                        SELECT 1
                        FROM public.primary_table
                        WHERE raw_path = :filepath
                        LIMIT 1
                    """),
                    {"filepath": filepath}
                    ).fetchone()

        return result is not None
    
    def run(self):
        files = self.scan_files()
        missing_files = []
        print(f"Checking {len(files)} files...")

        for file in files:
            if not self.file_exists_in_db(file):
                missing_files.append(file)

        print(f"Missing files: {len(missing_files)}")

        if missing_files:
            log_name = f"missing_files_{self.date}.log"
            with open(log_name, "w") as f:
                for file in missing_files:
                    f.write(f"{file}\n")

            print(f"Missing files log saved: {log_name}")

        else:
            print("All files are present in the database.")