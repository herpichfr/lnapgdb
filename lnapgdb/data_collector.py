#!/usr/bin/env python3
"""
This module collect the header information of a list of raw files, validate
the values against the data model defined in model.py, and format the data as
a pandas table to be used for insertion into the database.
"""

import os
import glob
import argparse
import logging
import datetime
import json
from concurrent.futures import ProcessPoolExecutor
from functools import partial

import pandas as pd
from astropy.io import fits

try:
    from .log_utils import setup_logging, get_log_dir, ensure_not_root
    from .coords import ra_to_degrees, dec_to_degrees, angle_to_degrees
except ImportError:
    # Allow running this file directly without the package having been
    # installed, by putting the repo root on sys.path and importing lnapgdb
    # as a regular top-level package instead.
    import sys
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from lnapgdb.log_utils import setup_logging, get_log_dir, ensure_not_root
    from lnapgdb.coords import ra_to_degrees, dec_to_degrees, angle_to_degrees

logger = logging.getLogger("lnapgdb")


def parse_args():
    parser = argparse.ArgumentParser(
        description="Collect and validate FITS header data for database insertion.")
    # Added nargs='+' to safely handle both quoted glob patterns and shell-expanded file lists
    parser.add_argument(
        '--fits_files', '-f', nargs='+', required=True,
        help="List of FITS files or a glob pattern (e.g., '*.fits').")
    parser.add_argument(
        '--db_schema', '-s', default=None,
        help="Database schema to use (default: dev).")
    parser.add_argument(
        '--nprocs', '-n', type=int, default=4,
        help="Number of parallel processes to use (default: 4).")
    parser.add_argument(
        '--verbose', '-v', action='store_true',
        help="Enable verbose logging.")
    parser.add_argument(
        '--logfile', '-l', default=str(get_log_dir() / 'data_collection.log'),
        help="Log file path (default: <home>/logs/data_collection.log).")
    parser.add_argument(
        '--debug', action='store_true',
        help="Run in test mode with limited files for quick testing.")
    return parser.parse_args()


# NOTE: Shared datatype-coercion machinery used by both get_allowed_values()
# and _validate_value() below, so the primary and instrument branches of
# validate_data() parse and coerce values identically instead of drifting
# apart (as the two branches previously did).
_DATATYPE_MAPPING = {
    'string': str,
    'integer': int,
    'float': float,
    'boolean': bool
}


def _resolve_datatype(col_model):
    """Look up the Python type for a column's declared JSON 'datatype'."""
    datatype = col_model.get('datatype', None)
    return _DATATYPE_MAPPING.get(datatype.lower(), str) if datatype else str


def _coerce_bool(value):
    """
    Coerce a header value to a proper bool.

    # NOTE: Python's bool(x) is a truthiness cast, not a parse: bool('F')
    # is True because a non-empty string is truthy. Parse common FITS
    # logical spellings explicitly instead. Raises ValueError if the value
    # cannot be interpreted as a boolean.
    """
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        text = value.strip().lower()
        if text in ('t', 'true', '1', 'yes'):
            return True
        if text in ('f', 'false', '0', 'no'):
            return False
    raise ValueError(f"Cannot coerce {value!r} to boolean.")


def _coerce_value(value, datatype):
    """
    Coerce ``value`` to ``datatype``, raising (ValueError, TypeError) on
    failure. Both exceptions are caught the same way by every caller.
    """
    if datatype == bool:
        return _coerce_bool(value)
    return datatype(value)


def _is_absent(value):
    """
    True when a header value (or a model's declared default) means "no
    value" rather than a genuine, coercible one: ``None``, an undefined
    FITS card, or a blank/whitespace-only string.

    # NOTE: FITS writes '' or an undefined card when a keyword could not be
    # filled in. An undefined card comes back from astropy as a
    # fits.card.Undefined instance -- str(value) on one is '', but it is
    # not a str, so it must be checked for explicitly and not left to the
    # str.strip() branch below to catch.
    """
    if value is None:
        return True
    if isinstance(value, fits.card.Undefined):
        return True
    if isinstance(value, str) and not value.strip():
        return True
    return False


