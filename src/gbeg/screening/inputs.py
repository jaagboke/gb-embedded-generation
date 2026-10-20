"""Read a user's site list and work out where each site is.

People's spreadsheets differ, so columns are matched by loose name patterns, and a single
"location" column may hold a postcode, a grid reference, "easting, northing" or
"latitude, longitude" on different rows. Every row gets either a location or a reason why
it has none; nothing is silently dropped.
"""

from __future__ import annotations

import io
import re
from collections.abc import Callable
from dataclasses import dataclass, field

import pandas as pd

from gbeg.transform.coords import InvalidLocationError, from_en, from_grid_ref, from_latlon

ROLE_PATTERNS: dict[str, list[str]] = {
    "name": [r"^site( name)?$", r"^name$", r"site name", r"^location name$", r"^site id$",
             r"^id$", r"^ref(erence)?$", r"description"],
    "postcode": [r"post ?code", r"^pc$"],
    "gridref": [r"grid ?ref", r"^ngr$", r"os ref", r"national grid"],
    "easting": [r"^east(ing)?s?$", r"^x$", r"x[ _-]?coord", r"easting"],
    "northing": [r"^north(ing)?s?$", r"^y$", r"y[ _-]?coord", r"northing"],
    "lat": [r"^lat(itude)?$", r"latitude"],
    "lon": [r"^lon(g|gitude)?$", r"longitude", r"^lng$"],
    "location": [r"^location$", r"^coordinates?$", r"^position$", r"^address$", r"^site location$"],
    "kva": [r"kva", r"rating", r"size", r"capacity"],
    "noise_7m": [r"noise", r"db ?\(?a\)?", r"sound"],
    "period": [r"period", r"operat", r"hours", r"day ?/ ?night"],
}

POSTCODE = re.compile(r"^([A-Z]{1,2}\d[A-Z\d]?)\s*(\d[A-Z]{2})$")
GRIDREF = re.compile(r"^[A-HJ-Z]{2}\s*\d+(\s*\d+)?$")
# A postcode inside longer text, such as an address.
POSTCODE_IN_TEXT = re.compile(r"\b([A-Z]{1,2}\d[A-Z\d]?)\s*(\d[A-Z]{2})\b")
PAIR = re.compile(r"^\s*(-?\d+(?:\.\d+)?)\s*[,;/ ]\s*(-?\d+(?:\.\d+)?)\s*$")


@dataclass
class ColumnMap:
    roles: dict[str, str] = field(default_factory=dict)

    def get(self, role: str) -> str | None:
        return self.roles.get(role)

    def describe(self) -> list[tuple[str, str]]:
        labels = {"name": "Site name", "postcode": "Postcode", "gridref": "Grid reference",
                  "easting": "Easting", "northing": "Northing", "lat": "Latitude",
                  "lon": "Longitude", "location": "Location", "kva": "Rating (kVA)",
                  "noise_7m": "Noise at 7 m", "period": "Operating period"}
        return [(labels[r], c) for r, c in self.roles.items()]


def _norm(header: object) -> str:
    return " ".join(str(header).strip().lower().replace("_", " ").split())


def read_table(data: bytes | io.BytesIO, filename: str) -> pd.DataFrame:
    """Read CSV or Excel into strings, dropping fully empty rows and columns."""
    raw = data.getvalue() if isinstance(data, io.BytesIO) else data
    if filename.lower().endswith((".xlsx", ".xlsm", ".xls")):
        df = pd.read_excel(io.BytesIO(raw), dtype=str)
    else:
        for encoding in ("utf-8-sig", "latin-1"):
            try:
                df = pd.read_csv(io.BytesIO(raw), dtype=str, encoding=encoding,
                                 sep=None, engine="python")
                break
            except UnicodeDecodeError:
                continue
    df = df.dropna(how="all").dropna(axis=1, how="all")
    df.columns = [str(c).strip() for c in df.columns]
    return df.apply(lambda s: s.str.strip() if s.dtype == object else s).reset_index(drop=True)


def detect_columns(df: pd.DataFrame) -> ColumnMap:
    """Assign each role to the first unclaimed column whose header matches its patterns."""
    roles: dict[str, str] = {}
    claimed: set[str] = set()
    for role, patterns in ROLE_PATTERNS.items():
        for pattern in patterns:
            match = next((c for c in df.columns
                          if c not in claimed and re.search(pattern, _norm(c))), None)
            if match:
                roles[role] = match
                claimed.add(match)
                break
    if "name" not in roles and len(df.columns):
        first = next((c for c in df.columns if c not in claimed), None)
        if first:
            roles["name"] = first
    return ColumnMap(roles)


def _num(value: object) -> float | None:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    text = str(value).replace(",", "").strip()
    try:
        return float(text)
    except ValueError:
        return None


@dataclass
class Located:
    easting: int | None = None
    northing: int | None = None
    latitude: float | None = None
    longitude: float | None = None
    method: str | None = None
    issue: str | None = None


def _from_pair(a: float, b: float) -> Located:
    """Decide whether a number pair is lat/lon or easting/northing."""
    if abs(a) <= 90 and abs(b) <= 180:
        lat, lon = (a, b) if 49 <= a <= 61.5 else (b, a)
        loc = from_latlon(lat, lon)
        return Located(loc.easting, loc.northing, loc.latitude, loc.longitude, "lat/long")
    loc = from_en(a, b)
    return Located(loc.easting, loc.northing, loc.latitude, loc.longitude, "easting/northing")


