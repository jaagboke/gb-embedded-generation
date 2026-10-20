"""Reference data the screening uses, each optional.

Files live in one folder (app/data/reference by default) and are produced by
`python -m gbeg.screening.prepare`:

    ruc_oa.parquet        ONS 2021 output areas: oa21cd, ruc21nm, wkb (EPSG:27700)
    addresses.parquet     OS Open UPRN points: x, y (EPSG:27700, metres)
    postcodes.parquet     OS Code-Point Open: postcode (no space), e, n
    generation.csv        existing and planned generation: name, technology, mw, status,
                          source, e, n
    spen_sites.csv        SPEN substations, for finding a site by name: name, alias, type,
                          voltage, e, n (optional; see `spen_sites_loaded`)

Missing files are reported in `available` and the related checks return None.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd

# Words that describe the kind of substation rather than which one it is.
_SITE_WORDS = frozenset(
    "substation substations sub s primary grid supply point bulk gsp bsp pss "
    "secondary distribution switching station kv the".split())
_VOLTAGE = re.compile(r"\b\d+(\.\d+)?(\s*/\s*\d+(\.\d+)?)*\s*kv\b")
_TRANSFORMER = re.compile(r"^(s?gt|t)\d+[a-z]?$")
# Abbreviations in SPEN names, expanded on both sides so either spelling matches.
_ABBREVIATIONS = {"st": "street", "rd": "road", "dv": "drive", "dr": "drive", "ave": "avenue",
                  "ln": "lane", "sq": "square", "pk": "park", "gn": "green", "grn": "green",
                  "hosp": "hospital", "nth": "north", "sth": "south", "lwr": "lower",
                  "upr": "upper", "ind": "industrial", "est": "estate", "mt": "mount"}
# Words that say which kind of substation is meant, matched against the `type` column.
_TYPE_HINTS = {"primary": "primary", "pss": "primary", "bsp": "bsp", "bulk": "bsp",
               "gsp": "gsp", "grid": "gsp"}


def site_key(name: object) -> str:
    """'HOOLE RD 33/11kV Primary S/S T1' -> 'hoole road'."""
    text = _VOLTAGE.sub(" ", str(name).lower())
    text = re.sub(r"[^a-z0-9 ]+", " ", text)
    words = (_ABBREVIATIONS.get(t, t) for t in text.split()
             if t not in _SITE_WORDS and not _TRANSFORMER.match(t))
    return " ".join(words)


def _type_hint(name: str) -> str | None:
    words = re.sub(r"[^a-z ]+", " ", name.lower()).split()
    return next((_TYPE_HINTS[w] for w in words if w in _TYPE_HINTS), None)


@dataclass
class ReferenceData:
    folder: Path
    available: dict[str, bool] = field(default_factory=dict)
    _ruc: object = None
    _ruc_names: np.ndarray | None = None
    _address_tree: object = None
    _postcodes: dict | None = None
    _generation: pd.DataFrame | None = None
    _generation_tree: object = None
    spen_sites: pd.DataFrame | None = None
    _site_index: dict | None = None

    @classmethod
    def load(cls, folder: Path) -> ReferenceData:
        ref = cls(Path(folder))
        ref._load_ruc()
        ref._load_addresses()
        ref._load_postcodes()
        ref._load_generation()
        ref._load_spen_sites()
        return ref

    # ---- loaders -----------------------------------------------------------------------
    def _load_ruc(self) -> None:
        path = self.folder / "ruc_oa.parquet"
        self.available["Rural/urban classification"] = path.exists()
        if not path.exists():
            return
        import shapely
        df = pd.read_parquet(path)
        geoms = shapely.from_wkb(df["wkb"].to_numpy())
        self._ruc = shapely.STRtree(geoms)
        self._ruc_names = df["ruc21nm"].to_numpy()

    def _load_addresses(self) -> None:
        path = self.folder / "addresses.parquet"
        self.available["Addresses"] = path.exists()
        if not path.exists():
            return
        from scipy.spatial import cKDTree
        df = pd.read_parquet(path, columns=["x", "y"])
        self._address_tree = cKDTree(df[["x", "y"]].to_numpy(dtype=np.float64))

    def _load_postcodes(self) -> None:
        path = self.folder / "postcodes.parquet"
        self.available["Postcodes"] = path.exists()
        if not path.exists():
            return
        df = pd.read_parquet(path)
        self._postcodes = dict(zip(df["postcode"], zip(df["e"], df["n"], strict=True),
                                   strict=True))

    def _load_generation(self) -> None:
        path = self.folder / "generation.csv"
        self.available["Existing generation"] = path.exists()
        if not path.exists():
            return
        from scipy.spatial import cKDTree
        df = pd.read_csv(path).dropna(subset=["e", "n"]).reset_index(drop=True)
        self._generation = df
        self._generation_tree = cKDTree(df[["e", "n"]].to_numpy(dtype=np.float64))

    def _load_spen_sites(self) -> None:
        # Optional: not listed in `available`, so a missing file does not warn every user.
        path = self.folder / "spen_sites.csv"
        if not path.exists():
            return
        df = pd.read_csv(path, dtype=str).fillna("")
        df["e"] = df["e"].astype(float)
        df["n"] = df["n"].astype(float)
        self.spen_sites = df
        index: dict[str, list[int]] = {}
        for i, row in df.iterrows():
            for value in {row["name"], row["label"]}:
                if key := site_key(value):
                    index.setdefault(key, [])
                    if i not in index[key]:
                        index[key].append(i)
        self._site_index = index

    @property
    def spen_sites_loaded(self) -> bool:
        return self.spen_sites is not None

    # ---- queries -----------------------------------------------------------------------
    def find_site(self, name: str) -> tuple[float, float, str] | None:
        found = self._find_site(name)
        return found if isinstance(found, tuple) else None

    def _find_site(self, name: str) -> tuple[float, float, str] | str | None:
        """Easting, northing and label of the SPEN substation called `name`.

        Exact match on the cleaned-up name first; otherwise the closest name if it is a
        clear match (score 90+, with no other name scoring as well). When a name belongs
        to substations in different places, a hint in the text ("primary", "BSP") picks
        one; without a hint the name is ambiguous and nothing is returned.
        """
        if self._site_index is None or not name:
            return None
        key = site_key(name)
        if not key:
            return None
        hits = self._site_index.get(key)
        if hits is None:
            from rapidfuzz import fuzz, process
            found = process.extract(key, list(self._site_index), scorer=fuzz.ratio,
                                    limit=2, score_cutoff=90)
            if not found or (len(found) > 1 and found[1][1] == found[0][1]):
                return None
            hits = self._site_index[found[0][0]]
        rows = self.spen_sites.loc[hits]
        hint = _type_hint(name)
        if hint and len(rows) > 1:
            typed = rows[rows["type"].str.lower().str.contains(hint, regex=False)]
            rows = typed if len(typed) else rows
        spread = np.hypot(rows["e"] - rows["e"].mean(), rows["n"] - rows["n"].mean()).max()
        if spread > 500:   # same name at different places: say which, so the user can choose
            return (f"“{name}” matches more than one SPEN substation "
                    f"({', '.join(rows['label'])}); add primary or BSP to the name")
        row = rows.iloc[0]
        return float(row["e"]), float(row["n"]), str(row["label"])

    @property
    def site_lookup(self):
        """For locate_row: (e, n, label), a reason the name is ambiguous, or None."""
        return self._find_site if self._site_index is not None else None

    def postcode(self, key: str) -> tuple[float, float] | None:
        return None if self._postcodes is None else self._postcodes.get(key)

    @property
    def postcode_lookup(self):
        return self.postcode if self._postcodes is not None else None

    def ruc(self, xy: np.ndarray) -> list[str | None]:
        if self._ruc is None:
            return [None] * len(xy)
        import shapely
        points = shapely.points(xy)
        point_idx, poly_idx = self._ruc.query(points, predicate="intersects")
        out: list[str | None] = [None] * len(xy)
        for p, g in zip(point_idx, poly_idx, strict=True):
            if out[p] is None:
                out[p] = str(self._ruc_names[g])
        return out

    def addresses(self, xy: np.ndarray, radii: tuple[int, ...]) -> pd.DataFrame:
        cols = {"nearest_address_m": [None] * len(xy)}
        cols.update({f"addresses_{r}m": [None] * len(xy) for r in radii})
        if self._address_tree is None or not len(xy):
            return pd.DataFrame(cols)
        dist, _ = self._address_tree.query(xy, k=1)
        cols["nearest_address_m"] = np.round(dist).astype(int)
        for r in radii:
            cols[f"addresses_{r}m"] = self._address_tree.query_ball_point(
                xy, r=r, return_length=True)
        return pd.DataFrame(cols)

    def generation_near(self, xy: np.ndarray, radius: float) -> list[pd.DataFrame | None]:
        if self._generation_tree is None:
            return [None] * len(xy)
        hits = self._generation_tree.query_ball_point(xy, r=radius)
        out = []
        for (x, y), idx in zip(xy, hits, strict=True):
            near = self._generation.iloc[idx].copy()
            near["distance_m"] = np.hypot(near["e"] - x, near["n"] - y).round()
            out.append(near.sort_values("distance_m"))
        return out
