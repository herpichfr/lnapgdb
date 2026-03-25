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


def setup_logging(verbose=False, logfile=None, loglevel=logging.INFO):
    logger = logging.getLogger(__name__)
    logger.setLevel(loglevel if verbose else logging.WARNING)

    formatter = logging.Formatter(
        '%(asctime)s [%(levelname)s] @%(module)s.%(funcName)s() %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S')

    if logfile:
        fh = logging.FileHandler(logfile)
        fh.setLevel(loglevel)
        fh.setFormatter(formatter)
        logger.addHandler(fh)
    else:
        ch = logging.StreamHandler()
        ch.setLevel(loglevel)
        ch.setFormatter(formatter)
        logger.addHandler(ch)
    return logger
