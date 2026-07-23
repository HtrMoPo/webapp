from app import threads  # noqa: F401  -- must run before any subprocess is spawned

import logging
import tempfile
from pathlib import Path

from fastapi import FastAPI, Form, HTTPException, UploadFile

from app import cache
from app.inference import InferenceError, run_pipeline

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)

app = FastAPI(title="HTRMoPo Playground Runner")

# Only ever one job in flight (the main app's worker loop is single-threaded
# -- see app.playground.worker.playground_worker_loop), but guard here too
# in case this service is ever called from somewhere else.
_busy = False


@app.get("/healthz")
async def healthz():
    return {"status": "ok"}


@app.post("/run")
async def run(
    image: UploadFile,
    direction: str = Form(...),
    segmentation_url: str = Form(...),
    segmentation_key: str = Form(...),
    recognition_url: str = Form(...),
    recognition_key: str = Form(...),
    region_url: str | None = Form(None),
    region_key: str | None = Form(None),
):
    global _busy
    if _busy:
        raise HTTPException(status_code=503, detail="runner_busy")
    if direction not in ("ltr", "rtl"):
        raise HTTPException(status_code=422, detail="invalid_direction")

    _busy = True
    try:
        seg_path = await cache.get_or_download(segmentation_key, segmentation_url)
        reco_path = await cache.get_or_download(recognition_key, recognition_url)
        region_path = await cache.get_or_download(region_key, region_url) if region_url and region_key else None

        with tempfile.TemporaryDirectory() as tmp:
            # Only the basename of whatever filename the caller sent is
            # trusted -- an unexpected value here (e.g. a content-type
            # string containing "/") must never be interpreted as a nested
            # path under the temp dir.
            safe_name = Path(image.filename or "upload").name or "upload"
            image_path = Path(tmp) / safe_name
            image_path.write_bytes(await image.read())

            try:
                result = await run_pipeline(
                    image_path,
                    seg_path,
                    reco_path,
                    region_path,
                    direction,
                    threads=int(threads.RUNNER_THREADS),
                    timeout_seconds=240,
                )
            except InferenceError:
                logger.exception("kraken pipeline failed")
                raise HTTPException(status_code=500, detail="inference_failed")

        return result
    finally:
        _busy = False
