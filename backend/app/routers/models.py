import asyncio
import logging

from fastapi import APIRouter, Depends, HTTPException, Request, UploadFile
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app import card, claim, harvest, progress, storage
from app.config import get_settings
from app.db import async_session, get_db
from app.deps import get_current_user
from app.models import ModelRecord, ModelVersion, User
from app.slugs import doi_to_url_slug, slugify, unique_slug, url_slug_to_doi
from app.zenodo_client import ZenodoClient, ZenodoError, build_zenodo_metadata

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/models", tags=["models"])


class DraftIn(BaseModel):
    metadata: dict
    body_md: str
    title: str = ""


async def _trigger_background_harvest() -> None:
    """Fire-and-forget catalog refresh, kicked off after a successful
    publish -- a publish is already a moment we're talking to Zenodo, so it's
    a natural, low-cost point to also pick up any new community entries."""
    try:
        async with async_session() as session:
            summary = await harvest.sync_ocr_models(session)
            logger.info("Post-publish catalog harvest: %s", summary)
    except Exception:
        logger.exception("Post-publish catalog harvest failed")


def _is_public(version: ModelVersion) -> bool:
    # The public catalog only ever shows versions actually published to
    # production Zenodo, so sandbox test publishes never leak into it --
    # regardless of which ZENODO_ENV this deployment currently runs under.
    # Placeholder versions (see app.claim) are never public either -- they
    # exist only to unblock publishing a real version from "My Models".
    return version.status == "published" and version.zenodo_env == "production" and not version.is_placeholder


def _record_summary(
    record: ModelRecord,
    versions: list[ModelVersion] | None = None,
    *,
    records_by_id: dict[int, ModelRecord] | None = None,
) -> dict:
    versions = versions if versions is not None else [v for v in record.versions if _is_public(v)]
    latest = versions[-1] if versions else None
    obsoleted_by = None
    if record.obsoleted_by_doi:
        target = records_by_id.get(record.obsoleted_by_record_id) if records_by_id else None
        obsoleted_by = {
            "doi": record.obsoleted_by_doi,
            "doi_slug": doi_to_url_slug(target.concept_doi) if target and target.concept_doi else None,
            "title": target.current_title if target else None,
        }
    variant_of = None
    if record.variant_of_doi:
        target = records_by_id.get(record.variant_of_record_id) if records_by_id else None
        variant_of = {
            "doi": record.variant_of_doi,
            "doi_slug": doi_to_url_slug(target.concept_doi) if target and target.concept_doi else None,
            "title": target.current_title if target else None,
        }
    return {
        "id": record.id,
        "slug": record.slug,
        "concept_doi": record.concept_doi,
        # DOI-based URL identifier (e.g. "10.5281-zenodo.6669508") -- the
        # canonical part of the model detail page URL, stable across title
        # changes unlike `slug`. Null only for draft-only records, which are
        # never publicly linkable anyway (see get_model's 404 below).
        "doi_slug": doi_to_url_slug(record.concept_doi) if record.concept_doi else None,
        "title": record.current_title,
        "summary": record.current_summary,
        "model_type": record.model_type,
        "language": record.language,
        "script": record.script,
        "license": record.license,
        "downloads": record.downloads,
        "version_count": len(versions),
        # Schema of the current (latest visible) version -- "v0" flags a
        # legacy record whose owner can upgrade it to v1 (see app.claim and
        # the "publish a new version" flow).
        "schema_version": latest.schema_version if latest else None,
        "latest_version": _version_summary(latest) if latest else None,
        # Set when Zenodo reports this record as obsoleted by another one
        # (see app.harvest.refresh_download_stats). "slug"/"title" are only
        # populated if the obsoleting record has been harvested into our own
        # catalog too -- otherwise it's just the raw DOI.
        "obsoleted_by": obsoleted_by,
        # Set when Zenodo reports this record as a variant of another model
        # (e.g. CATMuS-Print Small/Tiny of Large) -- same shape as
        # obsoleted_by, but not a "stale" relation: hidden from the main
        # catalog behind its own toggle instead (see CatalogView.vue).
        "variant_of": variant_of,
        # Papers describing this model (Zenodo's "isDocumentedBy" relation).
        # "title" is best-effort resolved/cached by app.harvest and may be
        # null if it couldn't be resolved.
        "documented_by": record.documented_by,
    }


def _version_summary(version: ModelVersion) -> dict:
    return {
        "id": version.id,
        "doi": version.version_doi,
        "status": version.status,
        "schema_version": version.schema_version,
        "zenodo_env": version.zenodo_env,
        "files": version.files,
        "published_at": version.published_at.isoformat() if version.published_at else None,
        "card_yaml": version.card_yaml,
        "card_body_md": version.card_body_md,
        "is_placeholder": version.is_placeholder,
    }


