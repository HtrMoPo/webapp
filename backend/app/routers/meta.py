from fastapi import APIRouter

from app import htr_united, vocab
from app.config import get_settings

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


@router.get("/config")
async def config():
    settings = get_settings()
    return {
        "zenodo_env": settings.zenodo_env,
        "zenodo_base_url": settings.zenodo_base_url,
    }
