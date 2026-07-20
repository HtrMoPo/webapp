import asyncio
import datetime as dt
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from starlette.middleware.sessions import SessionMiddleware

from app import claim, harvest, htr_united
from app.config import get_settings
from app.db import async_session
from app.models import HarvestClaim, User
from app.routers import auth, meta, models

settings = get_settings()

# Uvicorn's default logging setup only configures its own "uvicorn.*"
# loggers, not the root logger -- without this, INFO-level app logs (e.g.
# the Zenodo OAuth callback diagnostics in app.routers.auth) are silently
# dropped rather than reaching `docker compose logs`. Level is configurable
# via LOG_LEVEL since these can be chatty at INFO/DEBUG.
logging.basicConfig(
    level=getattr(logging, settings.log_level.upper(), logging.INFO),
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)

logger = logging.getLogger(__name__)

if settings.zenodo_env == "production" and settings.session_secret in ("", "change-me-in-production"):
    raise RuntimeError(
        "SESSION_SECRET is still set to its insecure default while ZENODO_ENV=production. "
        "Set a real, random SESSION_SECRET before running against production Zenodo."
    )


async def _claim(key: str) -> bool:
    """Attempts to atomically claim `key` in harvest_claims. With
    UVICORN_WORKERS > 1, every worker process runs its own copy of the
    nightly loop / initial-crawl check on its own schedule; without this,
    each would run the harvest independently. The primary-key insert is
    atomic at the SQLite level, so exactly one worker's insert succeeds and
    the rest get IntegrityError and back off -- no separate lock needed."""
    async with async_session() as session:
        try:
            session.add(HarvestClaim(key=key))
            await session.commit()
            return True
        except IntegrityError:
            await session.rollback()
            return False


async def _run_catalog_crawl(label: str) -> None:
    try:
        async with async_session() as session:
            summary = await harvest.sync_ocr_models(session)
            logger.info("%s catalog harvest: %s", label, summary)
    except Exception:
        logger.exception("%s catalog harvest failed", label)
    try:
        summary = await htr_united.refresh_catalog()
        logger.info("%s HTR-United catalog refresh: %s", label, summary)
    except Exception:
        logger.exception("%s HTR-United catalog refresh failed", label)
    try:
        async with async_session() as session:
            summary = await harvest.refresh_download_stats(session)
            logger.info("%s download stats refresh: %s", label, summary)
    except Exception:
        logger.exception("%s download stats refresh failed", label)


async def _run_claim_sync(label: str) -> None:
    """Runs app.claim.sync_my_depositions for every registered user.

    GET /deposit/depositions can't be trusted to only return depositions a
    given token actually owns (see app.claim's module docstring -- it's been
    observed returning other accounts' depositions, likely community-curator
    visibility bleeding through), so ownership is verified per-record
    (a posteriori) inside sync_my_depositions itself before anything is ever
    claimed. Running this nightly for everyone, in addition to the
    user-triggered "Sync from Zenodo" button, means a user's own un-harvested
    (no README) community depositions get picked up even if they never click
    it themselves."""
    async with async_session() as session:
        users = (await session.execute(select(User))).scalars().all()
    for user in users:
        try:
            async with async_session() as session:
                summary = await claim.sync_my_depositions(user, session)
                logger.info("%s claim sync for user %s: %s", label, user.id, summary)
        except Exception:
            logger.exception("%s claim sync failed for user %s", label, user.id)


async def _nightly_harvest_loop() -> None:
    """Runs app.harvest.sync_ocr_models, app.htr_united.refresh_catalog, and
    app.claim.sync_my_depositions (for every user) once a day, in addition to
    the Zenodo refresh already triggered by every publish. No OS-level
    cron/scheduler needed -- this is a plain asyncio task tied to each worker
    process's lifetime; _claim() makes sure only one worker actually runs it
    per UTC day even with several workers."""
    while True:
        now = dt.datetime.now(dt.timezone.utc)
        target = now.replace(hour=settings.nightly_harvest_hour_utc, minute=0, second=0, microsecond=0)
        if target <= now:
            target += dt.timedelta(days=1)
        await asyncio.sleep((target - now).total_seconds())
        day_key = f"nightly:{dt.datetime.now(dt.timezone.utc).date().isoformat()}"
        if await _claim(day_key):
            await _run_catalog_crawl("Nightly")
            await _run_claim_sync("Nightly")


async def _run_initial_crawl_if_needed() -> None:
    """Runs the catalog harvest once ever per database, marked by a claimed
    row in harvest_claims -- so a fresh deployment gets a populated catalog
    right away instead of sitting empty until the next nightly harvest
    (which may be disabled, or up to 24h away)."""
    if await _claim("initial"):
        logger.info("No initial catalog crawl recorded for this database; running one now")
        await _run_catalog_crawl("Initial")


@asynccontextmanager
async def lifespan(app: FastAPI):
    tasks = [asyncio.create_task(_run_initial_crawl_if_needed())]
    if settings.enable_nightly_harvest:
        tasks.append(asyncio.create_task(_nightly_harvest_loop()))
    yield
    for task in tasks:
        task.cancel()


app = FastAPI(title="HTRMoPo App", root_path=settings.url_base_path, lifespan=lifespan)
app.add_middleware(SessionMiddleware, secret_key=settings.session_secret, same_site="lax")

app.include_router(auth.router)
app.include_router(meta.router)
app.include_router(models.router)


@app.get("/healthz")
async def healthz():
    from sqlalchemy import text

    async with async_session() as session:
        await session.execute(text("SELECT 1"))
    return {"status": "ok"}

frontend_dir = Path(settings.frontend_dist_dir)
if frontend_dir.exists():
    assets_dir = frontend_dir / "assets"
    if assets_dir.exists():
        # Filenames under /assets are content-hashed by Vite, so they're safe
        # to cache forever; a new build always gets new filenames.
        class ImmutableStaticFiles(StaticFiles):
            def file_response(self, *args, **kwargs):
                response = super().file_response(*args, **kwargs)
                response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
                return response

        app.mount("/assets", ImmutableStaticFiles(directory=assets_dir), name="assets")

    @app.get("/{full_path:path}")
    async def spa_fallback(full_path: str):
        candidate = frontend_dir / full_path
        # index.html (and any other unhashed top-level file) references the
        # current build's hashed asset names, so it must never be cached --
        # otherwise a stale cached index.html can point at assets a later
        # deploy has already removed.
        if candidate.is_file() and candidate.name != "index.html":
            return FileResponse(candidate)
        return FileResponse(frontend_dir / "index.html", headers={"Cache-Control": "no-cache"})
