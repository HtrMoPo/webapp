import datetime as dt

import pytest
import pytest_asyncio
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.config import get_settings
from app.playground import router as playground_router
from app.playground import worker as playground_worker
from app.playground.models import Base as PlaygroundBase
from app.playground.models import PlaygroundJob
from tests.conftest import make_record, make_version


@pytest_asyncio.fixture
async def playground_db_session():
    engine = create_async_engine("sqlite+aiosqlite://")
    async with engine.begin() as conn:
        await conn.run_sync(PlaygroundBase.metadata.create_all)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with session_factory() as session:
        yield session
    await engine.dispose()


class FakeClient:
    def __init__(self, host="1.2.3.4"):
        self.host = host


class FakeRequest:
    def __init__(self, host="1.2.3.4"):
        self.client = FakeClient(host)


async def _seed_model(db_session, doi="10.5281/zenodo.1", filename="model.mlmodel"):
    record = make_record(slug=doi.replace("/", "-"))
    db_session.add(record)
    await db_session.flush()
    version = make_version(record, version_doi=doi, files=[{"filename": filename, "size": 10}])
    db_session.add(version)
    await db_session.commit()
    return version


async def _submit(playground_db_session, db_session, image=b"fake-image", **overrides):
    from fastapi import UploadFile
    import io

    kwargs = dict(
        request=FakeRequest(),
        image=UploadFile(filename="page.png", file=io.BytesIO(image)),
        direction="ltr",
        segmentation_doi="10.5281/zenodo.1",
        segmentation_filename="model.mlmodel",
        recognition_doi="10.5281/zenodo.1",
        recognition_filename="model.mlmodel",
        region_doi=None,
        region_filename=None,
        db=playground_db_session,
        catalog_db=db_session,
    )
    kwargs.update(overrides)
    return await playground_router.submit_job(**kwargs)


class TestRateLimit:
    async def test_rejects_after_max_per_ip(self, playground_db_session, db_session, monkeypatch):
        settings = get_settings()
        monkeypatch.setattr(settings, "playground_rate_limit_max_per_ip", 2)
        await _seed_model(db_session)

        await _submit(playground_db_session, db_session)
        await _submit(playground_db_session, db_session)
        with pytest.raises(HTTPException) as exc:
            await _submit(playground_db_session, db_session)
        assert exc.value.status_code == 429

    async def test_different_ips_are_independent(self, playground_db_session, db_session, monkeypatch):
        settings = get_settings()
        monkeypatch.setattr(settings, "playground_rate_limit_max_per_ip", 1)
        await _seed_model(db_session)

        await _submit(playground_db_session, db_session, request=FakeRequest("1.1.1.1"))
        # A second IP isn't affected by the first IP's limit.
        result = await _submit(playground_db_session, db_session, request=FakeRequest("2.2.2.2"))
        assert result["status"] == "queued"


class TestCapEviction:
    async def test_evicts_only_done_rows_to_make_room(self, playground_db_session, db_session, monkeypatch):
        settings = get_settings()
        monkeypatch.setattr(settings, "playground_max_rows", 2)
        monkeypatch.setattr(settings, "playground_rate_limit_max_per_ip", 100)
        await _seed_model(db_session)

        done_job = PlaygroundJob(
            ip_hash="x", status="done", direction="ltr",
            segmentation_doi="d", segmentation_filename="f",
            recognition_doi="d", recognition_filename="f",
            image_bytes=b"x",
        )
        queued_job = PlaygroundJob(
            ip_hash="y", status="queued", direction="ltr",
            segmentation_doi="d", segmentation_filename="f",
            recognition_doi="d", recognition_filename="f",
            image_bytes=b"x",
        )
        playground_db_session.add_all([done_job, queued_job])
        await playground_db_session.commit()

        result = await _submit(playground_db_session, db_session, request=FakeRequest("9.9.9.9"))
        assert result["status"] == "queued"

        from sqlalchemy import select

        remaining = (await playground_db_session.execute(select(PlaygroundJob))).scalars().all()
        assert done_job.id not in [j.id for j in remaining]
        assert queued_job.id in [j.id for j in remaining]

    async def test_rejects_when_queue_full_of_active_jobs(self, playground_db_session, db_session, monkeypatch):
        settings = get_settings()
        monkeypatch.setattr(settings, "playground_max_rows", 1)
        monkeypatch.setattr(settings, "playground_rate_limit_max_per_ip", 100)
        await _seed_model(db_session)

        running_job = PlaygroundJob(
            ip_hash="x", status="running", direction="ltr",
            segmentation_doi="d", segmentation_filename="f",
            recognition_doi="d", recognition_filename="f",
            image_bytes=b"x",
        )
        playground_db_session.add(running_job)
        await playground_db_session.commit()

        with pytest.raises(HTTPException) as exc:
            await _submit(playground_db_session, db_session, request=FakeRequest("9.9.9.9"))
        assert exc.value.status_code == 503

        from sqlalchemy import select

        remaining = (await playground_db_session.execute(select(PlaygroundJob))).scalars().all()
        assert len(remaining) == 1
        assert remaining[0].status == "running"