@router.get("")
async def list_models(request: Request, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(ModelRecord).options(selectinload(ModelRecord.versions)))
    records = result.scalars().all()
    records_by_id = {r.id: r for r in records}
    session_user_id = request.session.get("user_id")

    output = []
    for r in records:
        public_versions = [v for v in r.versions if _is_public(v)]
        is_mine = session_user_id is not None and session_user_id == r.owner_user_id

        if public_versions:
            output.append({
                **_record_summary(r, public_versions, records_by_id=records_by_id),
                "is_mine": is_mine,
                "is_public": True,
            })
        elif is_mine:
            # Not yet public (e.g. sandbox-only), but it's the requester's own
            # record -- surface it to them (badged on the frontend), with any
            # of their own published versions (sandbox included). Records
            # with nothing published at all (pure drafts) still don't show
            # here; there's nothing to browse yet, and they're already
            # visible on /mine.
            own_versions = [v for v in r.versions if v.status == "published" and not v.is_placeholder]
            if own_versions:
                output.append({
                    **_record_summary(r, own_versions, records_by_id=records_by_id),
                    "is_mine": True,
                    "is_public": False,
                })

    return output


@router.get("/mine")
async def my_models(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(ModelRecord)
        .where(ModelRecord.owner_user_id == user.id)
        .options(selectinload(ModelRecord.versions))
    )
    records = result.scalars().all()
    return [
        {**_record_summary(r), "versions": [_version_summary(v) for v in r.versions]}
        for r in records
    ]