def _default_for(key, col_model, logger):
    """
    Resolve a column's declared 'default_value' to its column datatype.

    Returns (True, coerced_default) when the model declares a usable,
    non-blank default, or (False, None) when there is no default, the
    declared default is itself blank (treated as "no default declared"),
    or the default itself cannot be coerced (logged once as a WARNING;
    never raises).
    """
    default_value = col_model.get('default_value', None)
    if _is_absent(default_value):
        return False, None

    datatype = _resolve_datatype(col_model)
    try:
        return True, _coerce_value(default_value, datatype)
    except (ValueError, TypeError):
        logger.warning(
            f"Key '{key}' has default value '{default_value}' which cannot "
            f"be converted to datatype '{datatype.__name__}'; treating as "
            f"absent."
        )
        return False, None


def _validate_value(key, value, model, logger):
    """
    Validate and coerce a single header value against its column model.

    `model` is either the primary or the instrument column-keyed dict, so
    this one helper backs both branches of validate_data() -- they must
    behave identically apart from which dict they write the result into.
    Column entries may be either shape (the raw JSON dict used by the
    primary model, or the normalised dict used by the instrument model);
    only .get() is used below, never indexing, so both work.

    Returns (ok, value):
      - ok is False only when the column is non-nullable and the value
        cannot be salvaged (missing, blank, uncoercible, or violating a
        constraint, with no usable default); the caller must fail the
        file in that case.
      - ok is True otherwise, and value is what the caller should store
        for that column -- the coerced value, None (nulled), or a
        coerced default.
    """
    col_model = model.get(key, {})
    is_nullable = col_model.get('nullable', True)
    default_value = col_model.get('default_value', None)
    allowed_values, datatype, minmax = DataCollector.get_allowed_values(
        model, key, logger)

    def _fallback(reason):
        """No usable value for `key`: apply the default, null it, or fail."""
        has_default, coerced_default = _default_for(key, col_model, logger)
        if has_default:
            logger.warning(
                f"Key '{key}' {reason}; substituting default value "
                f"'{default_value}'."
            )
            return True, coerced_default
        if is_nullable:
            logger.warning(f"Key '{key}' {reason}; setting value to None.")
            return True, None
        logger.critical(
            f"Key '{key}' {reason} and the column is not nullable.")
        return False, None

    # NOTE: A None value, an undefined FITS card (fits.card.Undefined), or
    # a blank/whitespace-only string all mean the instrument left this
    # keyword unfilled, and must stay absent (None, or be defaulted) rather
    # than reach datatype coercion below -- str(None) would otherwise
    # produce the string 'None', and '' coerces cleanly to '' on a string
    # column instead of being nulled. This is a normal condition, not a
    # conversion failure, so it is routed to _fallback() without an ERROR
    # logged above it (_fallback() logs its own WARNING/CRITICAL).
    if _is_absent(value):
        return _fallback("has a blank or missing value")

    try:
        coerced = _coerce_value(value, datatype)
    except (ValueError, TypeError) as e:
        # NOTE: OBSLAT/OBSLONG may be recorded as sexagesimal strings that
        # the direct numeric cast can't parse at all. Try that reading
        # before giving up, and keep the ORIGINAL header value if it's
        # within range -- primary_data stores what the header said, not
        # the parsed decimal-degree value.
        if key in ("OBSLAT", "OBSLONG") and minmax:
            # NOTE: angle_to_degrees(), not dms_to_decimal(), so the model's
            # own allowed_values bounds decide the range (e.g. OBSLONG's
            # -180..180) instead of coords.py's declination-only +/-90
            # clamp silently nulling a valid longitude east/west of +/-90.
            angle_value = angle_to_degrees(value)
            if angle_value is not None and allowed_values[0] <= angle_value <= allowed_values[1]:
                logger.debug(
                    f"Key '{key}' has sexagesimal value '{value}' which "
                    f"converts to {angle_value}, within the allowed range: "
                    f"{allowed_values[0]} - {allowed_values[1]}."
                )
                return True, value
        logger.error(
            f"Key '{key}' has value '{value}' which cannot be converted to "
            f"the required datatype '{datatype.__name__}'. Error: {e}"
        )
        return _fallback(
            f"has value '{value}' which cannot be converted to the "
            f"required datatype '{datatype.__name__}'"
        )

    if minmax:
        in_range = isinstance(coerced, datatype) and allowed_values[0] <= coerced <= allowed_values[1]
        if not in_range and key in ("OBSLAT", "OBSLONG"):
            # NOTE: same angle_to_degrees() fallback as above, but for a
            # value that DID cast to a number, just not one in range (e.g.
            # a DDMMSS-style value with no separators).
            angle_value = angle_to_degrees(value)
            if angle_value is not None and allowed_values[0] <= angle_value <= allowed_values[1]:
                logger.debug(
                    f"Key '{key}' has sexagesimal value '{value}' which "
                    f"converts to {angle_value}, within the allowed range: "
                    f"{allowed_values[0]} - {allowed_values[1]}."
                )
                return True, value
        if not in_range:
            logger.error(
                f"Key '{key}' has value '{coerced}' which is not within "
                f"the allowed range: {allowed_values[0]} - {allowed_values[1]}."
            )
            return _fallback(
                f"has value '{coerced}' which is outside the allowed "
                f"range: {allowed_values[0]} - {allowed_values[1]}"
            )
        logger.debug(
            f"Key '{key}' has value '{coerced}' which is within the "
            f"allowed range: {allowed_values[0]} - {allowed_values[1]}."
        )
        return True, coerced

    if allowed_values and coerced not in allowed_values:
        logger.error(
            f"Key '{key}' has value '{coerced}' which is not in the "
            f"allowed values: {allowed_values}."
        )
        return _fallback(
            f"has value '{coerced}' which is not in the allowed values: "
            f"{allowed_values}"
        )

    logger.debug(
        f"Key '{key}' has value '{coerced}' which is in the allowed "
        f"values: {allowed_values}."
    )
    return True, coerced


