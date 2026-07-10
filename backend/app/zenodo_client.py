"""Async Zenodo deposition client.

Replicates the exact call sequence used by HTRMoPo's publish.py/repo.py
(create deposition -> upload files -> set metadata -> publish, and the
records/{id}/versions flow for new versions) but with Authorization: Bearer
headers (OAuth access tokens) instead of HTRMoPo's ?access_token= query param.
"""

import asyncio
import re
from dataclasses import dataclass

import httpx

_DOI_RECID_RE = re.compile(r"[0-9.]+/zenodo\.([0-9]+)")


def doi_to_recid(doi: str) -> str | None:
    match = _DOI_RECID_RE.match(doi)
    return match.group(1) if match else None


@dataclass
class Deposition:
    id: str
    bucket_url: str
    prereserved_doi: str
    raw: dict


class ZenodoError(Exception):
    def __init__(self, status_code: int, detail: str):
        self.status_code = status_code
        self.detail = detail
        super().__init__(f"Zenodo API error {status_code}: {detail}")


class ZenodoClient:
    def __init__(self, api_url: str, access_token: str):
        self.api_url = api_url.rstrip("/") + "/"
        self._headers = {"Authorization": f"Bearer {access_token}"}

    async def _request(self, method: str, url: str, **kwargs) -> httpx.Response:
        async with httpx.AsyncClient(timeout=120.0) as client:
            resp = await client.request(method, url, headers=self._headers, **kwargs)
        if resp.status_code >= 400:
            raise ZenodoError(resp.status_code, resp.text)
        return resp

    async def create_deposition(self) -> Deposition:
        resp = await self._request("POST", f"{self.api_url}deposit/depositions", json={})
        data = resp.json()
        return Deposition(
            id=str(data["id"]),
            bucket_url=data["links"]["bucket"],
            prereserved_doi=data["metadata"]["prereserve_doi"]["doi"],
            raw=data,
        )

    async def new_version(self, doi: str) -> Deposition:
        """Creates a new draft version of the record the given DOI belongs to.

        Tries the records/{id}/versions endpoint first (what HTRMoPo uses),
        falling back to the older deposit/depositions/{id}/actions/newversion
        action if that fails.
        """
        recid = doi_to_recid(doi)
        if recid is None:
            raise ValueError(f"Could not resolve a Zenodo record id from DOI {doi!r}")

        # Resolve to the latest record id in case the DOI is a concept DOI.
        resolve_resp = await self._request("GET", f"{self.api_url}records/{recid}")
        latest_doi = resolve_resp.json()["doi"]
        latest_recid = doi_to_recid(latest_doi) or recid

        try:
            resp = await self._request("POST", f"{self.api_url}records/{latest_recid}/versions")
            new_recid = str(resp.json()["id"])
        except ZenodoError:
            resp = await self._request(
                "POST", f"{self.api_url}deposit/depositions/{latest_recid}/actions/newversion"
            )
            draft_url = resp.json()["links"]["latest_draft"]
            new_recid = draft_url.rstrip("/").rsplit("/", 1)[-1]

        depo_resp = await self._request("GET", f"{self.api_url}deposit/depositions/{new_recid}")
        data = depo_resp.json()
        return Deposition(
            id=str(data["id"]),
            bucket_url=data["links"]["bucket"],
            prereserved_doi=data["metadata"]["prereserve_doi"]["doi"],
            raw=data,
        )

    async def upload_file(self, bucket_url: str, filename: str, content: bytes) -> None:
        await self._request("PUT", f"{bucket_url}/{filename}", content=content)

    async def delete_file(self, bucket_url: str, filename: str) -> None:
        await self._request("DELETE", f"{bucket_url}/{filename}")

    async def list_files(self, deposition_id: str) -> list[dict]:
        resp = await self._request("GET", f"{self.api_url}deposit/depositions/{deposition_id}/files")
        return resp.json()

    async def put_metadata(self, deposition_id: str, metadata: dict) -> None:
        await self._request(
            "PUT",
            f"{self.api_url}deposit/depositions/{deposition_id}",
            json={"metadata": metadata},
        )

    async def publish(self, deposition_id: str) -> dict:
        resp = await self._request(
            "POST", f"{self.api_url}deposit/depositions/{deposition_id}/actions/publish"
        )
        return resp.json()

    async def discard(self, deposition_id: str) -> None:
        await self._request("POST", f"{self.api_url}deposit/depositions/{deposition_id}/actions/discard")

    async def _request_with_retry(self, method: str, url: str, *, retries: int = 5, **kwargs) -> httpx.Response:
        """Like _request, but retries on Zenodo gateway errors (502/503/504).
        Observed in practice (listing a deposit account's depositions):
        Zenodo's own reverse proxy has a ~30s timeout, and this particular
        query routinely takes close to that regardless of page size --
        individual attempts fail more often than not, but a retry a few
        seconds later usually gets through, so this retries more
        persistently than a typical transient-error handler would."""
        for attempt in range(retries + 1):
            try:
                return await self._request(method, url, **kwargs)
            except ZenodoError as exc:
                if exc.status_code not in (502, 503, 504) or attempt == retries:
                    raise
                await asyncio.sleep(3)

    async def get_deposition(self, deposition_id: str) -> dict:
        """Single-record GET -- unlike list_my_depositions' summary rows,
        this reliably includes the true `owners`/`owner` field (see
        auth._resolve_zenodo_user_id, which relies on the same field from
        the same endpoint shape). Used by app.claim to verify a deposition
        is genuinely owned by the caller before claiming it: in practice
        GET /deposit/depositions?status=... has been observed returning
        depositions NOT actually owned by the querying token (likely
        community-curator visibility bleeding through), so its results
        can't be trusted as "the caller's own" without this cross-check."""
        resp = await self._request_with_retry("GET", f"{self.api_url}deposit/depositions/{deposition_id}")
        return resp.json()

    async def list_my_depositions(
        self, status: str = "published", size: int = 100, all_versions: bool = True
    ) -> list[dict]:
        """Lists depositions Zenodo considers visible/manageable via this
        token with GET /deposit/depositions -- despite being documented as
        "all depositions for the currently authenticated user", this has
        been observed in practice to include depositions actually owned by
        someone else entirely (their `owners` field doesn't match the
        querying token's account). Callers MUST cross-check each result's
        true ownership via get_deposition before treating it as the
        caller's own -- see app.claim.sync_my_depositions.

        all_versions=True (the default) is needed for app.claim to see a
        concept's full version history -- Zenodo otherwise only returns
        each concept's single latest version, hiding older ones."""
        results: list[dict] = []
        page = 1
        while True:
            resp = await self._request_with_retry(
                "GET",
                f"{self.api_url}deposit/depositions",
                params={"status": status, "page": page, "size": size, "all_versions": all_versions},
            )
            batch = resp.json()
            results.extend(batch)
            if len(batch) < size:
                break
            page += 1
        return results


