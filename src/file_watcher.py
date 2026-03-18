import time
import os
from pathlib import Path
from typing import List


class FileWatcher:
    def __init__(self, directories: List[str], extensions=None, poll_interval=1):
        self.directories = [Path(d) for d in directories]
        self.extensions = extensions or {'.fits', '.fit', '.fts'}
        self.poll_interval = poll_interval

        # Controle de estado
        self.last_seen_files = set()
        self.initialized = False

    def _scan_all_files(self):
        """Scan all directories and return matching files."""
        files = []

        for directory in self.directories:
            if not directory.exists():
                continue

            for path in directory.rglob('*'):
                if path.suffix.lower() in self.extensions:
                    files.append(path)

        return files

    def initialize(self):
        """
        Initialize watcher ignoring pre-existing files.
        """
        existing_files = self._scan_all_files()
        self.last_seen_files = set(existing_files)
        self.initialized = True

        print(f"Watcher initialized. Ignoring {len(existing_files)} existing files.")

    def get_new_files(self):
        """
        Return only new files since last iteration.
        """
        current_files = set(self._scan_all_files())

        new_files = current_files - self.last_seen_files

        # Updates state (even if it fails later)
        self.last_seen_files = current_files

        return sorted(new_files, key=lambda x: x.stat().st_mtime)

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