"""Fetches and caches the HTR-United dataset catalog
(https://htr-united.github.io/htr-united/catalog.json) so the model form can
offer a search-and-pick UI for the `datasets` field, the same way the
`base_model` field searches our own catalog.

In-memory TTL cache, same spirit as app/progress.py -- fine for a single
deployment process, and cheap enough to just refetch on restart.
"""

import logging
import time

import httpx

logger = logging.getLogger(__name__)

CATALOG_URL = "https://htr-united.github.io/htr-united/catalog.json"
_TTL_SECONDS = 3600

_cache: dict = {"entries": None, "fetched_at": 0.0}


def _normalize(repo_id: str, entry: dict) -> dict | None:
    title = entry.get("title")
    url = entry.get("url")
    if not title or not url:
        return None
    # HTR-United's "url" field is a bare DOI (e.g. "10.5281/zenodo.7467249"),
    # not a full URI -- HTRMoPo's `datasets` field requires format: uri.
    normalized_url = url if url.startswith(("http://", "https://")) else f"https://doi.org/{url}"
    return {"id": repo_id, "title": title, "url": normalized_url}


async def fetch_catalog(force: bool = False) -> list[dict]:
    now = time.time()
    if not force and _cache["entries"] is not None and now - _cache["fetched_at"] < _TTL_SECONDS:
        return _cache["entries"]

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get(CATALOG_URL)
            resp.raise_for_status()
            raw = resp.json()
    except Exception:
        logger.exception("Failed to fetch HTR-United catalog; serving stale/empty cache")
        return _cache["entries"] or []

    entries = [e for e in (_normalize(repo_id, entry) for repo_id, entry in raw.items()) if e is not None]
    _cache["entries"] = entries
    _cache["fetched_at"] = now
    return entries