class TestUnknownModelRef:
    async def test_rejects_unpublished_or_unknown_doi(self, playground_db_session, db_session):
        with pytest.raises(HTTPException) as exc:
            await _submit(playground_db_session, db_session, segmentation_doi="10.5281/zenodo.999")
        assert exc.value.status_code == 422


class TestQueuePosition:
    async def test_first_job_is_position_one_not_zero(self, playground_db_session, db_session):
        """Position is 1-indexed for display -- "position 1" means next in
        line, not "0 jobs ahead of it"."""
        await _seed_model(db_session)
        first = await _submit(playground_db_session, db_session, request=FakeRequest("1.1.1.1"))
        second = await _submit(playground_db_session, db_session, request=FakeRequest("2.2.2.2"))
        assert first["queue_position"] == 1
        assert second["queue_position"] == 2

        status = await playground_router.get_job(second["id"], db=playground_db_session)
        assert status["queue_position"] == 2

    async def test_running_job_counts_as_ahead(self, playground_db_session, db_session):
        """A job waiting behind one already being processed must not report
        the same position as if nothing were ahead of it."""
        await _seed_model(db_session)
        from sqlalchemy import select

        first = await _submit(playground_db_session, db_session, request=FakeRequest("1.1.1.1"))
        running = (
            await playground_db_session.execute(select(PlaygroundJob).where(PlaygroundJob.public_id == first["id"]))
        ).scalar_one()
        running.status = "running"
        await playground_db_session.commit()

        second = await _submit(playground_db_session, db_session, request=FakeRequest("2.2.2.2"))
        assert second["queue_position"] == 2


class TestCleanup:
    async def test_marks_stale_running_jobs_as_error(self, playground_db_session, monkeypatch):
        monkeypatch.setattr(playground_worker, "async_session", lambda: playground_db_session)
        settings = get_settings()
        monkeypatch.setattr(settings, "playground_job_timeout_seconds", 60)

        stale = PlaygroundJob(
            ip_hash="x", status="running", direction="ltr",
            segmentation_doi="d", segmentation_filename="f",
            recognition_doi="d", recognition_filename="f",
            image_bytes=b"x",
            started_at=dt.datetime.now(dt.timezone.utc) - dt.timedelta(seconds=1000),
        )
        fresh = PlaygroundJob(
            ip_hash="x", status="running", direction="ltr",
            segmentation_doi="d", segmentation_filename="f",
            recognition_doi="d", recognition_filename="f",
            image_bytes=b"x",
            started_at=dt.datetime.now(dt.timezone.utc),
        )
        playground_db_session.add_all([stale, fresh])
        await playground_db_session.commit()

        count = await playground_worker.mark_stale_running_jobs_as_failed()
        assert count == 1

        stale_after = await playground_db_session.get(PlaygroundJob, stale.id)
        fresh_after = await playground_db_session.get(PlaygroundJob, fresh.id)
        assert stale_after.status == "error"
        assert fresh_after.status == "running"

    async def test_prunes_old_done_and_error_rows_but_keeps_active(self, playground_db_session, monkeypatch):
        monkeypatch.setattr(playground_worker, "async_session", lambda: playground_db_session)

        old_done = PlaygroundJob(
            ip_hash="x", status="done", direction="ltr",
            segmentation_doi="d", segmentation_filename="f",
            recognition_doi="d", recognition_filename="f",
            image_bytes=b"x",
            created_at=dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=48),
        )
        recent_done = PlaygroundJob(
            ip_hash="x", status="done", direction="ltr",
            segmentation_doi="d", segmentation_filename="f",
            recognition_doi="d", recognition_filename="f",
            image_bytes=b"x",
            created_at=dt.datetime.now(dt.timezone.utc),
        )
        old_queued = PlaygroundJob(
            ip_hash="x", status="queued", direction="ltr",
            segmentation_doi="d", segmentation_filename="f",
            recognition_doi="d", recognition_filename="f",
            image_bytes=b"x",
            created_at=dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=48),
        )
        playground_db_session.add_all([old_done, recent_done, old_queued])
        await playground_db_session.commit()

        await playground_worker._cleanup_once()

        from sqlalchemy import select

        remaining_ids = {j.id for j in (await playground_db_session.execute(select(PlaygroundJob))).scalars().all()}
        assert old_done.id not in remaining_ids
        assert recent_done.id in remaining_ids
        assert old_queued.id in remaining_ids
