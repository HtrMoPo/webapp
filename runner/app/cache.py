"""Downloads and caches model files by (doi, filename) key on a local
volume, so repeated playground jobs against the same model don't re-fetch it
from Zenodo every time. The main app only ever gives this container URLs it
has already validated point at a real, published model file (see
app.playground.router._resolve_model_ref) -- this module trusts that and
just downloads/caches whatever URL/key it's given."""

import hashlib
import os
from pathlib import Path

import httpx

CACHE_DIR = Path(os.environ.get("MODEL_CACHE_DIR", "/cache"))
CACHE_DIR.mkdir(parents=True, exist_ok=True)


def _cache_path(key: str) -> Path:
    # Keys look like "10.5281/zenodo.123/model.mlmodel" -- hash them into a
    # flat, filesystem-safe name rather than trying to preserve structure.
    digest = hashlib.sha256(key.encode("utf-8")).hexdigest()
    suffix = "".join(Path(key).suffixes) or ""
    return CACHE_DIR / f"{digest}{suffix}"


async def get_or_download(key: str, url: str) -> Path:
    path = _cache_path(key)
    if path.exists() and path.stat().st_size > 0:
        return path

    tmp_path = path.with_suffix(path.suffix + ".part")
    async with httpx.AsyncClient(timeout=120, follow_redirects=True) as client:
        async with client.stream("GET", url) as resp:
            resp.raise_for_status()
            with open(tmp_path, "wb") as out:
                async for chunk in resp.aiter_bytes(1024 * 1024):
                    out.write(chunk)
    tmp_path.rename(path)
    return path
