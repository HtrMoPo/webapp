"""Shared retry helper for talking to Zenodo's public endpoints.

Zenodo has, in practice, returned 502/503/504 gateway errors under load for
these endpoints -- transient, and a retry a few seconds later usually gets
through. Used by both app.harvest (OAI-PMH ListRecords/README fetches) and
app.claim (legacy v0 metadata.json fetches) so a single blip doesn't
permanently misclassify or drop a record.
"""

import asyncio

import httpx


async def get_with_retry(client: httpx.AsyncClient, url: str, *, retries: int = 5, **kwargs) -> httpx.Response:
    for attempt in range(retries + 1):
        resp = await client.get(url, **kwargs)
        if resp.status_code not in (502, 503, 504) or attempt == retries:
            return resp
        await asyncio.sleep(3)
    return resp