_ORCID_RE = re.compile(r"(\d{4}-\d{4}-\d{4}-\d{3}[\dX])")


def _to_zenodo_creator(author: dict) -> dict:
    """Zenodo's `creators.orcid` field expects the bare ORCID identifier
    (e.g. 0000-0002-1825-0097), not the full https://orcid.org/... URI that
    HTRMoPo's own schema stores it as."""
    creator = {"name": author["name"]}
    if author.get("affiliation"):
        creator["affiliation"] = author["affiliation"]
    if author.get("orcid"):
        match = _ORCID_RE.search(author["orcid"])
        if match:
            creator["orcid"] = match.group(1)
    return creator


def build_zenodo_metadata(card_metadata: dict, body_html: str, private: bool, version: str = "") -> dict:
    """Builds the Zenodo deposition `metadata` object from a parsed model card,
    following the field mapping used by htrmopo/publish.py (adapted for
    creators, since Zenodo expects a bare ORCID id, not HTRMoPo's URI form)."""
    data: dict = {
        "title": card_metadata["summary"],
        "upload_type": "publication",
        "publication_type": "other",
        "description": body_html,
        "creators": [_to_zenodo_creator(a) for a in card_metadata["authors"]],
        "access_right": "open",
        "license": card_metadata["license"],
    }

    keywords = card_metadata.get("keywords") or card_metadata.get("tags")
    if keywords:
        data["keywords"] = keywords

    # Secondary authors/collaborators -- not part of the HTRMoPo v1 card
    # schema (see app.claim's module docstring for the same distinction on
    # the read side), but Zenodo's own `contributors` field supports them
    # directly. Zenodo requires a `type` per contributor from a fixed
    # vocabulary; this app doesn't collect one, so "Other" (a valid generic
    # member of that vocabulary) is used for all of them.
    contributors = card_metadata.get("contributors")
    if contributors:
        data["contributors"] = [{**_to_zenodo_creator(c), "type": "Other"} for c in contributors]

    # A free-text version label (e.g. "1.6.0") -- Zenodo supports this
    # natively but it isn't part of the HTRMoPo v1 card schema, so it's
    # passed straight through here rather than round-tripping via card_metadata.
    if version:
        data["version"] = version

    if not private:
        data["communities"] = [{"identifier": "ocr_models"}]

    related_identifiers = []
    for ds in card_metadata.get("datasets") or []:
        related_identifiers.append({"relation": "isDerivedFrom", "identifier": ds, "resource_type": "dataset"})
    for base in card_metadata.get("base_model") or []:
        related_identifiers.append({"relation": "isDerivedFrom", "identifier": base, "resource_type": "other"})
    if related_identifiers:
        data["related_identifiers"] = related_identifiers

    return data
