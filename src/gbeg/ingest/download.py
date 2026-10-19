"""Download a source file into an immutable, versioned raw folder with a manifest.

Every download records the URL, retrieval time, size and SHA-256 hash, so any output can
be traced back to the exact bytes it was built from. Re-running with identical content is
a no-op.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

import requests

RAW_ROOT = Path("data/raw")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def download(source_key: str, url: str, release: str, filename: str,
             raw_root: Path = RAW_ROOT, timeout: int = 120) -> Path:
    """Fetch `url` to data/raw/<source_key>/<release>/<filename> and write manifest.json."""
    target_dir = raw_root / source_key / release
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / filename
    tmp = target.with_suffix(target.suffix + ".part")

    with requests.get(url, stream=True, timeout=timeout) as response:
        response.raise_for_status()
        with tmp.open("wb") as fh:
            for chunk in response.iter_content(chunk_size=1 << 20):
                fh.write(chunk)

    new_hash = _sha256(tmp)
    manifest_path = target_dir / "manifest.json"
    unchanged = (
        target.exists()
        and manifest_path.exists()
        and json.loads(manifest_path.read_text()).get("sha256") == new_hash
    )
    if unchanged:
        tmp.unlink()
        return target

    tmp.replace(target)
    manifest = {
        "source": source_key,
        "release": release,
        "url": url,
        "file": filename,
        "sha256": new_hash,
        "bytes": target.stat().st_size,
        "retrieved_at": datetime.now(UTC).isoformat(timespec="seconds"),
    }
    manifest_path.write_text(json.dumps(manifest, indent=2))
    return target
