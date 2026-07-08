from fastapi import APIRouter, Depends, HTTPException

from app import htr_united, vocab
from app.config import get_settings
from app.deps import get_current_user
from app.models import User

router = APIRouter(prefix="/api/meta", tags=["meta"])


@router.get("/languages")
async def languages():
    return [{"code": code, "name": name} for code, name in sorted(vocab.iso639_3().items(), key=lambda kv: kv[1])]


@router.get("/scripts")
async def scripts():
    return [{"code": code, "name": name} for code, name in sorted(vocab.iso15924().items(), key=lambda kv: kv[1])]


@router.get("/licenses")
async def licenses():
    return [
        {"id": lic_id, "title": lic["title"], "url": lic.get("url", "")}
        for lic_id, lic in sorted(vocab.licenses().items(), key=lambda kv: kv[1]["title"])
    ]


@router.get("/model-types")
async def model_types():
    # Free-text per HTRMoPo's schema, but these are the conventional values
    # used across existing HTRMoPo model cards.
    return ["recognition", "segmentation", "reading order", "end-to-end"]


@router.get("/datasets")
async def datasets():
    return await htr_united.fetch_catalog()


@router.post("/datasets/refresh")
async def refresh_datasets(user: User = Depends(get_current_user)):
    """Admin-only: forces an immediate HTR-United catalog refresh, in
    addition to the automatic nightly one. Uses a conditional GET, so this
    is cheap even if the upstream catalog hasn't actually changed."""
    if not user.is_admin:
        raise HTTPException(status_code=403, detail="admin_required")
    return await htr_united.refresh_catalog()


@router.get("/config")
async def config():
    settings = get_settings()
    return {
        "zenodo_env": settings.zenodo_env,
        "zenodo_base_url": settings.zenodo_base_url,
    }
