import datetime as dt

from sqlalchemy import LargeBinary, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


def _now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


class PlaygroundJob(Base):
    """One "try it in the browser" request. Lives in its own SQLite file
    (see app.playground.db) -- separate from the catalog DB since this is
    ephemeral, high-churn data (uploaded image bytes, raw kraken output)
    that gets pruned within a day (see app.playground.worker)."""

    __tablename__ = "playground_jobs"

    id: Mapped[int] = mapped_column(primary_key=True)
    created_at: Mapped[dt.datetime] = mapped_column(default=_now, index=True)
    started_at: Mapped[dt.datetime | None] = mapped_column(nullable=True)
    finished_at: Mapped[dt.datetime | None] = mapped_column(nullable=True)

    # SHA-256 hex digest of the client IP, not the raw address -- enough to
    # rate-limit by source without persisting real IPs.
    ip_hash: Mapped[str] = mapped_column(String, index=True)

    # "queued" | "running" | "done" | "error"
    status: Mapped[str] = mapped_column(String, default="queued", index=True)

    direction: Mapped[str] = mapped_column(String, default="ltr")  # "ltr" | "rtl"

    segmentation_doi: Mapped[str] = mapped_column(String)
    segmentation_filename: Mapped[str] = mapped_column(String)
    recognition_doi: Mapped[str] = mapped_column(String)
    recognition_filename: Mapped[str] = mapped_column(String)
    # Optional D-Fine region-segmentation model.
    region_doi: Mapped[str | None] = mapped_column(String, nullable=True)
    region_filename: Mapped[str | None] = mapped_column(String, nullable=True)

    image_bytes: Mapped[bytes] = mapped_column(LargeBinary)
    image_content_type: Mapped[str] = mapped_column(String, default="application/octet-stream")

    result_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
