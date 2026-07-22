"""Claims a logged-in user's own Zenodo depositions in the ocr_models
community that this app never harvested (no README.md, or one that failed
to parse as a v1 model card) so they show up under "My Models" and can be
used to publish a real new version through the app.

This also covers legacy v0 depositions (a standalone metadata.json instead
of a v1 README.md, only ever kraken text-recognition models): their real
metadata is read and converted to v1 (see card.v0_to_v1_metadata) so the
owner can upgrade them to the current schema by publishing a new v1 version
of the same record. A v0 record already harvested into the public catalog
(owned by nobody) is claimed in place so its owner can do that upgrade; a v1
record already carries full metadata and is left as harvested.

Unlike app.harvest, this reads via the deposit API with the user's own
OAuth token (GET /deposit/depositions) rather than the public OAI-PMH feed
-- that's the only way to reliably discover records this specific user
owns, since Zenodo has no third-party "who owns record X" lookup and
OAI-PMH's dcat metadata carries no owner/creator user id at all.

IMPORTANT: despite being documented as "all depositions for the currently
authenticated user", GET /deposit/depositions has been observed in
practice returning depositions NOT actually owned by the querying token
(their true `owners` field points at a different account entirely --
likely community-curator visibility bleeding through). Every candidate is
therefore cross-checked against ZenodoClient.get_deposition's `owners`
field (the same field auth._resolve_zenodo_user_id relies on) before ever
being claimed -- see _owns_deposition below. Without this, "My Models"
could show up other people's models as if they were the logged-in user's
own.
"""

import datetime as dt
import logging

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app import card
from app.http_retry import get_with_retry
from app.models import ModelRecord, ModelVersion, User
from app.slugs import slugify, unique_slug
from app.zenodo_client import ZenodoClient, ZenodoError, doi_to_recid

logger = logging.getLogger(__name__)

# Always targets *real* production Zenodo -- the ocr_models community only
# meaningfully exists there, independent of this deployment's ZENODO_ENV
# sandbox/production toggle used for OAuth/publishing (mirrors
# app.harvest.PRODUCTION_OAI_URL's reasoning).
PRODUCTION_API_URL = "https://zenodo.org/api/"
_PRODUCTION_FILE_BASE = "https://zenodo.org/records"
_COMMUNITY = "ocr_models"


def _parse_timestamp(value: str | None) -> dt.datetime | None:
    if not value:
        return None
    try:
        return dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _is_in_community(deposition: dict) -> bool:
    communities = deposition.get("metadata", {}).get("communities") or []
    return any(c.get("identifier") == _COMMUNITY for c in communities)


def _owns_deposition(deposition_detail: dict, zenodo_user_id: str) -> bool:
    """Same owner-id extraction as auth._resolve_zenodo_user_id (Zenodo puts
    it under `owners` as a list, or `owner` as a single value, depending on
    the endpoint/API version)."""
    owner = deposition_detail.get("owners") or deposition_detail.get("owner")
    owner_id = owner[0] if isinstance(owner, list) else owner
    return owner_id is not None and str(owner_id) == zenodo_user_id


async def _verify_ownership(client: ZenodoClient, deposition: dict, user: User) -> bool:
    """Cross-checks that `deposition` is genuinely owned by `user` against the
    trustworthy single-record detail (list_my_depositions can't be trusted on
    its own -- see the module docstring and ZenodoClient.get_deposition). A
    ZenodoError (typically a 403) confirms the token has no real access, i.e.
    it isn't ours."""
    doi = deposition.get("doi")
    try:
        detail = await client.get_deposition(deposition["id"])
    except ZenodoError as exc:
        logger.warning("Skipping deposition %s: could not verify ownership (%s)", doi, exc)
        return False
    if not _owns_deposition(detail, user.zenodo_user_id):
        logger.warning(
            "Skipping deposition %s: list_my_depositions returned it but its true owner "
            "doesn't match the querying user's zenodo_user_id %s",
            doi,
            user.zenodo_user_id,
        )
        return False
    return True


def _deposition_filenames(deposition: dict) -> set[str]:
    return {f.get("filename") for f in (deposition.get("files") or [])}


def _is_legacy_v0(deposition: dict) -> bool:
    """A legacy v0 deposition carries a standalone metadata.json and no v1
    README.md. A record with both is treated as v1 (mirrors app.harvest)."""
    names = _deposition_filenames(deposition)
    return "metadata.json" in names and "README.md" not in names


