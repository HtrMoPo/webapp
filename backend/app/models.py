import datetime as dt

from sqlalchemy import ForeignKey, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


def _now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


class User(Base):
    __tablename__ = "users"
    __table_args__ = (UniqueConstraint("zenodo_user_id", "zenodo_env", name="uq_user_zenodo_identity"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    zenodo_user_id: Mapped[str] = mapped_column(String, index=True)
    # Which Zenodo instance this identity belongs to ("sandbox" | "production").
    zenodo_env: Mapped[str] = mapped_column(String)
    display_name: Mapped[str] = mapped_column(String, default="")
    email: Mapped[str | None] = mapped_column(String, nullable=True)

    # Admin-only actions (e.g. manually triggering a catalog harvest) are
    # gated on this; toggled via `make set-admin` (see app/scripts/manage_users.py).
    is_admin: Mapped[bool] = mapped_column(default=False)

    access_token: Mapped[str] = mapped_column(Text)
    refresh_token: Mapped[str | None] = mapped_column(Text, nullable=True)
    token_expires_at: Mapped[dt.datetime | None] = mapped_column(nullable=True)

    created_at: Mapped[dt.datetime] = mapped_column(default=_now)
    updated_at: Mapped[dt.datetime] = mapped_column(default=_now, onupdate=_now)

    model_records: Mapped[list["ModelRecord"]] = relationship(back_populates="owner")


class ModelRecord(Base):
    __tablename__ = "model_records"

    id: Mapped[int] = mapped_column(primary_key=True)
    # Null for records that only exist because they were harvested from the
    # public HTRMoPo community on Zenodo, not published through this app.
    owner_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    concept_doi: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    slug: Mapped[str] = mapped_column(String, unique=True, index=True)

    # "app" (published through this app) | "harvested" (pulled in from the
    # public ocr_models Zenodo community via OAI-PMH).
    source: Mapped[str] = mapped_column(String, default="app")

    current_title: Mapped[str] = mapped_column(String, default="")
    current_summary: Mapped[str] = mapped_column(Text, default="")
    model_type: Mapped[list] = mapped_column(JSON, default=list)
    language: Mapped[list] = mapped_column(JSON, default=list)
    script: Mapped[list] = mapped_column(JSON, default=list)
    license: Mapped[str] = mapped_column(String, default="")

    created_at: Mapped[dt.datetime] = mapped_column(default=_now)
    updated_at: Mapped[dt.datetime] = mapped_column(default=_now, onupdate=_now)

    owner: Mapped["User | None"] = relationship(back_populates="model_records")
    versions: Mapped[list["ModelVersion"]] = relationship(
        back_populates="model_record", order_by="ModelVersion.created_at"
    )


class ModelVersion(Base):
    __tablename__ = "model_versions"

    id: Mapped[int] = mapped_column(primary_key=True)
    model_record_id: Mapped[int] = mapped_column(ForeignKey("model_records.id"))

    version_doi: Mapped[str | None] = mapped_column(String, nullable=True)
    zenodo_deposition_id: Mapped[str | None] = mapped_column(String, nullable=True)
    # Which Zenodo instance this version was actually published to
    # ("sandbox" | "production"), stamped at publish time. The public catalog
    # only ever shows "production" versions, so sandbox test publishes never
    # leak into it regardless of which environment the deployment is
    # currently configured for.
    zenodo_env: Mapped[str | None] = mapped_column(String, nullable=True)

    card_yaml: Mapped[str] = mapped_column(Text)
    card_body_md: Mapped[str] = mapped_column(Text)
    files: Mapped[list] = mapped_column(JSON, default=list)

    # "draft" | "published" | "discarded"
    status: Mapped[str] = mapped_column(String, default="draft")

    created_at: Mapped[dt.datetime] = mapped_column(default=_now)
    published_at: Mapped[dt.datetime | None] = mapped_column(nullable=True)

    model_record: Mapped["ModelRecord"] = relationship(back_populates="versions")
