from pathlib import Path

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.config import get_settings

settings = get_settings()

db_path = Path(settings.database_path)
db_path.parent.mkdir(parents=True, exist_ok=True)

engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}", echo=False)
async_session = async_sessionmaker(engine, expire_on_commit=False)


async def get_db():
    async with async_session() as session:
        yield session
