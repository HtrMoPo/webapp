import re
import unicodedata

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import ModelRecord


def slugify(text: str) -> str:
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    text = re.sub(r"[^a-zA-Z0-9]+", "-", text).strip("-").lower()
    return text or "model"


async def unique_slug(db: AsyncSession, base: str) -> str:
    slug = base
    i = 2
    while (await db.execute(select(ModelRecord).where(ModelRecord.slug == slug))).scalar_one_or_none():
        slug = f"{base}-{i}"
        i += 1
    return slug
