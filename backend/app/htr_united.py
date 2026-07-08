"""Fetches and caches the HTR-United dataset catalog
(https://htr-united.github.io/htr-united/catalog.json) so the model form can
offer a search-and-pick UI for the `datasets` field, the same way the
`base_model` field searches our own catalog.

Cache is persisted to a local JSON file (in the same volume as the SQLite DB
and staged uploads, so it survives restarts), refreshed via conditional GET
(ETag/Last-Modified -- HTR-United's GitHub Pages hosting supports both) on:
- app startup (loads whatever's on disk into memory)
- the nightly harvest loop (see app/main.py), alongside the Zenodo sync
- an admin-triggered manual refresh (POST /api/meta/datasets/refresh)

Lazy/on-request refetching was deliberately dropped in favor of these
explicit triggers, so a page load never blocks on (or silently serves stale
data past) a background refresh race.
"""

import json
import logging
import time
from pathlib import Path

import httpx

from app.config import get_settings

logger = logging.getLogger(__name__)

CATALOG_URL = "https://htr-united.github.io/htr-united/catalog.json"

_cache: dict | None = None  # {"entries": [...], "fetched_at": ts, "etag": str|None, "last_modified": str|None}


def _cache_path() -> Path:
    return Path(get_settings().database_path).parent / "htr_united_cache.json"


def _load_from_disk() -> dict | None:
    path = _cache_path()
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text())
    except Exception:
        logger.warning("Corrupt HTR-United cache file at %s; ignoring", path)
        return None


def _save_to_disk(cache: dict) -> None:
    path = _cache_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(cache))


def _normalize(repo_id: str, entry: dict) -> dict | None:
    title = entry.get("title")
    url = entry.get("url")
    if not title or not url:
        return None
    # HTR-United's "url" field is a bare DOI (e.g. "10.5281/zenodo.7467249"),
    # not a full URI -- HTRMoPo's `datasets` field requires format: uri.
    normalized_url = url if url.startswith(("http://", "https://")) else f"https://doi.org/{url}"
    return {"id": repo_id, "title": title, "url": normalized_url}


async def refresh_catalog() -> dict:
    """Always hits the network (conditionally -- a 304 means the catalog
    hasn't changed since our last fetch, so we skip reparsing) and updates
    the persisted + in-memory cache. Returns {"status": "updated"|"unchanged"
    |"error", "count": N}."""
    global _cache
    cache = _cache if _cache is not None else (_load_from_disk() or {})

    headers = {}
    if cache.get("etag"):
        headers["If-None-Match"] = cache["etag"]
    if cache.get("last_modified"):
        headers["If-Modified-Since"] = cache["last_modified"]

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get(CATALOG_URL, headers=headers)

        if resp.status_code == 304:
            cache["fetched_at"] = time.time()
            _cache = cache
            _save_to_disk(cache)
            return {"status": "unchanged", "count": len(cache.get("entries", []))}

        resp.raise_for_status()
        raw = resp.json()
    except Exception:
        logger.exception("Failed to refresh HTR-United catalog; keeping existing cache")
        return {"status": "error", "count": len(cache.get("entries", []))}

    entries = [e for e in (_normalize(repo_id, entry) for repo_id, entry in raw.items()) if e is not None]
    cache = {
        "entries": entries,
        "fetched_at": time.time(),
        "etag": resp.headers.get("ETag"),
        "last_modified": resp.headers.get("Last-Modified"),
    }
    _cache = cache
    _save_to_disk(cache)
    return {"status": "updated", "count": len(entries)}


async def fetch_catalog() -> list[dict]:
    """Serves the persisted/in-memory cache. Only hits the network itself if
    there's genuinely nothing cached yet (first run ever) -- routine refreshes
    happen via refresh_catalog() (nightly + admin button), not here."""
    global _cache
    if _cache is None:
        _cache = _load_from_disk()
    if _cache is None:
        await refresh_catalog()
    return _cache.get("entries", []) if _cache else []
