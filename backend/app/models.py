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


class RecentOAuthCallback(Base):
    """Zenodo authorization codes are single-use; a duplicate delivery of the
    same callback (browser back-forward-cache replay, tab/session restore, a
    double click) that re-exchanges the code gets invalid_grant even though
    the first delivery already succeeded. See app.routers.auth.callback --
    the first delivery records the outcome here so a duplicate, on whichever
    worker it lands on, can redirect straight in instead of re-exchanging.
    Rows are pruned once past expires_at."""

    __tablename__ = "recent_oauth_callbacks"

    code: Mapped[str] = mapped_column(String, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    expires_at: Mapped[dt.datetime]


class HarvestClaim(Base):
    """Marks a catalog-harvest run (see app.main) as claimed/done, and
    doubles as the cross-worker mutex that makes sure only one of several
    uvicorn workers actually runs it: the primary key insert is atomic, so
    with N workers racing to claim the same key, exactly one wins and the
    rest see an IntegrityError and back off.

    key="initial" is claimed at most once ever, so a fresh deployment gets a
    populated catalog right away instead of sitting empty until the next
    nightly harvest. key="nightly:YYYY-MM-DD" is claimed at most once per UTC
    day by the nightly harvest loop."""

    __tablename__ = "harvest_claims"

    key: Mapped[str] = mapped_column(String, primary_key=True)
    claimed_at: Mapped[dt.datetime] = mapped_column(default=_now)


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

    # Zenodo's stats.downloads/views for the record's latest public version,
    # refreshed best-effort alongside the catalog harvest (see
    # app.harvest.refresh_download_stats). Null until the first refresh runs.
    downloads: Mapped[int | None] = mapped_column(nullable=True)
    views: Mapped[int | None] = mapped_column(nullable=True)

    # Zenodo's "isObsoletedBy" related_identifier, read from the same
    # records API response as downloads/views (see
    # app.harvest.refresh_download_stats). obsoleted_by_doi is the raw DOI
    # Zenodo reports even if we haven't harvested the target record;
    # obsoleted_by_record_id is populated once/if that DOI resolves to a
    # ModelRecord we know about.
    obsoleted_by_doi: Mapped[str | None] = mapped_column(String, nullable=True)
    obsoleted_by_record_id: Mapped[int | None] = mapped_column(
        ForeignKey("model_records.id"), nullable=True
    )

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

    # HTRMoPo metadata schema this version's card was read from/written as:
    # "v1" (YAML front matter in README.md -- everything this app publishes)
    # or "v0" (a legacy standalone metadata.json, only ever for kraken text
    # recognition models). v0 versions are harvested/claimed read-only; their
    # owner upgrades them to v1 by publishing a new version (which is v1, so
    # the default here is "v1").
    schema_version: Mapped[str] = mapped_column(String, default="v1")

    # "draft" | "published" | "discarded"
    status: Mapped[str] = mapped_column(String, default="draft")

    # True for an auto-created placeholder representing a Zenodo deposition
    # the user owns but this app never harvested (no README, or an
    # unparseable one). Excluded from the public catalog and slug lookup for
    # everyone, including the owner, until a real new version is published
    # through the app (see app.claim.sync_my_depositions).
    is_placeholder: Mapped[bool] = mapped_column(default=False)

    created_at: Mapped[dt.datetime] = mapped_column(default=_now)
    published_at: Mapped[dt.datetime | None] = mapped_column(nullable=True)

    model_record: Mapped["ModelRecord"] = relationship(back_populates="versions")
