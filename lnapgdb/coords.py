#!/bin/python3

"""
This module provides the shared coordinate-conversion helpers used by both
data_collector.py (ingestion) and model.py (backfill) to derive decimal
degree values from the raw RA/DEC strings stored in FITS headers.
Right ascension is conventionally recorded either as sexagesimal hours
('HH:MM:SS.ss') or as a bare number already in decimal degrees; declination
is always degrees, either sexagesimal ('+/-DD:MM:SS.ss') or bare. A third
helper, angle_to_degrees(), does the same degrees parsing with no range
restriction at all, for angles (e.g. a site longitude) whose valid range is
a model concern rather than this module's. All three public functions are
total: they never raise and return None for anything they cannot
confidently convert, so that a bad or missing coordinate never turns a
valid file into a failed one.

Copyright (c) 2025, LNA DB Team. All rights reserved.

This code is licensed under the LNA License v1.0. The code is provided "as is",
without warranty of any kind, express or implied. In no event shall the authors
or copyright holders be liable for any claim, damages or other liability,
whether in an action of contract, tort or otherwise, arising from, out of or in
connection with the code or the use or other dealings in the code.
"""

import math

# NOTE: Sentinel strings observed (or plausible) in FITS headers for a
# missing pointing. Compared case-insensitively.
_SENTINELS = {'', 'n/a', 'unknown', '---'}


def _parse_sexagesimal(text):
    """
    Parse a sexagesimal 'sign D:M:S' (colon- or space-separated) string
    into a signed decimal value, with no unit conversion applied.

    Returns None if the string is not 2 or 3 numeric fields.
    """
    # NOTE: The leading sign must apply to the whole value, not just the
    # first (degrees) field, otherwise e.g. '-22:32:04' is mis-converted to
    # -21.466 (degrees negative, minutes/seconds added back in positive)
    # instead of the correct -22.534.
    sign = 1.0
    if text[:1] in ('+', '-'):
        if text[0] == '-':
            sign = -1.0
        text = text[1:]

    parts = text.split(':') if ':' in text else text.split()
    parts = [p for p in parts if p]
    if len(parts) not in (2, 3):
        return None

    try:
        fields = [float(p) for p in parts]
    except ValueError:
        return None

    degrees, minutes = fields[0], fields[1]
    seconds = fields[2] if len(fields) == 3 else 0.0
    return sign * (degrees + minutes / 60.0 + seconds / 3600.0)


def _to_degrees(value, is_ra, clamp=True):
    """
    Shared conversion core for ra_to_degrees()/dec_to_degrees()/
    angle_to_degrees(). Never raises; returns None for anything it cannot
    convert.

    `is_ra` selects hours-to-degrees (x15) plus modulo-360 normalisation.
    `clamp` (ignored when `is_ra` is True) selects the +/-90 rejection that
    dec_to_degrees() wants and angle_to_degrees() doesn't.
    """
    if value is None:
        return None

    if isinstance(value, (int, float)):
        degrees = float(value)
    elif isinstance(value, str):
        text = value.strip()
        if text.lower() in _SENTINELS:
            return None
        try:
            # A bare number is already decimal degrees, for both RA and DEC.
            degrees = float(text)
        except ValueError:
            if ':' in text or ' ' in text or '\t' in text:
                parsed = _parse_sexagesimal(text)
                if parsed is None:
                    return None
                # NOTE: Only a sexagesimal RA is in hours and needs the x15
                # factor; a bare number is already degrees either way.
                degrees = parsed * 15.0 if is_ra else parsed
            else:
                return None
    else:
        return None

    if not math.isfinite(degrees):
        return None

    if is_ra:
        degrees = degrees % 360.0
    elif clamp and (degrees < -90.0 or degrees > 90.0):
        return None

    return degrees


def ra_to_degrees(value):
    """
    Convert a right ascension value to decimal degrees.

    Accepts an int/float already in degrees, a string that parses as a bare
    float already in degrees, or a sexagesimal hours string ('HH:MM:SS.ss',
    colon- or space-separated), which is multiplied by 15. The result is
    normalised into [0, 360) by modulo. Returns None (never raises) for
    None, an empty string, a known sentinel, or anything that does not
    parse.
    """
    return _to_degrees(value, is_ra=True)


def dec_to_degrees(value):
    """
    Convert a declination value to decimal degrees.

    Accepts an int/float or a bare-float string already in degrees, or a
    sexagesimal '+/-DD:MM:SS.ss' string (colon- or space-separated), with
    the leading sign applied to the whole value. Returns None (never
    raises) for None, an empty string, a known sentinel, anything that does
    not parse, or a value outside [-90, +90].
    """
    return _to_degrees(value, is_ra=False)


def angle_to_degrees(value):
    """
    Convert a generic signed angle (e.g. a geographic longitude) to decimal
    degrees.

    Accepts an int/float or a bare-float string already in degrees, or a
    sexagesimal '+/-D:M:S.ss' string (colon- or space-separated), with the
    leading sign applied to the whole value -- the same parsing as
    dec_to_degrees(). Unlike dec_to_degrees(), no +/-90 range restriction
    is applied: an angle's valid range (e.g. -180..180 for a longitude) is
    the caller's (the data model's) business, not this module's. Returns
    None (never raises) for None, an empty string, a known sentinel, or
    anything that does not parse.
    """
    return _to_degrees(value, is_ra=False, clamp=False)
