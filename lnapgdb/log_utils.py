#!/bin/python3

"""
Miscellaneous of tools to be used accross the several modules of the LNA DB
project. This includes functions for logging, error handling, and other
utilities that are not specific to any particular module but are used
throughout the project.
Copyright (c) 2025, LNA DB Team. All rights reserved.
This code is licensed under the LNA License v1.0. The code is provided "as is",
without warranty of any kind, express or implied. In no event shall the authors
"""

import logging
import os
import sys
from pathlib import Path


def ensure_not_root():
    """
    Refuse to continue if the current process is running as root, either
    directly or via sudo. This tool creates files (logs, and data inserted
    into the database) that must remain owned by the observing account, and
    elevated privileges are never required to run it.
    """
    is_root = hasattr(os, "geteuid") and os.geteuid() == 0
    ran_via_sudo = "SUDO_USER" in os.environ or "SUDO_UID" in os.environ

    if is_root or ran_via_sudo:
        sys.stderr.write(
            "lnapgdb: refusing to run as root or via sudo. "
            "Please run this tool as a regular, non-privileged user.\n"
        )
        sys.exit(1)


def get_log_dir():
    """
    Return the directory where lnapgdb log files should be written, creating
    it if it does not already exist. Logs must never be written inside the
    installed package directory, so this always resolves to a ``logs``
    folder in the home directory of the user running the code.
    """
    log_dir = Path.home() / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    return log_dir


def setup_logging(
        logger_name="lnapgdb",
        verbose=False,
        logfile=None,
        loglevel=logging.INFO
):
    """
    Configures and returns a logger instance.

    Args:
        logger_name (str): The name of the logger (defaults to the root project name).
        verbose (bool): If True, uses the provided loglevel. If False, defaults to WARNING.
        logfile (str): Optional path to a file to write logs to.
        loglevel (int): The base logging level (e.g., logging.INFO, logging.DEBUG).
    """
    ensure_not_root()

    # 1. Use a project-specific name instead of __name__
    logger = logging.getLogger(logger_name)

    # 2. Prevent duplicate handlers if this function is called multiple times
    if logger.hasHandlers():
        logger.handlers.clear()

    # Determine the effective level
    effective_level = loglevel if verbose else logging.WARNING
    logger.setLevel(effective_level)

    # 3. Create a unified formatter
    formatter = logging.Formatter(
        '%(asctime)s [%(levelname)s] @%(module)s.%(funcName)s() %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )

    # 4. ALWAYS output to the console (StreamHandler)
    ch = logging.StreamHandler(sys.stdout)
    ch.setLevel(effective_level)
    ch.setFormatter(formatter)
    logger.addHandler(ch)

    # 5. IN ADDITION, output to a file if provided
    if logfile:
        fh = logging.FileHandler(logfile)
        fh.setLevel(effective_level)
        fh.setFormatter(formatter)
        logger.addHandler(fh)

    # Prevent logs from bubbling up to the root logger and printing twice
    logger.propagate = False

    return logger
