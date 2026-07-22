"""Harvests the public HTRMoPo "ocr_models" community from Zenodo via
OAI-PMH, mirroring the read path htrmopo/repo.py uses (ListRecords with the
custom "dcat" metadata prefix), and folds it into our own catalog.

Always targets *real* production Zenodo -- the ocr_models community only
meaningfully exists there, independent of this deployment's ZENODO_ENV
sandbox/production toggle used for OAuth/publishing.

Records already tracked as "app"-sourced (owned by a real user who published
them through this app) are never overwritten by harvesting, so this can't
clobber someone's own in-progress edits with a possibly-stale public copy.
"""

import datetime as dt
import html
import logging
import re
import xml.etree.ElementTree as ET
from urllib.parse import urlsplit

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app import card
from app.http_retry import get_with_retry as _get_with_retry
from app.models import ModelRecord, ModelVersion
from app.slugs import slugify, unique_slug
from app.zenodo_client import doi_to_recid

logger = logging.getLogger(__name__)

PRODUCTION_OAI_URL = "https://zenodo.org/oai2d"
_OAI_SET = "user-ocr_models"


def _doi_from_url(url: str | None) -> str | None:
    if not url:
        return None
    path = urlsplit(url).path
    doi = path[1:] if path.startswith("/") else path
    return doi or None


def _parse_dcat_metadata(metadata_el: ET.Element) -> dict:
    identifier = metadata_el.find("./{*}RDF/{*}Description/{*}identifier")
    concept_el = metadata_el.find("./{*}RDF/{*}Description/{*}isVersionOf/{*}Description/{*}identifier")

    distribution = []
    for element in metadata_el.findall("./{*}RDF/{*}Description/{*}distribution"):
        file_url_el = element.find("./{*}Distribution/{*}downloadURL")
        if file_url_el is None:
            continue
        url = next(iter(file_url_el.attrib.values()), None) or file_url_el.text
        if not url:
            continue
        size_el = element.find("./{*}Distribution/{*}byteSize")
        distribution.append({"url": url, "size": int(size_el.text) if size_el is not None else -1})

    return {
        "doi": _doi_from_url(identifier.text if identifier is not None else None),
        "concept_doi": _doi_from_url(concept_el.text if concept_el is not None else None),
        "distribution": distribution,
    }


