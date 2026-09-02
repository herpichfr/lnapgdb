#!/bin/python3

"""
This module defines the FileWatcher class, which is responsible for monitoring
directories for new FITS files. The new files are handed to the
observation_manager module for processing and insertion into the database.

Author: Thaiane Cassetari
"""

import time
import os
import re
from pathlib import Path
from typing import List


def resolve_instrument_directories(config):
    """
    Resolve each instrument's raw_data_directory from a loaded config dict,
    expanding environment variables. Shared by FileWatcher and DatabaseChecker
    so both always agree on where each instrument's data actually lives.

    Returns a list of (instrument_name, Path, exists) tuples.
    """
    resolved = []
    data_root = config.get("data_root", "")
    instruments = config.get("instruments", {})

    for instrument_name, instrument_data in instruments.items():
        raw_dir = os.path.expandvars(
            instrument_data.get("raw_data_directory", ""))

        if not raw_dir:
            continue

        full_path = Path(data_root) / raw_dir
        resolved.append((instrument_name, full_path, full_path.exists()))

    return resolved


class FileWatcher:
    def __init__(
        self,
        directories: List[str] = None,
        config: dict = None,
        poll_interval=1,
        extensions=None,
        process_existing=False,
        exclude_today_dir=True
    ):
        self.extensions = extensions or {'.fits', '.fit', '.fts'}
        self.poll_interval = poll_interval
        self.process_existing = process_existing

        # State tracking -> highest timestamp seen and files sharing that exact timestamp
        self.last_checkpoint = 0.0
        self.seen_files_at_checkpoint = set()
        self.initialized = False

        # Directories currently being monitored
        self.active_directories = []
        self.exclude_today = exclude_today_dir if exclude_today_dir else True

        if config:
            self.directories = self._load_directories_from_config(config)
        else:
            self.directories = [Path(d) for d in (directories or [])]

    def initialize(self):
        """
        Define the starting point (timestamp)
        and discover latest active directories.
        """
        if self.process_existing:
            self.last_checkpoint = 0.0
            self.initialized = True
            print("Watcher initialized. Processing existing files.")
            return

        newest_file_mtime = 0
        self.active_directories = []

        for root_dir in self.directories:
            latest_dir = self._find_latest_directory(root_dir)
            if latest_dir:
                self.active_directories.append(latest_dir)
                print(f"DEBUG: Active directory => {latest_dir}")

                # Find the maximum mtime in this directory
                for path, mtime in self._fast_scan_fits(latest_dir):
                    if mtime > newest_file_mtime:
                        newest_file_mtime = mtime

        self.last_checkpoint = newest_file_mtime

        # Pre-populate the seen list with files exactly matching the starting checkpoint
        # to prevent them from being processed again
        for latest_dir in self.active_directories:
            for path, mtime in self._fast_scan_fits(latest_dir):
                if mtime == self.last_checkpoint:
                    self.seen_files_at_checkpoint.add(str(path))

        self.initialized = True
        print(f"Watcher initialized. Starting point: {self.last_checkpoint}")

    def _find_latest_directory(self, root_directory: Path):
        """
        Find the most recently modified subdirectory that matches YYYYMMDD format.
        """
        latest_dir = None
        latest_mtime = 0

        # Regex pattern for exactly 8 digits (YYYYMMDD)
        date_pattern = re.compile(r"^\d{8}$")

        try:
            with os.scandir(root_directory) as entries:
                for entry in entries:
                    if entry.is_dir():
                        # Ignore folders that are not exactly 8 digits
                        if not date_pattern.match(entry.name):
                            continue

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
    # def _find_latest_directory(self, root_directory: Path):
    #     """
    #     Find the most recently modified subdirectory.
    #     """
    #     latest_dir = None
    #     latest_mtime = 0
    #
    #     try:
    #         with os.scandir(root_directory) as entries:
    #             for entry in entries:
    #                 if entry.is_dir():
    #                     try:
    #                         mtime = entry.stat().st_mtime
    #                         if mtime > latest_mtime:
    #                             latest_mtime = mtime
    #                             latest_dir = Path(entry.path)
    #                     except OSError:
    #                         continue
    #     except OSError:
    #         return None
    #
    #     return latest_dir

    def _fast_scan_fits(self, directory: Path):
        """
        Recursively scan for fits files efficiently using os.scandir.
        Yields (Path object, mtime).
        """
        stack = [str(directory)]
        while stack:
            current_dir = stack.pop()
            try:
                with os.scandir(current_dir) as entries:
                    for entry in entries:
                        if entry.is_dir(follow_symlinks=False):
                            stack.append(entry.path)
                        elif entry.is_file(follow_symlinks=False):
                            # Fast string suffix check before creating Path objects
                            _, ext = os.path.splitext(entry.name)
                            if ext.lower() in self.extensions:
                                yield Path(entry.path), entry.stat().st_mtime
            except OSError:
                continue

    def get_new_files(self):
        """
        Return only new files since last iteration.
        Scan only the latest modified directories.
        """
        new_files_data = []

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

            # Fixed bug: Compare directory name to string, not Path to string
            if self.exclude_today and directory.name == "today":
                continue

            for path, mtime in self._fast_scan_fits(directory):
                path_str = str(path)

                # Strict greater than
                if mtime > self.last_checkpoint:
                    new_files_data.append((path_str, mtime))
                # Handle millisecond exact matches to avoid dropping concurrent files
                elif mtime == self.last_checkpoint and path_str not in self.seen_files_at_checkpoint:
                    new_files_data.append((path_str, mtime))

        # Sort files by modification time chronologically
        if new_files_data:
            new_files_data.sort(key=lambda x: x[1])

            # Identify the new absolute maximum checkpoint
            new_max_mtime = new_files_data[-1][1]

            if new_max_mtime > self.last_checkpoint:
                self.last_checkpoint = new_max_mtime
                # Reset seen files for the new max checkpoint
                self.seen_files_at_checkpoint = {
                    f[0] for f in new_files_data if f[1] == new_max_mtime}
            else:
                # If the max time didn't change (we just processed parallel files with the exact same mtime)
                self.seen_files_at_checkpoint.update(
                    f[0] for f in new_files_data if f[1] == new_max_mtime)

            return [f[0] for f in new_files_data]

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

    def _load_directories_from_config(self, config):
        """
        Load directories from config file.
        """
        directories = []

        for instrument_name, full_path, exists in resolve_instrument_directories(config):
            if exists:
                print(f"DEBUG: Watching {full_path}")
                directories.append(full_path)
            else:
                print(f"WARNING: Directory does not exist: {full_path}")

        return directories
