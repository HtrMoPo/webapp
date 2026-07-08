import asyncio
import datetime as dt
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from starlette.middleware.sessions import SessionMiddleware

from app import harvest, htr_united
from app.config import get_settings
from app.db import async_session
from app.routers import auth, meta, models

logger = logging.getLogger(__name__)

settings = get_settings()

if settings.zenodo_env == "production" and settings.session_secret in ("", "change-me-in-production"):
    raise RuntimeError(
        "SESSION_SECRET is still set to its insecure default while ZENODO_ENV=production. "
        "Set a real, random SESSION_SECRET before running against production Zenodo."
    )


async def _nightly_harvest_loop() -> None:
    """Runs app.harvest.sync_ocr_models and app.htr_united.refresh_catalog
    once a day, in addition to the Zenodo refresh already triggered by every
    publish. No OS-level cron/scheduler needed -- this is a plain asyncio
    task tied to the app process's lifetime, which is fine given the app
    runs as a single process/worker."""
    while True:
        now = dt.datetime.now(dt.timezone.utc)
        target = now.replace(hour=settings.nightly_harvest_hour_utc, minute=0, second=0, microsecond=0)
        if target <= now:
            target += dt.timedelta(days=1)
        await asyncio.sleep((target - now).total_seconds())
        try:
            async with async_session() as session:
                summary = await harvest.sync_ocr_models(session)
                logger.info("Nightly catalog harvest: %s", summary)
        except Exception:
            logger.exception("Nightly catalog harvest failed")
        try:
            summary = await htr_united.refresh_catalog()
            logger.info("Nightly HTR-United catalog refresh: %s", summary)
        except Exception:
            logger.exception("Nightly HTR-United catalog refresh failed")


@asynccontextmanager
async def lifespan(app: FastAPI):
    task = None
    if settings.enable_nightly_harvest:
        task = asyncio.create_task(_nightly_harvest_loop())
    yield
    if task:
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
