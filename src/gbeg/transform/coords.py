"""Location normalisation.

Sources publish locations as OS grid references ("SJ 838 980"), eastings/northings, or
latitude/longitude. Everything is normalised to OSGB36 easting/northing (EPSG:27700),
with WGS84 derived from it.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache

from pyproj import Transformer

# Bounding box of the OS National Grid, used to reject impossible coordinates.
GB_EASTING_RANGE = (0, 700_000)
GB_NORTHING_RANGE = (0, 1_300_000)

_GRID_REF = re.compile(r"^([A-HJ-Z]{2})\s*(\d+)\s*(\d*)$")


class InvalidLocationError(ValueError):
    """Raised when a location cannot be parsed or lies outside Great Britain."""


@dataclass(frozen=True)
class Location:
    easting: int
    northing: int
    latitude: float
    longitude: float


def _letter_index(letter: str) -> int:
    """Index of a grid letter in the 25-letter alphabet that omits I."""
    idx = ord(letter) - ord("A")
    return idx - 1 if idx > 7 else idx


def grid_ref_to_en(grid_ref: str) -> tuple[int, int]:
    """Convert an OS grid reference such as 'SJ 838 980' to (easting, northing).

    Accepts 2 to 10 digits, with or without spaces. The returned point is the south-west
    corner of the referenced square, which is the OS convention.
    """
    cleaned = grid_ref.strip().upper()
    match = _GRID_REF.match(cleaned)
    if not match:
        raise InvalidLocationError(f"Not an OS grid reference: {grid_ref!r}")

    letters, part1, part2 = match.groups()
    digits = part1 + part2
    if len(digits) % 2 or not 2 <= len(digits) <= 10:
        raise InvalidLocationError(f"Grid reference needs an even number of digits: {grid_ref!r}")

    l1, l2 = _letter_index(letters[0]), _letter_index(letters[1])
    e100km = ((l1 - 2) % 5) * 5 + (l2 % 5)
    n100km = (19 - (l1 // 5) * 5) - (l2 // 5)

    half = len(digits) // 2
    e_digits = digits[:half].ljust(5, "0")
    n_digits = digits[half:].ljust(5, "0")

    easting = e100km * 100_000 + int(e_digits)
    northing = n100km * 100_000 + int(n_digits)
    _check_in_gb(easting, northing, grid_ref)
    return easting, northing


def _check_in_gb(easting: float, northing: float, original: object) -> None:
    if not (GB_EASTING_RANGE[0] <= easting <= GB_EASTING_RANGE[1]) or not (
        GB_NORTHING_RANGE[0] <= northing <= GB_NORTHING_RANGE[1]
    ):
        raise InvalidLocationError(f"Location outside the OS National Grid: {original!r}")


@lru_cache(maxsize=1)
def _to_wgs84() -> Transformer:
    return Transformer.from_crs("EPSG:27700", "EPSG:4326", always_xy=True)


@lru_cache(maxsize=1)
def _to_osgb() -> Transformer:
    return Transformer.from_crs("EPSG:4326", "EPSG:27700", always_xy=True)


def from_en(easting: float, northing: float) -> Location:
    _check_in_gb(easting, northing, (easting, northing))
    lon, lat = _to_wgs84().transform(easting, northing)
    return Location(round(easting), round(northing), round(lat, 6), round(lon, 6))


def from_latlon(latitude: float, longitude: float) -> Location:
    if not (49.0 <= latitude <= 61.5 and -9.0 <= longitude <= 2.5):
        raise InvalidLocationError(f"Lat/lon outside Great Britain: {(latitude, longitude)!r}")
    easting, northing = _to_osgb().transform(longitude, latitude)
    return from_en(easting, northing)


def from_grid_ref(grid_ref: str) -> Location:
    return from_en(*grid_ref_to_en(grid_ref))
