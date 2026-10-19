"""Reference data the screening uses, each optional.

Files live in one folder (app/data/reference by default) and are produced by
`python -m gbeg.screening.prepare`:

    ruc_oa.parquet        ONS 2021 output areas: oa21cd, ruc21nm, wkb (EPSG:27700)
    addresses.parquet     OS Open UPRN points: x, y (EPSG:27700, metres)
    postcodes.parquet     OS Code-Point Open: postcode (no space), e, n
    generation.csv        existing and planned generation: name, technology, mw, status,
                          source, e, n

Missing files are reported in `available` and the related checks return None.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd


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

    @classmethod
    def load(cls, folder: Path) -> ReferenceData:
        ref = cls(Path(folder))
        ref._load_ruc()
        ref._load_addresses()
        ref._load_postcodes()
        ref._load_generation()
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

    # ---- queries -----------------------------------------------------------------------
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
