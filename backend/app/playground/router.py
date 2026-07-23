import datetime as dt
import hashlib
import json
import logging

from fastapi import APIRouter, Depends, Form, HTTPException, Request, UploadFile
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db import get_db as get_catalog_db
from app.deps import get_admin_user
from app.models import ModelVersion, User
from app.playground.db import get_db
from app.playground.models import PlaygroundJob

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/playground", tags=["playground"])

_ACTIVE_STATUSES = ("queued", "running")


def _hash_ip(ip: str) -> str:
    return hashlib.sha256(ip.encode("utf-8")).hexdigest()


async def _queue_position(job: PlaygroundJob, db: AsyncSession) -> int:
    """1-indexed rank of `job` among not-yet-finished work (queued or
    already running) created before it -- "position 1" means it's next in
    line, not "0 jobs ahead of it". Also counts a currently *running* job
    as occupying a spot, so a queued job waiting behind one being processed
    doesn't misleadingly show the same position as if nothing were ahead
    of it."""
    ahead = (
        await db.execute(
            select(func.count())
            .select_from(PlaygroundJob)
            .where(PlaygroundJob.status.in_(_ACTIVE_STATUSES), PlaygroundJob.created_at < job.created_at)
        )
    ).scalar_one()
    return ahead + 1


async def _resolve_model_ref(doi: str, filename: str, db: AsyncSession) -> str:
    """Confirms `doi`/`filename` is a real, published model file this app
    already knows about -- so the runner container is only ever asked to
    fetch a Zenodo URL this app itself vouches for, never an
    arbitrary/attacker-supplied one. Returns the version's own zenodo_env
    (production vs sandbox), which is what actually determines which Zenodo
    instance serves the file -- not this deployment's own ZENODO_ENV
    setting (see PlaygroundJob.segmentation_zenodo_env)."""
    result = await db.execute(select(ModelVersion).where(ModelVersion.version_doi == doi, ModelVersion.status == "published"))
    version = result.scalar_one_or_none()
    if not version or not any(f["filename"] == filename for f in version.files):
        raise HTTPException(status_code=422, detail=f"unknown_model_file: {doi} / {filename}")
    return version.zenodo_env or "production"


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

    segmentation_zenodo_env = await _resolve_model_ref(segmentation_doi, segmentation_filename, catalog_db)
    recognition_zenodo_env = await _resolve_model_ref(recognition_doi, recognition_filename, catalog_db)
    region_zenodo_env = None
    if region_doi or region_filename:
        if not (region_doi and region_filename):
            raise HTTPException(status_code=422, detail="incomplete_region_model")
        region_zenodo_env = await _resolve_model_ref(region_doi, region_filename, catalog_db)

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
        # Only ever evict rows that are actually finished (done or error) --
        # a full queue of genuinely in-flight (queued/running) work must
        # never be dropped to make room for a new submission; the submitter
        # gets told to try later instead. Failed jobs are just as evictable
        # as successful ones here -- neither represents work still pending.
        oldest_finished_ids = (
            await db.execute(
                select(PlaygroundJob.id)
                .where(PlaygroundJob.status.in_(("done", "error")))
                .order_by(PlaygroundJob.created_at)
                .limit(total - settings.playground_max_rows + 1)
            )
        ).scalars().all()
        if oldest_finished_ids:
            await db.execute(delete(PlaygroundJob).where(PlaygroundJob.id.in_(oldest_finished_ids)))
            await db.commit()
            total -= len(oldest_finished_ids)
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
        segmentation_zenodo_env=segmentation_zenodo_env,
        recognition_doi=recognition_doi,
        recognition_filename=recognition_filename,
        recognition_zenodo_env=recognition_zenodo_env,
        region_doi=region_doi or None,
        region_filename=region_filename or None,
        region_zenodo_env=region_zenodo_env,
        image_bytes=image_bytes,
        image_content_type=image.content_type or "application/octet-stream",
    )
    db.add(job)
    await db.commit()
    await db.refresh(job)

    return {"id": job.public_id, "status": job.status, "queue_position": await _queue_position(job, db)}


