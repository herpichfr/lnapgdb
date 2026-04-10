import time
import os
from pathlib import Path
from typing import List


class FileWatcher:
    def __init__(
            self, 
            directories: List[str] = None,
            config: dict = None,
            poll_interval=1,
            extensions=None,
            process_existing=False # para teste
        ):
        self.extensions = extensions or {'.fits', '.fit', '.fts'}
        self.poll_interval = poll_interval

        # para teste
        self.process_existing = process_existing

        # State tracking -> highest timestamp seen
        self.last_checkpoint = 0.0 #self.last_seen_files = set()
        self.initialized = False

        if config:
            self.directories = self._load_directories_from_config(config)
        else:
            self.directories = [Path(d) for d in (directories or [])]

    def _scan_all_files(self):  #ver se tira essa parte, para n ler todos os arquivos
        """Scan all directories and return matching files."""
        files = []

        for directory in self.directories:
            if not directory.exists():
                continue

            for path in directory.rglob('*'):
                if path.is_file() and any(str(path).lower().endswith(ext) for ext in self.extensions):
                    files.append(path)
            print(f"DEBUG: Scanning directory: {directory}[file_watcher/_scan_all_files/42]")

        print(f"DEBUG: Scanning directory: {directory}[file_watcher/_scan_all_files/44]")
        return files

    def initialize(self):
        """
        Define the starting point (timestamp)
        """

        if self.process_existing:
            self.last_checkpoint = 0.0
            print(f"Watcher initialized.")
        else:
            self.last_checkpoint = time.time()
            print(f"Watcher initialized => time.time")

        self.initialized = True
        print(f"Watcher inicializado. Ponto de partida: {self.last_checkpoint}")

    def get_new_files(self):
        """
        Return only new files since last iteration.
        Retorna apenas arquivos cujo mtime seja maior que o último checkpoint.
        """
        new_files = []
        max_mtime_found = self.last_checkpoint

        for directory in self.directories:
            if not directory.exists():
                continue
            
            # Use an iterator to avoid loading everything into memory at once
            for path in directory.rglob('*'):
                if path.is_file() and path.suffix.lower() in self.extensions:
                    try:
                        mtime = path.stat().st_mtime
                        if mtime > self.last_checkpoint:
                            new_files.append(path) # Track the newest file in this batch
                            if mtime > max_mtime_found:
                                max_mtime_found = mtime
                    except OSError:
                        continue # File may have been deleted or locked

            new_files.sort(key=lambda p: p.stat().st_mtime)
            
        # Update the global checkpoint with the latest processed file timestamp
        if new_files:
            new_files.sort(key=lambda p: p.stat().st_mtime)
            self.last_checkpoint = max_mtime_found
            return [str(p) for p in new_files]
        
        return [] # Return an empty list if nothing is found

    def watch(self):
        """
        Generator that yields new files continuously.
        """
        if not self.initialized:
            self.initialize()

        while True:
            new_files = self.get_new_files()

            if new_files:
                print(f"DEBUG: Found {len(new_files)} new files.")
                yield new_files

            time.sleep(self.poll_interval)

            print(f"DEBUG: Waiting {self.poll_interval} seconds... [file_watcher-82]")

    def _load_directories_from_config(self, config):
        """
        Load directories from config file.
        """
        directories = []

        data_root = config.get("data_root", "")
        instruments = config.get("instruments", {})

        for instrument_name, instrument_data in instruments.items():
            raw_dir = instrument_data.get("raw_data_directory")

            if raw_dir:
                full_path = Path(data_root) / raw_dir

                if full_path.exists():
                    print(f"DEBUG: Watching {full_path}")
                    directories.append(full_path)
                else:
                    print(f"WARNING: Directory does not exist: {full_path}")

        return directories