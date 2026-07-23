import datetime as dt
import hashlib
import json
import logging

from fastapi import APIRouter, Depends, Form, HTTPException, Request, UploadFile
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db import get_db as get_catalog_db
from app.models import ModelVersion
from app.playground.db import get_db
from app.playground.models import PlaygroundJob

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/playground", tags=["playground"])

_ACTIVE_STATUSES = ("queued", "running")


def _hash_ip(ip: str) -> str:
    return hashlib.sha256(ip.encode("utf-8")).hexdigest()


async def _resolve_model_ref(doi: str, filename: str, db: AsyncSession) -> None:
    """Confirms `doi`/`filename` is a real, published model file this app
    already knows about -- so the runner container is only ever asked to
    fetch a Zenodo URL this app itself vouches for, never an
    arbitrary/attacker-supplied one."""
    result = await db.execute(select(ModelVersion).where(ModelVersion.version_doi == doi, ModelVersion.status == "published"))
    version = result.scalar_one_or_none()
    if not version or not any(f["filename"] == filename for f in version.files):
        raise HTTPException(status_code=422, detail=f"unknown_model_file: {doi} / {filename}")


@router.post("/jobs")
async def submit_job(
    request: Request,
    image: UploadFile,
    direction: str = Form(...),
    segmentation_doi: str = Form(...),
    segmentation_filename: str = Form(...),
    recognition_doi: str = Form(...),
    recognition_filename: str = Form(...),
    region_doi: str | None = Form(None),
    region_filename: str | None = Form(None),
    db: AsyncSession = Depends(get_db),
    catalog_db: AsyncSession = Depends(get_catalog_db),
):
    settings = get_settings()
    if not settings.enable_playground:
        raise HTTPException(status_code=404, detail="playground_disabled")
    if direction not in ("ltr", "rtl"):
        raise HTTPException(status_code=422, detail="invalid_direction")

    await _resolve_model_ref(segmentation_doi, segmentation_filename, catalog_db)
    await _resolve_model_ref(recognition_doi, recognition_filename, catalog_db)
    if region_doi or region_filename:
        if not (region_doi and region_filename):
            raise HTTPException(status_code=422, detail="incomplete_region_model")
        await _resolve_model_ref(region_doi, region_filename, catalog_db)

    ip_hash = _hash_ip(request.client.host if request.client else "unknown")

    window_start = dt.datetime.now(dt.timezone.utc) - dt.timedelta(minutes=settings.playground_rate_limit_window_minutes)
    recent_count = (
        await db.execute(
            select(func.count())
            .select_from(PlaygroundJob)
            .where(PlaygroundJob.ip_hash == ip_hash, PlaygroundJob.created_at >= window_start)
        )
    ).scalar_one()
    if recent_count >= settings.playground_rate_limit_max_per_ip:
        raise HTTPException(status_code=429, detail="rate_limit_exceeded")

    total = (await db.execute(select(func.count()).select_from(PlaygroundJob))).scalar_one()
    if total >= settings.playground_max_rows:
        # Only ever evict rows that are actually finished -- a full queue of
        # in-flight (queued/running) work must never be dropped to make room
        # for a new submission; the submitter gets told to try later instead.
        oldest_done_ids = (
            await db.execute(
                select(PlaygroundJob.id)
                .where(PlaygroundJob.status == "done")
                .order_by(PlaygroundJob.created_at)
                .limit(total - settings.playground_max_rows + 1)
            )
        ).scalars().all()
        if oldest_done_ids:
            await db.execute(delete(PlaygroundJob).where(PlaygroundJob.id.in_(oldest_done_ids)))
            await db.commit()
            total -= len(oldest_done_ids)
        if total >= settings.playground_max_rows:
            raise HTTPException(status_code=503, detail="queue_full")

    image_bytes = await image.read()
    if not image_bytes:
        raise HTTPException(status_code=422, detail="empty_image")

    job = PlaygroundJob(
        ip_hash=ip_hash,
        direction=direction,
        segmentation_doi=segmentation_doi,
        segmentation_filename=segmentation_filename,
        recognition_doi=recognition_doi,
        recognition_filename=recognition_filename,
        region_doi=region_doi or None,
        region_filename=region_filename or None,
        image_bytes=image_bytes,
        image_content_type=image.content_type or "application/octet-stream",
    )
    db.add(job)
    await db.commit()
    await db.refresh(job)

    queue_position = (
        await db.execute(
            select(func.count())
            .select_from(PlaygroundJob)
            .where(PlaygroundJob.status == "queued", PlaygroundJob.created_at < job.created_at)
        )
    ).scalar_one()

    return {"id": job.id, "status": job.status, "queue_position": queue_position}


@router.get("/jobs/{job_id}")
async def get_job(job_id: int, db: AsyncSession = Depends(get_db)):
    job = await db.get(PlaygroundJob, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="not_found")

    out = {"id": job.id, "status": job.status}
    if job.status == "queued":
        out["queue_position"] = (
            await db.execute(
                select(func.count())
                .select_from(PlaygroundJob)
                .where(PlaygroundJob.status == "queued", PlaygroundJob.created_at < job.created_at)
            )
        ).scalar_one()
    elif job.status == "done":
        out["result"] = json.loads(job.result_json) if job.result_json else None
    elif job.status == "error":
        out["error_message"] = job.error_message
    return out
