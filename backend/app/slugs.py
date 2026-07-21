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


# Model detail page URLs are DOI-based (e.g. "/models/10.5281-zenodo.6669508/some-title")
# so links stay stable even if a record's title (and therefore its old
# title-derived `slug`) changes. A DOI has exactly one "/", between its
# registrant prefix ("10.NNNN") and suffix, so swapping it for "-" is a
# reversible, URL-safe encoding -- no percent-encoding needed.
_DOI_SLUG_RE = re.compile(r"^(10\.\d+)-(.+)$")


def doi_to_url_slug(doi: str) -> str:
    return doi.replace("/", "-")


def url_slug_to_doi(doi_slug: str) -> str | None:
    match = _DOI_SLUG_RE.match(doi_slug)
    return f"{match.group(1)}/{match.group(2)}" if match else None