async def fetch_ocr_models():
    """Harvests every parseable record from the ocr_models community, both
    current v1 (YAML front matter in README.md) and legacy v0 (a standalone
    metadata.json, only ever kraken text-recognition models) -- converting
    the latter to the v1 metadata shape on the way out (see
    card.v0_to_v1_metadata) so the rest of the pipeline stays v1-only. A
    record carrying both files is treated as v1.

    Yields dicts (doi, concept_doi, metadata, body_html, schema_version,
    files, published_at) one at a time as they're parsed, rather than
    collecting the whole community into memory before returning: OAI-PMH
    resumption tokens are time-limited, and fetching each record's
    README.md/metadata.json is a separate, sometimes slow, round trip --
    with hundreds of records across several pages, that pagination can
    genuinely take long enough for a later page's token to expire. Yielding
    incrementally lets the caller (sync_ocr_models) commit as it goes, so a
    later page failing doesn't throw away everything already harvested.
    Records that fail to parse (malformed front matter, invalid v0 JSON,
    neither metadata file) are skipped rather than aborting the whole harvest.
    """
    params = {"verb": "ListRecords", "metadataPrefix": "dcat", "set": _OAI_SET}

    async with httpx.AsyncClient(timeout=60.0) as client:
        while True:
            resp = await _get_with_retry(client, PRODUCTION_OAI_URL, params=params)
            resp.raise_for_status()
            root = ET.fromstring(resp.content)

            error_el = root.find("./{*}error")
            if error_el is not None:
                if error_el.get("code") != "noRecordsMatch":
                    logger.warning("OAI-PMH harvest error: %s", error_el.text)
                break

            list_records_el = root.find("./{*}ListRecords")
            if list_records_el is None:
                break

            for record_el in list_records_el.findall("./{*}record"):
                header_el = record_el.find("./{*}header")
                if header_el is not None and header_el.get("status") == "deleted":
                    continue
                metadata_el = record_el.find("./{*}metadata")
                if metadata_el is None:
                    continue

                dcat = _parse_dcat_metadata(metadata_el)
                readme_url = next(
                    (f["url"] for f in dcat["distribution"] if f["url"].endswith("README.md")), None
                )
                legacy_url = next(
                    (f["url"] for f in dcat["distribution"] if f["url"].endswith("metadata.json")), None
                )
                if not dcat["doi"] or not (readme_url or legacy_url):
                    continue

                try:
                    if readme_url:
                        resp = await client.get(readme_url)
                        resp.raise_for_status()
                        parsed = card.parse_card(resp.text)
                        metadata, body_md = parsed.metadata, parsed.body_md
                        schema_version, card_filename = "v1", "README.md"
                    else:
                        resp = await client.get(legacy_url)
                        resp.raise_for_status()
                        v0_metadata = resp.json()
                        card.validate_v0_metadata(v0_metadata)
                        metadata, body_md = card.v0_to_v1_metadata(v0_metadata)
                        schema_version, card_filename = "v0", "metadata.json"
                except Exception as exc:
                    logger.info("Skipping unparseable harvested record %s: %s", dcat["doi"], exc)
                    continue

                datestamp_el = header_el.find("./{*}datestamp") if header_el is not None else None
                yield {
                    "doi": dcat["doi"],
                    "concept_doi": dcat["concept_doi"] or dcat["doi"],
                    "metadata": metadata,
                    "body_html": body_md,
                    "schema_version": schema_version,
                    "files": [
                        {"filename": f["url"].rsplit("/", 1)[-1], "size": f["size"]}
                        for f in dcat["distribution"]
                        if not f["url"].endswith(card_filename)
                    ],
                    "published_at": datestamp_el.text if datestamp_el is not None else None,
                }

            resumption_el = list_records_el.find("./{*}resumptionToken")
            token = resumption_el.text if resumption_el is not None else None
            if not token:
                break
            params = {"verb": "ListRecords", "resumptionToken": token}


def _parse_datestamp(value: str | None) -> dt.datetime | None:
    if not value:
        return None
    try:
        return dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


async def sync_ocr_models(db: AsyncSession) -> dict:
    """Fetches the community listing and upserts it into our catalog tables.

    Commits after each record rather than once at the end: fetch_ocr_models
    can span several OAI-PMH pages, and a later page's resumption token can
    expire (observed as an httpx.HTTPStatusError partway through) before the
    whole harvest finishes. A single final commit would then discard every
    record already harvested; committing incrementally means whatever was
    fetched before the failure is kept, and the next run (nightly, or an
    admin-triggered retry) only has to pick up from where this one stopped.

    Returns a summary dict: {"seen": N, "created": N, "updated": N, "skipped_owned": N}.
    Raises whatever fetch_ocr_models raises (e.g. on an expired resumption
    token) after committing everything harvested so far -- callers should
    expect this to be a partial, not total, failure.
    """
    created = updated = skipped_owned = seen = 0

    async for item in fetch_ocr_models():
        seen += 1
        result = await db.execute(select(ModelRecord).where(ModelRecord.concept_doi == item["concept_doi"]))
        record = result.scalar_one_or_none()

        if record is not None and record.source == "app":
            # Owned by a real user via this app -- never overwritten by harvesting.
            skipped_owned += 1
            continue

        metadata = item["metadata"]

        if record is None:
            slug = await unique_slug(db, slugify(metadata.get("summary", "model")))
            record = ModelRecord(
                owner_user_id=None,
                slug=slug,
                source="harvested",
                concept_doi=item["concept_doi"],
            )
            db.add(record)
            await db.flush()
            created += 1
        else:
            updated += 1

        record.current_title = metadata.get("summary", "")
        record.current_summary = metadata.get("summary", "")
        record.model_type = metadata.get("model_type", [])
        record.language = metadata.get("language", [])
        record.script = metadata.get("script", [])
        record.license = metadata.get("license", "")

        version_result = await db.execute(select(ModelVersion).where(ModelVersion.version_doi == item["doi"]))
        version = version_result.scalar_one_or_none()
        if version is None:
            version = ModelVersion(model_record_id=record.id, version_doi=item["doi"])
            db.add(version)

        version.card_yaml = card.build_card_text(metadata, item["body_html"])
        version.card_body_md = item["body_html"]
        version.schema_version = item["schema_version"]
        version.files = item["files"]
        version.status = "published"
        version.zenodo_env = "production"
        version.published_at = _parse_datestamp(item["published_at"]) or version.published_at

        await db.commit()

    return {"seen": seen, "created": created, "updated": updated, "skipped_owned": skipped_owned}


