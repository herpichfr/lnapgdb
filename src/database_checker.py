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
    

    def get_registered_files(self):
        """Search all database paths that contain the folder date"""
        query = text("""
            SELECT raw_path 
            FROM public.primary_table 
            WHERE raw_path LIKE :date_filter
        """)
        # LIKE ensures that we will only bring the data from that night, saving memory.
        date_filter = f"%{self.date}%" 

        with self.db.engine.connect() as conn:
            result = conn.execute(query, {"date_filter": date_filter}).fetchall()
            
        return {row[0] for row in result}
    
    def run(self):
        files = self.scan_files()
        missing_files = []
        if not files:
            print(f"Nenhum arquivo local encontrado para a data: {self.date}")
            return
        print(f"Avaliando {len(files)} arquivos no disco. Buscando banco de dados...")

        db_files = self.get_registered_files()

        missing_files = [file for file in files if file not in db_files]

        print(f"Arquivos faltando: {len(missing_files)}")

        if missing_files:
            log_name = f"missing_files_{self.date}.log"
            
            with open(log_name, "w", encoding="utf-8") as f: # para evitar erros com caracteres especiais
                for file in missing_files:
                    f.write(f"{file}\n")

            print(f"Log de arquivos faltando salvo em: {log_name}")

        else:
            print("Sucesso! Todos os arquivos estão presentes no banco de dados.")