@router.get("/jobs/{job_id}")
async def get_job(job_id: str, db: AsyncSession = Depends(get_db)):
    job = (await db.execute(select(PlaygroundJob).where(PlaygroundJob.public_id == job_id))).scalar_one_or_none()
    if not job:
        raise HTTPException(status_code=404, detail="not_found")

    out = {"id": job.public_id, "status": job.status}
    if job.status == "queued":
        out["queue_position"] = await _queue_position(job, db)
    elif job.status == "done":
        out["result"] = json.loads(job.result_json) if job.result_json else None
    elif job.status == "error":
        out["error_message"] = job.error_message
    return out


def _admin_job_summary(job: PlaygroundJob) -> dict:
    return {
        "id": job.public_id,
        "status": job.status,
        "created_at": job.created_at.isoformat(),
        "started_at": job.started_at.isoformat() if job.started_at else None,
        "finished_at": job.finished_at.isoformat() if job.finished_at else None,
        "direction": job.direction,
        "ip_hash": job.ip_hash,
        "segmentation": f"{job.segmentation_doi}/{job.segmentation_filename}",
        "recognition": f"{job.recognition_doi}/{job.recognition_filename}",
        "region": f"{job.region_doi}/{job.region_filename}" if job.region_doi else None,
        "error_message": job.error_message,
    }


@router.get("/admin/jobs")
async def admin_list_jobs(db: AsyncSession = Depends(get_db), _admin: User = Depends(get_admin_user)):
    """Admin-only: the current queue (queued/running, oldest first -- same
    order they'll be/are being worked) plus the most recently finished jobs,
    to see what's going on without paging through everything ever
    submitted."""
    active = (
        await db.execute(
            select(PlaygroundJob).where(PlaygroundJob.status.in_(_ACTIVE_STATUSES)).order_by(PlaygroundJob.created_at)
        )
    ).scalars().all()
    finished = (
        await db.execute(
            select(PlaygroundJob)
            .where(PlaygroundJob.status.in_(("done", "error")))
            .order_by(PlaygroundJob.created_at.desc())
            .limit(50)
        )
    ).scalars().all()
    return {
        "active": [_admin_job_summary(j) for j in active],
        "recent_finished": [_admin_job_summary(j) for j in finished],
    }


@router.get("/admin/jobs/{job_id}")
async def admin_get_job(job_id: str, db: AsyncSession = Depends(get_db), _admin: User = Depends(get_admin_user)):
    """Admin-only: full detail for one job, including the runner's raw
    output -- the list endpoint above omits this since it can be sizeable
    (full per-line text/baselines/boundaries, potentially per region too)."""
    job = (await db.execute(select(PlaygroundJob).where(PlaygroundJob.public_id == job_id))).scalar_one_or_none()
    if not job:
        raise HTTPException(status_code=404, detail="not_found")
    out = _admin_job_summary(job)
    out["result"] = json.loads(job.result_json) if job.result_json else None
    return out


@router.delete("/admin/jobs/{job_id}")
async def admin_cancel_job(job_id: str, db: AsyncSession = Depends(get_db), _admin: User = Depends(get_admin_user)):
    """Admin-only: removes a job outright. For a still-queued job this is a
    real cancel -- the worker's claim query only ever looks at rows that
    still exist. For a job already "running", the runner has no way to
    abort mid-inference (see app.inference's own docstring on this), so this
    only detaches it: the worker's later commit of the result against a
    since-deleted row simply matches zero rows and is silently discarded (no
    ORM version-counting is configured here), rather than erroring."""
    result = await db.execute(delete(PlaygroundJob).where(PlaygroundJob.public_id == job_id))
    await db.commit()
    if result.rowcount == 0:
        raise HTTPException(status_code=404, detail="not_found")
    return {"cancelled": job_id}


@router.post("/admin/queue/clear")
async def admin_clear_queue(db: AsyncSession = Depends(get_db), _admin: User = Depends(get_admin_user)):
    """Admin-only: bulk-cancels every still-*queued* job. Deliberately
    leaves a currently *running* job alone -- it can't be aborted mid-flight
    (see admin_cancel_job) and clearing it here would just silently orphan
    it without freeing up the runner any sooner than letting it finish."""
    result = await db.execute(delete(PlaygroundJob).where(PlaygroundJob.status == "queued"))
    await db.commit()
    return {"cancelled": result.rowcount}