def _zenodo_base_url(zenodo_env: str | None) -> str:
    return "https://zenodo.org" if zenodo_env == "production" else "https://sandbox.zenodo.org"


_TITLE_TAG_RE = re.compile(r"<title[^>]*>(.*?)</title>", re.IGNORECASE | re.DOTALL)


def _parse_related_identifiers(related_identifiers: list[dict]) -> dict:
    """Pure parsing of a Zenodo record's `metadata.related_identifiers`,
    split out from refresh_download_stats so it's unit-testable without a
    live network call.

    Returns {"obsoleted_by_doi": str | None, "variant_of_doi": str | None,
    "documented_by": [{"identifier", "scheme", "resource_type"}, ...]}.

    isVariantFormOf is only accepted when it points at a DOI-identified
    model (scheme == "doi" and resource_type == "model") -- unlike
    isObsoletedBy, Zenodo doesn't guarantee this relation is model-to-model,
    so it's checked explicitly rather than assumed.
    """
    obsoleted_by_doi = None
    variant_of_doi = None
    documented_by = []
    for rel in related_identifiers:
        relation = rel.get("relation")
        identifier = rel.get("identifier")
        if not identifier:
            continue
        if relation == "isObsoletedBy" and obsoleted_by_doi is None:
            obsoleted_by_doi = identifier
        elif (
            relation == "isVariantFormOf"
            and variant_of_doi is None
            and rel.get("scheme") == "doi"
            and rel.get("resource_type") == "model"
        ):
            variant_of_doi = identifier
        elif relation == "isDocumentedBy":
            documented_by.append(
                {
                    "identifier": identifier,
                    "scheme": rel.get("scheme"),
                    "resource_type": rel.get("resource_type"),
                }
            )
    return {
        "obsoleted_by_doi": obsoleted_by_doi,
        "variant_of_doi": variant_of_doi,
        "documented_by": documented_by,
    }


async def _fetch_paper_title(client: httpx.AsyncClient, identifier: str, scheme: str | None) -> str | None:
    """Best-effort title resolution for an isDocumentedBy paper -- there's no
    title in the related_identifier itself. Never blocks the harvest: any
    failure (404, timeout, unparseable response) just leaves the title
    unresolved, to be retried on a future run (see refresh_download_stats,
    which only calls this for identifiers still missing a cached title)."""
    try:
        if scheme == "doi":
            resp = await client.get(
                f"https://doi.org/{identifier}",
                headers={"Accept": "application/vnd.citationstyles.csl+json"},
                follow_redirects=True,
            )
            resp.raise_for_status()
            title = resp.json().get("title")
            return title or None
        resp = await client.get(identifier, follow_redirects=True)
        resp.raise_for_status()
        match = _TITLE_TAG_RE.search(resp.text)
        return html.unescape(match.group(1)).strip() or None if match else None
    except Exception as exc:
        logger.info("Could not resolve paper title for %s: %s", identifier, exc)
        return None


