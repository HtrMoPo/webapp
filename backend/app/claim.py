"""Claims a logged-in user's own Zenodo depositions in the ocr_models
community that this app never harvested (no README.md, or one that failed
to parse as a v1 model card) so they show up under "My Models" and can be
used to publish a real new version through the app.

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

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app import card
from app.models import ModelRecord, ModelVersion, User
from app.slugs import slugify, unique_slug
from app.zenodo_client import ZenodoClient, ZenodoError

logger = logging.getLogger(__name__)

# Always targets *real* production Zenodo -- the ocr_models community only
# meaningfully exists there, independent of this deployment's ZENODO_ENV
# sandbox/production toggle used for OAuth/publishing (mirrors
# app.harvest.PRODUCTION_OAI_URL's reasoning).
PRODUCTION_API_URL = "https://zenodo.org/api/"
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
    """Fetches the caller's own ocr_models-community depositions and creates
    a placeholder ModelRecord/ModelVersion for any not already tracked.

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

        metadata = _placeholder_metadata(deposition)

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
            is_placeholder=True,
            card_yaml=card.build_card_text(metadata, ""),
            card_body_md="",
            files=[
                {"filename": f["filename"], "size": f.get("filesize", -1)}
                for f in deposition.get("files", [])
            ],
            published_at=published_at,
        )
        db.add(version)

        await db.commit()

    return {"seen": seen, "created": created, "claimed": claimed, "skipped": skipped}
