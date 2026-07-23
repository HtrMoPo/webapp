from pathlib import Path

from sqlalchemy import event
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.config import get_settings
from app.playground.models import Base

settings = get_settings()

db_path = Path(settings.playground_database_path)
db_path.parent.mkdir(parents=True, exist_ok=True)

# Separate engine/file from the main catalog DB (see app.db) -- playground
# data is ephemeral and high-churn (uploaded images, job results), unlike
# the versioned catalog schema Alembic manages.
engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}", echo=False)


@event.listens_for(engine.sync_engine, "connect")
def _set_sqlite_pragmas(dbapi_connection, connection_record) -> None:
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA busy_timeout=5000")
    cursor.close()


async_session = async_sessionmaker(engine, expire_on_commit=False)


async def get_db():
    async with async_session() as session:
        yield session


async def init_models() -> None:
    # No Alembic migrations for this DB: it's a single simple table with no
    # meaningful data to preserve across schema changes (rows are pruned
    # within a day anyway -- see app.playground.worker's cleanup loop), so a
    # plain create_all at startup is enough.
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
