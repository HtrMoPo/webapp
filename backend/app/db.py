from pathlib import Path

from sqlalchemy import event
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.config import get_settings

settings = get_settings()

db_path = Path(settings.database_path)
db_path.parent.mkdir(parents=True, exist_ok=True)

engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}", echo=False)


@event.listens_for(engine.sync_engine, "connect")
def _set_sqlite_pragmas(dbapi_connection, connection_record) -> None:
    # With more than one uvicorn worker (see UVICORN_WORKERS), each is a
    # separate process opening its own connections to the same SQLite file.
    # WAL lets readers and a writer proceed concurrently instead of a writer
    # blocking every reader; busy_timeout makes a connection that does hit a
    # lock wait and retry instead of immediately raising "database is locked".
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA busy_timeout=5000")
    cursor.close()


async_session = async_sessionmaker(engine, expire_on_commit=False)


async def get_db():
    async with async_session() as session:
        yield session