async def _fetch_legacy_v0_metadata(doi: str) -> dict | None:
    """Fetches and validates a legacy deposition's metadata.json from its
    public Zenodo record, returning the parsed dict (or None if it can't be
    fetched/validated). Read over the unauthenticated public files URL --
    community depositions are public, so no token is needed, and this makes
    no assumption about the deposit API's per-file link shape."""
    recid = doi_to_recid(doi)
    if recid is None:
        return None
    url = f"{_PRODUCTION_FILE_BASE}/{recid}/files/metadata.json"
    try:
        async with httpx.AsyncClient(timeout=60.0, follow_redirects=True) as client:
            resp = await get_with_retry(client, url)
            resp.raise_for_status()
            v0_metadata = resp.json()
        card.validate_v0_metadata(v0_metadata)
        return v0_metadata
    except Exception as exc:
        logger.info("Could not read legacy v0 metadata.json for %s: %s", doi, exc)
        return None


def _zenodo_person_to_author(person: dict) -> dict | None:
    """Zenodo's creators/contributors entries use a bare ORCID id (e.g.
    "0000-0002-1825-0097"); HTRMoPo's v1 schema expects authors[].orcid as a
    full URI (format: uri) -- the exact inverse of what
    zenodo_client._to_zenodo_creator does when going the other direction at
    publish time."""
    name = person.get("name", "")
    if not name:
        return None
    author = {"name": name, "affiliation": person.get("affiliation") or ""}
    orcid = person.get("orcid")
    if orcid:
        author["orcid"] = orcid if orcid.startswith("http") else f"https://orcid.org/{orcid}"
    return author


def _placeholder_metadata(deposition: dict) -> dict:
    """Best-effort partial v1 metadata from Zenodo's own generic fields.
    software_name/language/script/model_type have no Zenodo equivalent and
    stay blank -- the user fills them in when publishing a real version
    (card.validate_metadata already gates on this at publish time, so it's
    safe to persist incomplete metadata here).

    HTRMoPo's v1 schema has no notion of secondary authors/collaborators,
    unlike Zenodo which separates `creators` from `contributors` (each with
    their own name/affiliation/orcid). Rather than silently dropping
    contributors or conflating them into `authors`, they're kept as their own
    `contributors` key alongside it -- the v1 schema doesn't forbid extra
    properties (no additionalProperties: false), so this rides along in
    card_yaml without upsetting card.validate_metadata, while still being
    distinguishable from real HTRMoPo authors wherever this metadata is read.
    """
    zmeta = deposition.get("metadata", {})
    authors = [
        a for a in (_zenodo_person_to_author(p) for p in zmeta.get("creators", [])) if a is not None
    ] or [{"name": ""}]
    contributors = [
        c for c in (_zenodo_person_to_author(p) for p in zmeta.get("contributors", [])) if c is not None
    ]
    license_field = zmeta.get("license")
    metadata = {
        "summary": zmeta.get("title", ""),
        "authors": authors,
        "license": license_field.get("id", "") if isinstance(license_field, dict) else "",
        "software_name": "",
        "language": [],
        "script": [],
        "model_type": [],
    }
    if contributors:
        metadata["contributors"] = contributors
    return metadata


