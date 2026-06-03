#!/bin/python

"""
This module defines the FileWatcher class, which is responsible for monitoring
directories for new FITS files. The new files are handed to the
observation_manager module for processing and insertion into the database.

Author: Thaiane Cassetari
"""

import time
import os #mtime
from pathlib import Path #mtime
from typing import List


class FileWatcher:
    def __init__(
        self,
        directories: List[str] = None,
        config: dict = None,
        poll_interval=1,
        extensions=None,
        process_existing=False
    ):
        self.extensions = extensions or {'.fits', '.fit', '.fts'}
        self.poll_interval = poll_interval
        self.process_existing = process_existing

        # State tracking -> highest timestamp seen
        self.last_checkpoint = 0.0 
        self.initialized = False

        # Directories currently being monitored
        self.active_directories = []

        if config:
            self.directories = self._load_directories_from_config(config)
        else:
            self.directories = [Path(d) for d in (directories or [])]

    # def initialize(self):
    #     """
    #     Define the starting point (timestamp)
    #     """
    #     if self.process_existing:
    #         self.last_checkpoint = 0.0
    #         print(f"Watcher initialized.")
    #     else:
    #         self.last_checkpoint = time.time()
    #         print(f"Watcher initialized => time.time")
    #     self.initialized = True
    #     print(f"Watcher initialized. Starting point: {self.last_checkpoint}")

    def initialize(self):
        """
        Define the starting point (timestamp)
        and discover latest active directories.
        """

        if self.process_existing:
            self.last_checkpoint = 0.0
            self.initialized = True
            print("Watcher initialized.")
            return
        
        newest_file_mtime = 0
        self.active_directories = []

        for root_dir in self.directories:
            latest_dir = self._find_latest_directory(root_dir)
            if latest_dir:
                self.active_directories.append(latest_dir)
                print(f"DEBUG: Active directory => {latest_dir}")
                file_mtime = self._find_latest_file_mtime(latest_dir)

                if file_mtime > newest_file_mtime:
                    newest_file_mtime = file_mtime

        self.last_checkpoint = newest_file_mtime

        self.initialized = True

        print(f"Watcher initialized. Starting point: {self.last_checkpoint}")


    def _find_latest_directory(self, root_directory):
        """
        Find the most recently modified subdirectory.
        """
        latest_dir = None
        latest_mtime = 0

        try:
            with os.scandir(root_directory) as entries:

                for entry in entries:

                    if entry.is_dir():

                        try:
                            mtime = entry.stat().st_mtime

                            if mtime > latest_mtime:
                                latest_mtime = mtime
                                latest_dir = Path(entry.path)

                        except OSError:
                            continue

        except OSError:
            return None
        return latest_dir

    def _find_latest_file_mtime(self, directory):
        """
        Find the newest FITS file inside a directory.
        """
        latest_mtime = 0

        try:
            for path in directory.rglob('*'):

                if (
                    path.is_file()
                    and path.suffix.lower() in self.extensions
                ):
                    try:
                        mtime = path.stat().st_mtime

                        if mtime > latest_mtime:
                            latest_mtime = mtime

                    except OSError:
                        continue

        except OSError:
            pass

        return latest_mtime

    def get_new_files(self):
        """
        Return only new files since last iteration.
        Scan only the latest modified directories.
        """
        new_files = []
        max_mtime_found = self.last_checkpoint

        # Refresh active directories
        updated_active_dirs = []

        for root_dir in self.directories:
            latest_dir = self._find_latest_directory(root_dir)
            if latest_dir:
                updated_active_dirs.append(latest_dir)
        self.active_directories = updated_active_dirs

        for directory in self.active_directories:
            if not directory.exists():
                continue
            try:
                for path in directory.rglob('*'):
                    if (
                        path.is_file()
                        and path.suffix.lower() in self.extensions
                    ):
                        try:
                            mtime = path.stat().st_mtime
                            if mtime > self.last_checkpoint:
                                new_files.append(path)
                                if mtime > max_mtime_found:
                                    max_mtime_found = mtime
                        except OSError:
                            continue
            except OSError:
                continue
        # Sort files by modification time
        if new_files:
            new_files.sort(key=lambda p: p.stat().st_mtime)
            self.last_checkpoint = max_mtime_found
            return [str(p) for p in new_files]

        return []  # Return an empty list if nothing is found

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

            print(f"DEBUG: Waiting {self.poll_interval} seconds... ")

    def _load_directories_from_config(self, config):
        """
        Load directories from config file.
        """
        directories = []

        data_root = config.get("data_root", "")
        instruments = config.get("instruments", {})

        for instrument_name, instrument_data in instruments.items():
            raw_dir = os.path.expandvars(
                instrument_data.get("raw_data_directory"))

            if raw_dir:
                full_path = Path(data_root) / raw_dir

                if full_path.exists():
                    print(f"DEBUG: Watching {full_path}")
                    directories.append(full_path)
                else:
                    print(f"WARNING: Directory does not exist: {full_path}")

        return directories