class DataCollector:
    def __init__(self,
                 fits_files,
                 primary_model=None,
                 instrument_models_cache=None,
                 db_schema='dev',
                 nprocs=4,
                 logger=None,
                 verbose=False,
                 logfile=None,
                 config=None,
                failed_files_log=None,
                 debug=False
                 ):
        self.fits_files = fits_files
        self.db_schema = db_schema
        self.nprocs = nprocs
        self.debug = debug
        self.config = config or {}
        self.failed_files_log = failed_files_log or str(
            get_log_dir() / 'failed_fits.log')
        self.primary_model = primary_model
        self.instrument_models_cache = instrument_models_cache or {}
        self.logger = logger or setup_logging(
            logfile=logfile or str(get_log_dir() / 'data_collection.log'),
            verbose=verbose)
        self.error_log_file = str(get_log_dir() / 'failed_fits.log')

        # 1. Define where models should live relative to this script
        self.root_dir = os.path.dirname(
            os.path.dirname(os.path.abspath(__file__)))
        self.models_dir = os.path.join(self.root_dir, 'models')

        self.primary_model = primary_model

        # 3. Fallback for instrument models
        if instrument_models_cache is None:
            self.instrument_models_cache = {}
        else:
            self.instrument_models_cache = instrument_models_cache

    def __repr__(self):
        return f"DataCollector(fits_files='{self.fits_files}', db_schema='{self.db_schema}', nprocs={self.nprocs}, debug={self.debug})"

    @staticmethod
    def default_service_nprocs(fraction=0.8):
        """
        Number of worker processes to use for unattended (service) data
        collection: roughly `fraction` of the CPUs actually available to
        this process, with a floor of 1. Prefers the CPU affinity mask
        (accurate under cgroup/container CPU limits) and falls back to the
        total CPU count if that isn't available on this platform.
        """
        try:
            cpu_count = len(os.sched_getaffinity(0))
        except (AttributeError, NotImplementedError):
            cpu_count = os.cpu_count() or 1

        return max(1, int(cpu_count * fraction))

    @staticmethod
    def get_instrument_model(instrument_name, instrument_models_cache=None):
        """Retrieve instrument model from cache or fall back to loading from disk."""
        if not instrument_name:
            return {}

        # 1. Check cache first if provided
        if instrument_models_cache and instrument_name in instrument_models_cache:
            return instrument_models_cache[instrument_name]

        # 2. Disk fallback
        models_dir = os.path.join(os.path.dirname(os.path.dirname(
            os.path.abspath(__file__))), 'models')
        instrument_json = os.path.join(models_dir, f"{instrument_name}.json")

        instrument_model_dict = {}
        if os.path.exists(instrument_json):
            with open(instrument_json, 'r') as f:
                instrument_model_mapping = json.load(f)
                for col in instrument_model_mapping:
                    colname = col['colname']
                    instrument_model_dict[colname] = {
                        'datatype': col.get('datatype', None),
                        'nullable': col.get('nullable', True),
                        'allowed_values': col.get('allowed_values', None),
                        'default_value': col.get('default_value', None),
                        'description': col.get('description', '')
                    }

            # Update cache if available
            if instrument_models_cache is not None:
                instrument_models_cache[instrument_name] = instrument_model_dict

        return instrument_model_dict

    @staticmethod
    def get_primary_model(primary_model=None):
        """Retrieve primary table model or fall back to loading primary_table.json."""
        if primary_model:
            return primary_model

        models_dir = os.path.join(os.path.dirname(os.path.dirname(
            os.path.abspath(__file__))), 'models')
        primary_json = os.path.join(models_dir, "primary_table.json")

        primary_model_dict = {}
        if os.path.exists(primary_json):
            with open(primary_json, 'r') as f:
                primary_model_mapping = json.load(f)
                for col in primary_model_mapping:
                    colname = col['colname']
                    primary_model_dict[colname] = col

        return primary_model_dict

    @staticmethod
    def process_file(
            file,
            primary_model=None,
            instrument_models_cache=None,
            logger=logging.getLogger(__name__)
    ):
        """
        Process a single FITS file: extract header, validate, and return data.
        """

        logger.debug(f"Processing file: {file}")
        raw_full_filename = os.path.abspath(file)

        try:
            with fits.open(file, checksum=True) as hdul:
                header = hdul[0].header
        except Exception as e:
            logger.error(f"Error opening file '{file}': {e}")
            return {
                'error': True,
                'file': file,
                'instrument_name': None
            }

        if not primary_model:
            # Load fallback primary model if not provided
            primary_model = DataCollector.get_primary_model()

        instrument = header.get('INSTRUME', None).lower(
        ) if header.get('INSTRUME', None) else None

        if instrument is None:
            logger.critical(
                f"File '{file}' is missing 'INSTRUME' keyword in header.")
            return {
                'error': True,
                'file': file,
                'instrument_name': None
            }

        if instrument not in instrument_models_cache:
            # Try to load the instrument model if it's not already cached
            instrument_model = DataCollector.get_instrument_model(
                instrument_name=instrument)
            if instrument_model:
                instrument_models_cache[instrument] = instrument_model
            else:
                logger.critical(
                    f"File '{file}' has unknown instrument '{instrument}' in header.")
                return {
                    'error': True,
                    'file': file,
                    'instrument_name': instrument
                }
        else:
            instrument_model = instrument_models_cache.get(instrument, None)

        is_valid, primary_data, instrument_data = DataCollector.validate_data(
            header, primary_model, instrument_model, logger)

        # NOTE: Add out-of-model raw_path to the primary data. This needs to
        # happen here to garantee that the path is associated with the correct file
        primary_data['raw_path'] = raw_full_filename

        # NOTE: Derive numeric decimal-degree coordinates from the raw
        # RA/DEC header strings for indexed positional queries. Read from
        # header (not primary_data) so they're populated even if validation
        # dropped RA/DEC, and assign both keys unconditionally (including
        # None) so every record in the batch carries the same columns.
        ra_raw = header.get('RA')
        dec_raw = header.get('DEC')
        primary_data['ra_deg'] = ra_to_degrees(ra_raw)
        primary_data['dec_deg'] = dec_to_degrees(dec_raw)
        if ra_raw not in (None, '') and primary_data['ra_deg'] is None:
            logger.warning(
                f"File '{file}' has RA '{ra_raw}' which could not be "
                f"converted to decimal degrees.")
        if dec_raw not in (None, '') and primary_data['dec_deg'] is None:
            logger.warning(
                f"File '{file}' has DEC '{dec_raw}' which could not be "
                f"converted to decimal degrees.")

        if is_valid:
            logger.debug(f"File '{file}' passed validation successfully.")
            return {
                'primary': primary_data,
                'instrument': instrument_data,
                'instrument_name': instrument,
                'file': file
            }
        else:  # NOTE:
            logger.error(
                f"File '{file}' failed validation and will be skipped.")
            return {
                'error': True,
                'file': file,
                'instrument_name': instrument if 'instrument' in locals() else None
            }

    def collect_data(self):
        """Collect and validate FITS header data for database insertion."""
        new_fits_files = self.fits_files
        if not new_fits_files:
            return pd.DataFrame(), pd.DataFrame()  # Return empty DataFrames if no new files

        worker = partial(self.process_file,
                         primary_model=self.primary_model,
                         instrument_models_cache=self.instrument_models_cache,
                         logger=self.logger)

        if self.debug or len(new_fits_files) < self.nprocs or self.nprocs <= 1:
            self.logger.warning(
                "Debug mode enabled or not enough files for parallel processing. Processing sequentially.")
            data = [worker(file) for file in new_fits_files]
        else:
            self.logger.info(f"Processing {len(new_fits_files)} files using {
                             self.nprocs} parallel processes.")
            try:
                with ProcessPoolExecutor(max_workers=self.nprocs) as executor:
                    data = list(executor.map(worker, new_fits_files))
            except Exception as e:
                self.logger.warning(
                    f"Parallel processing with {self.nprocs} processes failed "
                    f"({e}). Falling back to single-file (sequential) processing."
                )
                data = [worker(file) for file in new_fits_files]

        # NOTE: Save the filenames that failed validation for later review
        valid_data = [d for d in data if d and not d.get('error')]
        failed_data = [d for d in data if d and d.get('error')]
        self.logger.info(f"Successfully processed {len(valid_data)} files.")

        failed_dirs = {}
        if self.config:
            data_root = self.config.get("data_root", "")
            instruments = self.config.get("instruments", {})

            for name, inst_data in instruments.items():
                failed_dir = os.path.expandvars(
                    inst_data.get("failed_directory", ""))
                if failed_dir:
                    full_path = os.path.join(data_root, failed_dir)
                    failed_dirs[name.lower()] = full_path

        # Categorize errors by instrument
        failed_by_instrument = {}
        for item in failed_data:
            inst = item.get('instrument_name') or 'unknown'
            failed_by_instrument.setdefault(inst, []).append(item['file'])

        # Save in the correct directory
        for inst, files in failed_by_instrument.items():
            failed_dir = failed_dirs.get(inst)
            if not failed_dir:
                if self.config:
                    failed_dir = os.path.join(self.config.get(
                        "data_root", ""), "unknown/failed")
                else:
                    failed_dir = str(get_log_dir() / "unknown_failed")

            try:
                os.makedirs(failed_dir, exist_ok=True)
                log_path = os.path.join(failed_dir, "failed_fits.log")

                with open(log_path, "a") as f:
                    for file in files:
                        f.write(f"{datetime.datetime.now()} - {file}\n")
                self.logger.info(f"Saved failed files log to: {log_path}")
            except OSError as e:
                # The configured failed-files directory couldn't be created
                # or written to (e.g. an unresolved/invalid env var, or a
                # permissions issue on the mount). Don't reject the
                # ingestion over a logging problem: fall back to a
                # temporary local log inside this project's tmp/ directory.
                fallback_dir = os.path.join(self.root_dir, "tmp")
                fallback_log_path = os.path.join(
                    fallback_dir, f"failed_fits_{inst}.log")

                self.logger.warning(
                    f"Could not write failed files log to '{failed_dir}' "
                    f"({e}). Creating a temporary local log instead at: "
                    f"{fallback_log_path}"
                )

                os.makedirs(fallback_dir, exist_ok=True)
                with open(fallback_log_path, "a") as f:
                    for file in files:
                        f.write(f"{datetime.datetime.now()} - {file}\n")

        # Transform the list of dictionaries into two pandas DataFrames
        if not valid_data:
            return pd.DataFrame(), pd.DataFrame()

        primary_df = pd.DataFrame([d['primary'] for d in valid_data])
        instrument_df = pd.DataFrame([d['instrument'] for d in valid_data])

        return primary_df, instrument_df

    @staticmethod
    def dms_to_decimal(dms_str):
        """Convert DMS (Degrees, Minutes, Seconds) string to decimal degrees."""
        # NOTE: Thin delegate over lnapgdb.coords.dec_to_degrees, which fixes
        # the sign bug this used to have (the leading '-' only applied to the
        # degrees field, so '-22:32:04' became -21.466 instead of -22.534)
        # and never raises.
        return dec_to_degrees(dms_str)

    @staticmethod
    def validate_data(
            header_data,
            primary_model,
            instrument_model,
            logger=logging.getLogger(__name__)
    ):
        """Validate header data against primary and instrument models."""
        primary_data = {}
        instrument_data = {}

        for key, value in header_data.items():
            if key in primary_model:
                ok, result = _validate_value(key, value, primary_model, logger)
                if not ok:
                    return False, primary_data, instrument_data
                primary_data[key] = result

            elif key in instrument_model:
                ok, result = _validate_value(
                    key, value, instrument_model, logger)
                if not ok:
                    return False, primary_data, instrument_data
                instrument_data[key] = result
            else:
                logger.warning(
                    f"Key '{key}' is not defined in either the primary model or "
                    f"the instrument model and will be ignored."
                )

        # NOTE: Apply model-declared defaults for columns that never showed
        # up in the header at all (as opposed to showing up with a value
        # that got nulled -- that case is already handled above, inside
        # _validate_value). This runs before the required-columns check
        # below, so a non-nullable column satisfied by its default isn't
        # reported as missing.
        for key, col_model in primary_model.items():
            if key not in primary_data:
                has_default, coerced_default = _default_for(
                    key, col_model, logger)
                if has_default:
                    logger.warning(
                        f"Key '{key}' is missing from the header data; "
                        f"substituting default value "
                        f"'{col_model.get('default_value')}'."
                    )
                    primary_data[key] = coerced_default

        for key, col_model in instrument_model.items():
            if key not in instrument_data:
                has_default, coerced_default = _default_for(
                    key, col_model, logger)
                if has_default:
                    logger.warning(
                        f"Key '{key}' is missing from the header data; "
                        f"substituting default value "
                        f"'{col_model.get('default_value')}'."
                    )
                    instrument_data[key] = coerced_default

        # NOTE: Loop through the primary model and instrument model to check if
        # there are any required keys that are missing in the header data
        for key, value in primary_model.items():
            if not value.get('nullable', True) and key not in primary_data:
                logger.critical(
                    f"Key '{key}' is required in the primary model but is missing in the header data.")
                return False, primary_data, instrument_data

        for key, value in instrument_model.items():
            if not value.get('nullable', True) and key not in instrument_data:
                logger.critical(f"Key '{
                                key}' is required in the instrument model but is missing in the header data.")
                return False, primary_data, instrument_data

        logger.info("Header data validation successful.")
        return True, primary_data, instrument_data

    @staticmethod
    def get_allowed_values(data_model, key, logger=logger):
        """
        Resolve a column's allowed-values constraint into a uniform shape.

        Returns (allowed_values, datatype, minmax):
          - minmax=True: allowed_values is a (min, max) tuple, both coerced
            to `datatype` ('inf'/'-inf' become float infinities).
          - minmax=False: allowed_values is either None (unconstrained) or
            a list of enumerated values coerced to `datatype`; elements
            that fail to coerce are dropped (logged as a WARNING) rather
            than raising.

        `data_model` may be either the raw per-column JSON dict (primary
        model) or the normalised instrument-model dict; only .get() is
        used, so both work.

        `logger` defaults to this module's own logger so the two-positional
        call form (as used before this parameter existed) keeps working;
        pass the caller's logger so these WARNINGs land in the same sink as
        the rest of a file's validation diagnostics.
        """
        col_model = data_model.get(key, {})
        datatype = _resolve_datatype(col_model)

        # NOTE: A boolean column's allowed set is always {True, False}.
        # The JSON encodes this redundantly as the string 'true,false';
        # ignore it rather than intersecting with it.
        if datatype == bool:
            return [True, False], datatype, False

        allowed_values = col_model.get('allowed_values', None)
        if allowed_values is None:
            return None, datatype, False

        # NOTE: case-insensitive *prefix* test, not the previous substring
        # test, so an enumerated value that happens to contain the letters
        # "range" isn't misparsed as a bound.
        if allowed_values.strip().lower().startswith('range:'):
            bound_str = allowed_values.split(':', 1)[1]
            parts = [p.strip() for p in bound_str.split(',')]
            if len(parts) != 2:
                logger.warning(
                    f"Key '{key}' has a malformed range specification "
                    f"'{allowed_values}'; treating as unconstrained."
                )
                return None, datatype, False

            min_val, max_val = parts
            # NOTE: A malformed bound (a model-file typo, e.g. a
            # non-numeric or fractional value on an integer column) must
            # degrade the same way the len(parts) != 2 case above does,
            # not raise out of a ProcessPoolExecutor worker.
            try:
                min_val = float('-inf') if 'inf' in min_val.lower(
                ) else _coerce_value(min_val, datatype)
                max_val = float('inf') if 'inf' in max_val.lower(
                ) else _coerce_value(max_val, datatype)
            except (ValueError, TypeError):
                logger.warning(
                    f"Key '{key}' has a range specification "
                    f"'{allowed_values}' whose bounds cannot be converted "
                    f"to datatype '{datatype.__name__}'; treating as "
                    f"unconstrained."
                )
                return None, datatype, False

            return (min_val, max_val), datatype, True

        # NOTE: Enumerated allowed_values were previously compared as raw
        # strings against an already-coerced value (e.g. '1' vs int 1),
        # which rejected every legal value for non-string columns. Coerce
        # each element (after stripping whitespace) to the column's
        # datatype instead; an element that won't coerce is dropped with a
        # WARNING rather than raising.
        raw_items = [item.strip() for item in allowed_values.split(',')]
        coerced_items = []
        for item in raw_items:
            try:
                coerced_items.append(_coerce_value(item, datatype))
            except (ValueError, TypeError):
                logger.warning(
                    f"Key '{key}' has an enumerated allowed value '{item}' "
                    f"which cannot be converted to datatype "
                    f"'{datatype.__name__}' and will be dropped."
                )

        allowed_values = coerced_items if coerced_items else None
        return allowed_values, datatype, False


def main():
    ensure_not_root()

    args = parse_args()

    # Collect files properly handling shell expansion and glob lists
    raw_files = []
    for pattern in args.fits_files:
        raw_files.extend(glob.glob(pattern))

    fits_files = raw_files[:10] if args.debug else raw_files

    collector = DataCollector(
        fits_files=fits_files,
        db_schema=args.db_schema,
        nprocs=args.nprocs,
        verbose=args.verbose,
        logfile=args.logfile,
        debug=args.debug
    )

    # Correctly unpack the two DataFrames returned by collect_data
    primary_df, instrument_df = collector.collect_data()


if __name__ == "__main__":
    main()