def parse_text_location(text: str, postcode_lookup: Callable[[str], tuple] | None) -> Located:
    cleaned = " ".join(str(text).upper().split())
    try:
        if POSTCODE.match(cleaned):
            return _postcode(cleaned, postcode_lookup)
        if GRIDREF.match(cleaned):
            loc = from_grid_ref(cleaned)
            return Located(loc.easting, loc.northing, loc.latitude, loc.longitude,
                           "grid reference")
        pair = PAIR.match(cleaned)
        if pair:
            return _from_pair(float(pair.group(1)), float(pair.group(2)))
    except InvalidLocationError as exc:
        return Located(issue=str(exc))
    return Located(issue=f"Could not read a location from “{text}”")


def _postcode(text: str, lookup) -> Located:
    match = POSTCODE.match(" ".join(text.upper().split()))
    if not match:
        return Located(issue=f"“{text}” is not a valid postcode")
    if lookup is None:
        return Located(issue="Postcode lookup not loaded; give a grid reference or coordinates")
    key = match.group(1) + match.group(2)
    found = lookup(key)
    if found is None:
        return Located(issue=f"Postcode {match.group(1)} {match.group(2)} not found")
    loc = from_en(*found)
    return Located(loc.easting, loc.northing, loc.latitude, loc.longitude, "postcode")


def locate_row(row: pd.Series, cols: ColumnMap, postcode_lookup=None,
               site_lookup=None) -> Located:
    """Try the most precise location first: coordinates, grid reference, then postcode."""
    def val(role):
        col = cols.get(role)
        if col is None:
            return None
        v = row.get(col)
        return None if v is None or (isinstance(v, float) and pd.isna(v)) or v == "" else v

    try:
        e, n = _num(val("easting")), _num(val("northing"))
        if e is not None and n is not None:
            loc = from_en(e, n)
            return Located(loc.easting, loc.northing, loc.latitude, loc.longitude,
                           "easting/northing")
        lat, lon = _num(val("lat")), _num(val("lon"))
        if lat is not None and lon is not None:
            loc = from_latlon(lat, lon)
            return Located(loc.easting, loc.northing, loc.latitude, loc.longitude, "lat/long")
        if val("gridref"):
            loc = from_grid_ref(val("gridref"))
            return Located(loc.easting, loc.northing, loc.latitude, loc.longitude,
                           "grid reference")
    except InvalidLocationError as exc:
        return Located(issue=str(exc))
    # A "location" cell may hold a site name or address rather than a location, so when it
    # cannot be read, fall back to the postcode column, then to a postcode inside the text.
    issues: list[str] = []
    if val("location"):
        found = parse_text_location(val("location"), postcode_lookup)
        if not found.issue:
            return found
        issues.append(found.issue)
    if val("postcode"):
        found = _postcode(val("postcode"), postcode_lookup)
        if not found.issue:
            return found
        issues.append(found.issue)
    if val("location"):
        embedded = POSTCODE_IN_TEXT.search(" ".join(str(val("location")).upper().split()))
        if embedded:
            found = _postcode(embedded.group(0), postcode_lookup)
            if not found.issue:
                return found
            if found.issue not in issues:
                issues.append(found.issue)
    # Last resort: the site name (or the Location text) may be a known SPEN substation.
    if site_lookup is not None:
        for text in (val("name"), val("location")):
            found = site_lookup(str(text)) if text else None
            if isinstance(found, str):   # the name fits several substations
                issues.append(found)
                break
            if found:
                loc = from_en(found[0], found[1])
                return Located(loc.easting, loc.northing, loc.latitude, loc.longitude,
                               f"SPEN substation ({found[2]})")
        if val("name") and not issues:
            issues.append("No location given, and the name is not an SPEN substation")
    return Located(issue="; ".join(issues) or "No location given")


# Columns of the "add sites by hand" table, and the role each one fills.
EXTRA_SITE_FIELDS: dict[str, str] = {
    "Site name": "name",
    "Location": "location",
    "Generator rating (kVA)": "kva",
    "Noise at 7 m dB(A)": "noise_7m",
    "Operating period": "period",
}


def add_sites(sites: pd.DataFrame, cols: ColumnMap,
              extra: pd.DataFrame) -> tuple[pd.DataFrame, ColumnMap]:
    """Append typed-in sites (columns as in EXTRA_SITE_FIELDS) to an uploaded site list.

    Each value goes into the file's column for that role. If the file has no column for a
    role (often "location", when the file uses eastings and northings), a new column is
    added; it stays empty for the file's own rows, so they are located as before.
    """
    extra = extra.reindex(columns=list(EXTRA_SITE_FIELDS)).astype(object)
    extra = extra.where(extra.notna() & (extra.astype(str).apply(lambda s: s.str.strip()) != ""))
    extra = extra.dropna(how="all")
    if extra.empty:
        return sites, cols

    roles = dict(cols.roles)
    sites = sites.copy()
    rows = pd.DataFrame(index=range(len(extra)), columns=sites.columns, dtype=object)
    for label, role in EXTRA_SITE_FIELDS.items():
        values = extra[label].map(lambda v: None if pd.isna(v) else str(v).strip()).tolist()
        if all(v is None for v in values):
            continue
        target = roles.get(role)
        if target is None:
            target = label
            while target in sites.columns:
                target += " (added)"
            sites[target] = None
            rows[target] = None
            roles[role] = target
        rows[target] = values
    combined = pd.concat([sites, rows], ignore_index=True)
    return combined, ColumnMap(roles)
