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
import logging
import xml.etree.ElementTree as ET
from urllib.parse import urlsplit

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app import card
from app.models import ModelRecord, ModelVersion
from app.slugs import slugify, unique_slug

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


async def fetch_ocr_models() -> list[dict]:
    """Harvests every parseable v1 record from the ocr_models community.

    Returns a list of dicts: doi, concept_doi, metadata (parsed HTRMoPo v1
    front matter), body_html, files, published_at. Records that fail to
    parse (non-v1, malformed front matter, no README.md) are skipped rather
    than aborting the whole harvest.
    """
    results: list[dict] = []
    params = {"verb": "ListRecords", "metadataPrefix": "dcat", "set": _OAI_SET}

    async with httpx.AsyncClient(timeout=60.0) as client:
        while True:
            resp = await client.get(PRODUCTION_OAI_URL, params=params)
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
                if not dcat["doi"] or not readme_url:
                    continue

                try:
                    readme_resp = await client.get(readme_url)
                    readme_resp.raise_for_status()
                    parsed = card.parse_card(readme_resp.text)
                except Exception as exc:
                    logger.info("Skipping unparseable harvested record %s: %s", dcat["doi"], exc)
                    continue

                datestamp_el = header_el.find("./{*}datestamp") if header_el is not None else None
                results.append(
                    {
                        "doi": dcat["doi"],
                        "concept_doi": dcat["concept_doi"] or dcat["doi"],
                        "metadata": parsed.metadata,
                        "body_html": parsed.body_md,
                        "files": [
                            {"filename": f["url"].rsplit("/", 1)[-1], "size": f["size"]}
                            for f in dcat["distribution"]
                            if not f["url"].endswith("README.md")
                        ],
                        "published_at": datestamp_el.text if datestamp_el is not None else None,
                    }
                )

            resumption_el = list_records_el.find("./{*}resumptionToken")
            token = resumption_el.text if resumption_el is not None else None
            if not token:
                break
            params = {"verb": "ListRecords", "resumptionToken": token}

    return results


def _parse_datestamp(value: str | None) -> dt.datetime | None:
    if not value:
        return None
    try:
        return dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


async def sync_ocr_models(db: AsyncSession) -> dict:
    """Fetches the community listing and upserts it into our catalog tables.

    Returns a summary dict: {"seen": N, "created": N, "updated": N, "skipped_owned": N}.
    """
    harvested = await fetch_ocr_models()
    created = updated = skipped_owned = 0

    for item in harvested:
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
        version.files = item["files"]
        version.status = "published"
        version.zenodo_env = "production"
        version.published_at = _parse_datestamp(item["published_at"]) or version.published_at

    await db.commit()
    return {"seen": len(harvested), "created": created, "updated": updated, "skipped_owned": skipped_owned}