async def refresh_download_stats(db: AsyncSession) -> dict:
    """Best-effort download/view stats refresh via Zenodo's public records
    API (GET /api/records/<id>, no auth needed) -- covers every record with
    at least one published version, regardless of source (harvested or
    published through this app), since Zenodo aggregates `stats.downloads`
    across every version of a concept no matter which version id is queried.

    Each record is refreshed independently and committed on its own, so one
    slow/failing lookup (a deleted upstream record, a network blip) doesn't
    lose progress on the rest -- matching sync_ocr_models' incremental-commit
    approach above.
    """
    result = await db.execute(select(ModelRecord).options(selectinload(ModelRecord.versions)))
    records = result.scalars().all()

    # recid -> ModelRecord.id, built once up front so an obsoleting/variant
    # DOI reported by Zenodo can be resolved to a record we've already
    # harvested, without an extra query per record. Zenodo's
    # "isObsoletedBy"/"isVariantFormOf" identifiers are typically the
    # *concept* DOI (redirects to whichever version is currently latest),
    # not a specific version DOI, so both need indexing.
    recid_to_record_id: dict[str, int] = {}
    for record in records:
        if record.concept_doi:
            recid = doi_to_recid(record.concept_doi)
            if recid:
                recid_to_record_id[recid] = record.id
        for v in record.versions:
            if v.version_doi:
                recid = doi_to_recid(v.version_doi)
                if recid:
                    recid_to_record_id[recid] = record.id

    updated = failed = 0
    async with httpx.AsyncClient(timeout=15.0) as client:
        for record in records:
            published = [v for v in record.versions if v.status == "published" and not v.is_placeholder and v.version_doi]
            if not published:
                continue
            version = max(published, key=lambda v: v.published_at or dt.datetime.min.replace(tzinfo=dt.timezone.utc))
            recid = doi_to_recid(version.version_doi)
            if not recid:
                continue

            base = _zenodo_base_url(version.zenodo_env)
            try:
                resp = await client.get(f"{base}/api/records/{recid}")
                resp.raise_for_status()
                payload = resp.json()
                stats = payload.get("stats") or {}
            except Exception as exc:
                logger.info("Failed to refresh download stats for record %s: %s", record.slug, exc)
                failed += 1
                continue

            record.downloads = stats.get("downloads")
            record.views = stats.get("views")

            relations = _parse_related_identifiers(payload.get("metadata", {}).get("related_identifiers", []))

            record.obsoleted_by_doi = relations["obsoleted_by_doi"]
            obsoleted_by_recid = doi_to_recid(relations["obsoleted_by_doi"]) if relations["obsoleted_by_doi"] else None
            record.obsoleted_by_record_id = (
                recid_to_record_id.get(obsoleted_by_recid) if obsoleted_by_recid else None
            )

            record.variant_of_doi = relations["variant_of_doi"]
            variant_of_recid = doi_to_recid(relations["variant_of_doi"]) if relations["variant_of_doi"] else None
            record.variant_of_record_id = (
                recid_to_record_id.get(variant_of_recid) if variant_of_recid else None
            )

            # A resolved title is cached forever -- a published version's
            # related_identifiers can't change, so there's nothing to
            # re-fetch once we already have one (mirrors the "files can't
            # change" reasoning behind app.claim's placeholder self-heal).
            cached_titles = {p["identifier"]: p.get("title") for p in (record.documented_by or [])}
            documented_by = []
            for paper in relations["documented_by"]:
                title = cached_titles.get(paper["identifier"])
                if title is None:
                    title = await _fetch_paper_title(client, paper["identifier"], paper["scheme"])
                documented_by.append({**paper, "title": title})
            record.documented_by = documented_by

            await db.commit()
            updated += 1

    return {"updated": updated, "failed": failed}