async def sync_my_depositions(user: User, db: AsyncSession) -> dict:
    """Fetches the caller's own ocr_models-community depositions and, for any
    not already tracked, creates a ModelRecord/ModelVersion: a real (public)
    version carrying converted metadata for a legacy v0 deposition, or an
    empty placeholder otherwise. A legacy v0 deposition already harvested
    into the catalog (owned by nobody) is instead claimed in place so its
    owner can upgrade it to v1.

    Returns a summary dict: {"seen": N, "created": N, "claimed": N, "skipped": N}.
    """
    client = ZenodoClient(PRODUCTION_API_URL, user.access_token)
    depositions = [d for d in await client.list_my_depositions(status="published") if _is_in_community(d)]
    # list_my_depositions(all_versions=True) returns every version of every
    # concept, in no particular guaranteed order -- sort oldest-to-newest per
    # concept so that, as the loop below processes them and repeatedly
    # overwrites the shared ModelRecord's current_title/summary/etc, the
    # concept's actual latest version's metadata is what's left standing.
    depositions.sort(key=lambda d: d.get("modified") or d.get("created") or "")

    seen = created = claimed = skipped = 0

    for deposition in depositions:
        seen += 1
        doi = deposition.get("doi")
        if not doi:
            continue
        concept_doi = deposition.get("conceptdoi") or doi

        existing_version = (
            await db.execute(select(ModelVersion).where(ModelVersion.version_doi == doi))
        ).scalar_one_or_none()
        if existing_version is not None:
            record = await db.get(ModelRecord, existing_version.model_record_id)
            if record is not None and record.owner_user_id is None and existing_version.schema_version == "v0":
                # Already tracked, harvested v0, owned by nobody -- take
                # ownership so its owner can upgrade it to v1. Ownership is
                # verified against the trustworthy single-record detail first,
                # as always.
                if not await _verify_ownership(client, deposition, user):
                    skipped += 1
                    continue
                record.owner_user_id = user.id
                record.source = "app"
                await db.commit()
                claimed += 1
                continue

            if (
                record is not None
                and record.owner_user_id == user.id
                and existing_version.is_placeholder
                and _is_legacy_v0({"files": existing_version.files or []})
            ):
                # Already ours, but stuck as an empty placeholder from an
                # earlier run whose metadata.json fetch failed (a transient
                # Zenodo gateway error, no retry at the time -- see
                # get_with_retry). The file listing itself can't have changed
                # for an already-published version, so there's no need to
                # re-hit the deposit API for it -- only the one thing that
                # never actually succeeded, the metadata.json content, is
                # worth retrying.
                v0_metadata = await _fetch_legacy_v0_metadata(doi)
                if v0_metadata is not None:
                    metadata, body_md = card.v0_to_v1_metadata(v0_metadata)
                    record.current_title = metadata["summary"]
                    record.current_summary = metadata["summary"]
                    record.model_type = metadata["model_type"]
                    record.language = metadata["language"]
                    record.script = metadata["script"]
                    record.license = metadata["license"]
                    existing_version.card_yaml = card.build_card_text(metadata, body_md)
                    existing_version.card_body_md = body_md
                    existing_version.schema_version = "v0"
                    existing_version.is_placeholder = False
                    existing_version.files = [
                        f for f in (existing_version.files or []) if f.get("filename") != "metadata.json"
                    ]
                    await db.commit()
                    claimed += 1
                    continue

            skipped += 1
            continue

        try:
            detail = await client.get_deposition(deposition["id"])
        except ZenodoError as exc:
            # Confirms the same thing a mismatched owner id would: Zenodo
            # itself refuses this token access to the single-record detail
            # (typically 403) for a deposition list_my_depositions
            # nonetheless included -- not actually ours, skip it.
            logger.warning(
                "Skipping deposition %s: could not verify ownership (%s)", doi, exc
            )
            skipped += 1
            continue

        if not _owns_deposition(detail, user.zenodo_user_id):
            logger.warning(
                "Skipping deposition %s: list_my_depositions returned it but its true owner "
                "doesn't match the querying user's zenodo_user_id %s",
                doi,
                user.zenodo_user_id,
            )
            skipped += 1
            continue

        record = (
            await db.execute(select(ModelRecord).where(ModelRecord.concept_doi == concept_doi))
        ).scalar_one_or_none()

        if record is not None and record.owner_user_id not in (None, user.id):
            logger.warning(
                "Skipping deposition %s: concept_doi %s already tracked under a different owner",
                doi,
                concept_doi,
            )
            skipped += 1
            continue

        # A legacy v0 deposition gets its real (converted) metadata and a body,
        # and becomes a genuine public catalog version -- there's enough there
        # to show, and its owner upgrades it to v1 by publishing a new version.
        # Anything else gets an empty, non-public placeholder that only exists
        # to let the user publish a first real version through the app.
        v0_metadata = await _fetch_legacy_v0_metadata(doi) if _is_legacy_v0(detail) else None
        if v0_metadata is not None:
            metadata, body_md = card.v0_to_v1_metadata(v0_metadata)
            schema_version = "v0"
            is_placeholder = False
            skip_file = "metadata.json"
        else:
            metadata, body_md = _placeholder_metadata(deposition), ""
            schema_version = "v1"
            is_placeholder = True
            skip_file = None

        if record is None:
            slug = await unique_slug(db, slugify(metadata["summary"] or "model"))
            record = ModelRecord(
                owner_user_id=user.id,
                source="app",
                slug=slug,
                concept_doi=concept_doi,
            )
            db.add(record)
            await db.flush()
            created += 1
        else:
            record.owner_user_id = user.id
            record.source = "app"
            claimed += 1

        record.current_title = metadata["summary"]
        record.current_summary = metadata["summary"]
        record.model_type = metadata["model_type"]
        record.language = metadata["language"]
        record.script = metadata["script"]
        record.license = metadata["license"]

        # publish_draft's "branch a new Zenodo version" logic picks the
        # record's latest ModelVersion by published_at -- with several
        # placeholders per record (one per Zenodo version), they need a real
        # published_at each, or that ordering is undefined between them and
        # a new version could get branched off a stale one.
        published_at = _parse_timestamp(deposition.get("modified") or deposition.get("created"))

        version = ModelVersion(
            model_record_id=record.id,
            version_doi=doi,
            zenodo_deposition_id=str(deposition["id"]),
            zenodo_env="production",
            status="published",
            schema_version=schema_version,
            is_placeholder=is_placeholder,
            card_yaml=card.build_card_text(metadata, body_md),
            card_body_md=body_md,
            files=[
                {"filename": f["filename"], "size": f.get("filesize", -1)}
                for f in deposition.get("files", [])
                if f.get("filename") != skip_file
            ],
            published_at=published_at,
        )
        db.add(version)

        await db.commit()

    return {"seen": seen, "created": created, "claimed": claimed, "skipped": skipped}
