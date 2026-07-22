import datetime as dt

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.models import Base, ModelRecord, ModelVersion, User


@pytest_asyncio.fixture
async def db_session():
    """In-memory sqlite, schema created straight from the ORM metadata --
    no need to run alembic migrations for unit tests."""
    engine = create_async_engine("sqlite+aiosqlite://")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with session_factory() as session:
        yield session
    await engine.dispose()


def make_user(**overrides) -> User:
    defaults = dict(
        zenodo_user_id="3923",
        zenodo_env="production",
        display_name="Test User",
        access_token="test-token",
    )
    defaults.update(overrides)
    return User(**defaults)


def make_record(**overrides) -> ModelRecord:
    defaults = dict(
        slug="test-model",
        source="harvested",
        current_title="Test Model",
        current_summary="Test Model",
    )
    defaults.update(overrides)
    return ModelRecord(**defaults)


def make_version(record: ModelRecord, **overrides) -> ModelVersion:
    defaults = dict(
        version_doi="10.5281/zenodo.1",
        card_yaml="---\nsummary: Test Model\n---\n",
        card_body_md="",
        files=[],
        status="published",
        zenodo_env="production",
        schema_version="v1",
        is_placeholder=False,
        published_at=dt.datetime(2024, 1, 1, tzinfo=dt.timezone.utc),
    )
    defaults.update(overrides)
    version = ModelVersion(model_record=record, **defaults)
    return version
