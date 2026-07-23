"""Runs playground jobs one at a time against the separate kraken/D-Fine
runner container, plus a daily cleanup of old rows.

Deliberately no Redis/Celery: mirrors app.main's existing nightly-harvest
loop -- a plain asyncio task tied to the process lifetime, claiming work via
an atomic UPDATE instead of a distributed queue. That's enough here since
there's only ever supposed to be one job running at a time regardless."""

import asyncio
import datetime as dt
import logging

import httpx
from sqlalchemy import select, update

from app.config import get_settings
from app.playground.db import async_session
from app.playground.models import PlaygroundJob

logger = logging.getLogger(__name__)

_POLL_INTERVAL_SECONDS = 1
_CLEANUP_AGE_HOURS = 24


def _zenodo_base_url(zenodo_env: str) -> str:
    return "https://zenodo.org" if zenodo_env == "production" else "https://sandbox.zenodo.org"


async def _claim_next_job() -> int | None:
    """Atomically claims the oldest queued job by flipping it to "running".
    The UPDATE's WHERE clause re-checks status="queued", so if two workers
    (UVICORN_WORKERS > 1) raced for the same row, only one's UPDATE actually
    matches a row -- the loser's rowcount is 0 and it just loops again."""
    async with async_session() as session:
        job_id = (
            await session.execute(
                select(PlaygroundJob.id).where(PlaygroundJob.status == "queued").order_by(PlaygroundJob.created_at).limit(1)
            )
        ).scalar_one_or_none()
        if job_id is None:
            return None
        result = await session.execute(
            update(PlaygroundJob)
            .where(PlaygroundJob.id == job_id, PlaygroundJob.status == "queued")
            .values(status="running", started_at=dt.datetime.now(dt.timezone.utc))
        )
        await session.commit()
        return job_id if result.rowcount == 1 else None


def _file_url(doi: str, zenodo_env: str, filename: str) -> str:
    from app.zenodo_client import doi_to_recid

    recid = doi_to_recid(doi)
    base = _zenodo_base_url(zenodo_env)
    return f"{base}/records/{recid}/files/{filename}?download=1"


async def _run_job(job_id: int) -> None:
    settings = get_settings()
    async with async_session() as session:
        job = await session.get(PlaygroundJob, job_id)
        if job is None:
            return

        # Each model reference carries its *own* zenodo_env, captured at
        # submission time from the catalog's ModelVersion (see
        # app.playground.router._resolve_model_ref) -- a deployment
        # configured for sandbox publishing can still reference
        # production-hosted catalog models, so this deployment's own
        # ZENODO_ENV must never be assumed to apply to every model file.
        payload = {
            "direction": job.direction,
            "segmentation_url": _file_url(job.segmentation_doi, job.segmentation_zenodo_env, job.segmentation_filename),
            "segmentation_key": f"{job.segmentation_doi}/{job.segmentation_filename}",
            "recognition_url": _file_url(job.recognition_doi, job.recognition_zenodo_env, job.recognition_filename),
            "recognition_key": f"{job.recognition_doi}/{job.recognition_filename}",
        }
        if job.region_doi and job.region_filename:
            payload["region_url"] = _file_url(job.region_doi, job.region_zenodo_env, job.region_filename)
            payload["region_key"] = f"{job.region_doi}/{job.region_filename}"

        # httpx's files= tuple is (filename, content, content_type) -- the
        # filename only matters for the runner's own temp-file naming (see
        # runner's main.run), so a fixed placeholder is fine here.
        files = {"image": ("upload", job.image_bytes, job.image_content_type)}

        try:
            async with httpx.AsyncClient(timeout=settings.playground_job_timeout_seconds) as client:
                resp = await client.post(
                    f"{settings.playground_runner_url}/run",
                    data=payload,
                    files=files,
                )
            resp.raise_for_status()
            job.result_json = resp.text
            job.status = "done"
        except Exception as exc:
            logger.exception("Playground job %s failed", job_id)
            job.status = "error"
            job.error_message = str(exc)[:2000]
        finally:
            job.finished_at = dt.datetime.now(dt.timezone.utc)
            await session.commit()


async def playground_worker_loop() -> None:
    while True:
        try:
            job_id = await _claim_next_job()
        except Exception:
            logger.exception("Playground worker: failed to claim next job")
            job_id = None
        if job_id is None:
            await asyncio.sleep(_POLL_INTERVAL_SECONDS)
            continue
        await _run_job(job_id)


async def mark_stale_running_jobs_as_failed() -> int:
    """"running" jobs are only ever resolved by the worker that claimed them
    (see _run_job's try/finally); if the app process is killed/restarted
    mid-job, that row is orphaned -- forever "running", never picked up
    again since claiming only looks at status="queued". Anything still
    "running" well past the per-job timeout is obviously such an orphan, not
    genuinely in progress, so it's marked "error" here rather than left to
    confuse the polling frontend indefinitely."""
    settings = get_settings()
    cutoff = dt.datetime.now(dt.timezone.utc) - dt.timedelta(seconds=settings.playground_job_timeout_seconds * 2)
    async with async_session() as session:
        result = await session.execute(
            update(PlaygroundJob)
            .where(PlaygroundJob.status == "running", PlaygroundJob.started_at < cutoff)
            .values(status="error", error_message="stale: worker never returned a result", finished_at=dt.datetime.now(dt.timezone.utc))
        )
        await session.commit()
        return result.rowcount


async def _cleanup_once() -> int:
    stale = await mark_stale_running_jobs_as_failed()
    if stale:
        logger.info("Playground cleanup: marked %d stale running job(s) as failed", stale)

    cutoff = dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=_CLEANUP_AGE_HOURS)
    async with async_session() as session:
        from sqlalchemy import delete

        result = await session.execute(
            delete(PlaygroundJob).where(PlaygroundJob.status.in_(("done", "error")), PlaygroundJob.created_at < cutoff)
        )
        await session.commit()
        return result.rowcount


async def playground_cleanup_loop() -> None:
    """Once a day: marks orphaned "running" jobs (see
    mark_stale_running_jobs_as_failed) as failed, then prunes all finished
    (done/error) jobs older than 24h."""
    settings = get_settings()
    while True:
        now = dt.datetime.now(dt.timezone.utc)
        target = now.replace(hour=settings.nightly_harvest_hour_utc, minute=30, second=0, microsecond=0)
        if target <= now:
            target += dt.timedelta(days=1)
        await asyncio.sleep((target - now).total_seconds())
        try:
            removed = await _cleanup_once()
            logger.info("Playground cleanup: removed %d finished job(s)", removed)
        except Exception:
            logger.exception("Playground cleanup failed")