@router.post("/mine/sync")
async def sync_mine(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """Pulls in the caller's own ocr_models-community Zenodo depositions
    this app never harvested (no README, or an unparseable one), so they
    show up here to be turned into a real new version. Scoped to the
    caller's own token/data, so unlike /models/harvest this needs no admin
    gate."""
    return await claim.sync_my_depositions(user, db)


@router.get("/{doi_slug}")
async def get_model(doi_slug: str, request: Request, db: AsyncSession = Depends(get_db)):
    doi = url_slug_to_doi(doi_slug)
    if not doi:
        raise HTTPException(status_code=404, detail="not_found")
    result = await db.execute(
        select(ModelRecord).where(ModelRecord.concept_doi == doi).options(selectinload(ModelRecord.versions))
    )
    record = result.scalar_one_or_none()
    if not record:
        raise HTTPException(status_code=404, detail="not_found")

    # The owner can always see their own published versions (including
    # sandbox test publishes, e.g. right after publishing one); anyone else
    # only sees versions actually published to production Zenodo.
    session_user_id = request.session.get("user_id")
    is_owner = session_user_id is not None and session_user_id == record.owner_user_id
    visible_versions = [
        v
        for v in record.versions
        if v.status == "published" and not v.is_placeholder and (is_owner or v.zenodo_env == "production")
    ]
    if not visible_versions:
        raise HTTPException(status_code=404, detail="not_found")

    related_ids = set()
    if record.obsoleted_by_record_id:
        related_ids.add(record.obsoleted_by_record_id)
    if record.variant_of_record_id:
        related_ids.add(record.variant_of_record_id)
    obsoletes_result = await db.execute(
        select(ModelRecord).where(ModelRecord.obsoleted_by_record_id == record.id)
    )
    obsoletes = obsoletes_result.scalars().all()
    related_ids.update(r.id for r in obsoletes)

    variants_result = await db.execute(
        select(ModelRecord).where(ModelRecord.variant_of_record_id == record.id)
    )
    variants = variants_result.scalars().all()
    related_ids.update(r.id for r in variants)

    records_by_id = {}
    if related_ids:
        related_result = await db.execute(select(ModelRecord).where(ModelRecord.id.in_(related_ids)))
        records_by_id = {r.id: r for r in related_result.scalars().all()}

    return {
        **_record_summary(record, visible_versions, records_by_id=records_by_id),
        "is_owner": is_owner,
        "versions": [_version_summary(v) for v in visible_versions],
        # Records that Zenodo reports as obsoleted by *this* one -- surfaced
        # here so they stay discoverable from the model that superseded them
        # even though they're excluded from the main catalog by default.
        "obsoletes": [
            {"doi_slug": doi_to_url_slug(r.concept_doi) if r.concept_doi else None, "title": r.current_title, "doi": r.concept_doi}
            for r in obsoletes
        ],
        # Records that Zenodo reports as a variant of *this* one -- surfaced
        # the same way as obsoletes, but distinct: these are sibling models,
        # not superseded ones.
        "variants": [
            {"doi_slug": doi_to_url_slug(r.concept_doi) if r.concept_doi else None, "title": r.current_title, "doi": r.concept_doi}
            for r in variants
        ],
    }


@router.post("/drafts")
async def create_draft(
    body: DraftIn, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
):
    slug = await unique_slug(db, slugify(body.title or body.metadata.get("summary", "model")))
    record = ModelRecord(owner_user_id=user.id, slug=slug)
    db.add(record)
    await db.flush()

    version = ModelVersion(
        model_record_id=record.id,
        card_yaml=card.build_card_text(body.metadata, body.body_md),
        card_body_md=body.body_md,
        files=[],
        status="draft",
    )
    db.add(version)
    await db.commit()
    await db.refresh(version)
    return {"record_id": record.id, "version_id": version.id, "slug": slug}


@router.post("/{record_id}/versions/draft")
async def create_new_version_draft(
    record_id: int,
    body: DraftIn,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    record = await db.get(ModelRecord, record_id)
    if not record or record.owner_user_id != user.id:
        raise HTTPException(status_code=404, detail="not_found")

    version = ModelVersion(
        model_record_id=record.id,
        card_yaml=card.build_card_text(body.metadata, body.body_md),
        card_body_md=body.body_md,
        files=[],
        status="draft",
    )
    db.add(version)
    await db.commit()
    await db.refresh(version)
    return {"record_id": record.id, "version_id": version.id}


def _zenodo_error_messages(exc: ZenodoError) -> list[str]:
    import json

    try:
        body = json.loads(exc.detail)
    except (json.JSONDecodeError, TypeError):
        return [f"Zenodo error {exc.status_code}: {exc.detail}"]

    messages = []
    for err in body.get("errors", []):
        field = err.get("field", "")
        for msg in err.get("messages", [err.get("message", "")]):
            messages.append(f"{field}: {msg}" if field else msg)
    if not messages and body.get("message"):
        messages.append(body["message"])
    return messages or [f"Zenodo error {exc.status_code}"]


async def _get_owned_draft(version_id: int, user: User, db: AsyncSession) -> ModelVersion:
    version = await db.get(ModelVersion, version_id)
    if not version:
        raise HTTPException(status_code=404, detail="not_found")
    record = await db.get(ModelRecord, version.model_record_id)
    if not record or record.owner_user_id != user.id:
        raise HTTPException(status_code=404, detail="not_found")
    if version.status != "draft":
        raise HTTPException(status_code=409, detail="version_not_draft")
    return version


@router.put("/versions/{version_id}")
async def update_draft(
    version_id: int,
    body: DraftIn,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    version = await _get_owned_draft(version_id, user, db)
    version.card_yaml = card.build_card_text(body.metadata, body.body_md)
    version.card_body_md = body.body_md
    await db.commit()
    return {"ok": True}


@router.post("/versions/{version_id}/files")
async def upload_file(
    version_id: int,
    file: UploadFile,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    version = await _get_owned_draft(version_id, user, db)

    max_bytes = get_settings().max_upload_mb * 1024 * 1024
    dest = storage.draft_dir(version_id) / file.filename
    total = 0
    try:
        with open(dest, "wb") as out:
            while chunk := await file.read(1024 * 1024):
                total += len(chunk)
                if total > max_bytes:
                    raise HTTPException(
                        status_code=413,
                        detail=f"file_too_large: exceeds the {get_settings().max_upload_mb}MB limit",
                    )
                out.write(chunk)
    except HTTPException:
        dest.unlink(missing_ok=True)
        raise

    files = [f for f in version.files if f["filename"] != file.filename]
    files.append({"filename": file.filename, "size": total})
    version.files = files
    await db.commit()
    return {"files": version.files}


@router.delete("/versions/{version_id}/files/{filename}")
async def delete_file(
    version_id: int,
    filename: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    version = await _get_owned_draft(version_id, user, db)
    storage.delete_draft_file(version_id, filename)
    version.files = [f for f in version.files if f["filename"] != filename]
    await db.commit()
    return {"files": version.files}


@router.post("/versions/{version_id}/discard")
async def discard_draft(
    version_id: int, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
):
    version = await _get_owned_draft(version_id, user, db)
    storage.cleanup_draft(version_id)
    if version.zenodo_deposition_id:
        client = ZenodoClient(get_settings().zenodo_api_url, user.access_token)
        try:
            await client.discard(version.zenodo_deposition_id)
        except Exception:
            pass
    await db.delete(version)
    await db.commit()
    return {"ok": True}


class PublishIn(BaseModel):
    private: bool = False
    # Free-text version label (e.g. "1.6.0") some depositors like to set on
    # Zenodo -- not part of the HTRMoPo v1 card schema/catalog metadata, so
    # it's only ever sent through to Zenodo's own `metadata.version` field at
    # publish time, never persisted on ModelRecord/ModelVersion or the card
    # YAML itself.
    version: str = ""


@router.post("/versions/{version_id}/publish")
async def publish_draft(
    version_id: int,
    body: PublishIn,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    version = await _get_owned_draft(version_id, user, db)
    record = await db.get(ModelRecord, version.model_record_id)

    parsed = card.parse_card(version.card_yaml)
    metadata = parsed.metadata

    client = ZenodoClient(get_settings().zenodo_api_url, user.access_token)

    try:
        if record.concept_doi:
            progress.set_progress(version_id, "resolving_previous_version")
            latest_result = await db.execute(
                select(ModelVersion)
                .where(ModelVersion.model_record_id == record.id, ModelVersion.status == "published")
                .order_by(ModelVersion.published_at.desc())
                .limit(1)
            )
            latest_version = latest_result.scalar_one_or_none()
            if latest_version is None or not latest_version.version_doi:
                raise HTTPException(status_code=409, detail="no_published_version_to_branch_from")
            # Zenodo resolves /records/{id} from a specific version's DOI, not
            # the shared concept DOI, to find the record to branch a new version from.
            deposition = await client.new_version(latest_version.version_doi)
        else:
            progress.set_progress(version_id, "creating_deposition")
            deposition = await client.create_deposition()

        metadata["id"] = deposition.prereserved_doi
        try:
            card.validate_metadata(metadata)
        except card.CardValidationError as exc:
            raise HTTPException(status_code=422, detail={"errors": exc.errors}) from exc

        card_text = card.build_card_text(metadata, parsed.body_md)
        progress.set_progress(version_id, "uploading_file", "README.md")
        await client.upload_file(deposition.bucket_url, "README.md", card_text.encode("utf-8"))

        draft_files = storage.list_draft_files(version_id)
        for i, path in enumerate(draft_files, start=1):
            progress.set_progress(version_id, "uploading_file", f"{path.name} ({i}/{len(draft_files)})")
            await client.upload_file(deposition.bucket_url, path.name, path.read_bytes())

        progress.set_progress(version_id, "setting_metadata")
        zenodo_metadata = build_zenodo_metadata(
            metadata, card.render_body_html(parsed.body_md), body.private, version=body.version
        )
        await client.put_metadata(deposition.id, zenodo_metadata)

        progress.set_progress(version_id, "publishing")
        published = await client.publish(deposition.id)
    except ZenodoError as exc:
        progress.clear_progress(version_id)
        raise HTTPException(status_code=502, detail={"errors": _zenodo_error_messages(exc)}) from exc
    except HTTPException:
        progress.clear_progress(version_id)
        raise

    version.card_yaml = card_text
    version.zenodo_deposition_id = deposition.id
    version.version_doi = published["doi"]
    version.zenodo_env = get_settings().zenodo_env
    version.status = "published"
    version.files = [{"filename": p.name, "size": p.stat().st_size} for p in storage.list_draft_files(version_id)]

    if not record.concept_doi:
        record.concept_doi = published.get("conceptdoi") or published["doi"]
    record.current_title = metadata["summary"]
    record.current_summary = metadata["summary"]
    record.model_type = metadata.get("model_type", [])
    record.language = metadata.get("language", [])
    record.script = metadata.get("script", [])
    record.license = metadata.get("license", "")

    from datetime import datetime, timezone

    version.published_at = datetime.now(timezone.utc)

    await db.commit()
    storage.cleanup_draft(version_id)
    progress.clear_progress(version_id)

    asyncio.create_task(_trigger_background_harvest())

    return {
        "doi": version.version_doi,
        "concept_doi": record.concept_doi,
        "slug": record.slug,
        "doi_slug": doi_to_url_slug(record.concept_doi),
    }


@router.get("/versions/{version_id}/publish/progress")
async def publish_progress(
    version_id: int, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
):
    version = await db.get(ModelVersion, version_id)
    if not version:
        raise HTTPException(status_code=404, detail="not_found")
    record = await db.get(ModelRecord, version.model_record_id)
    if not record or record.owner_user_id != user.id:
        raise HTTPException(status_code=404, detail="not_found")
    return progress.get_progress(version_id)


@router.post("/harvest")
async def trigger_harvest(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """Manually refreshes the catalog from the public ocr_models Zenodo
    community. Admin-only: this fans out to an external OAI-PMH harvest plus
    a README.md fetch per record, which is more load than a base user should
    be able to trigger on demand (the automatic post-publish/nightly refresh
    already covers regular users' needs)."""
    if not user.is_admin:
        raise HTTPException(status_code=403, detail="admin_required")
    summary = await harvest.sync_ocr_models(db)
    summary["download_stats"] = await harvest.refresh_download_stats(db)
    return summary
