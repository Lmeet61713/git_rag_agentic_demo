from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from backend.app.config import get_settings


class Base(DeclarativeBase):
    pass


engine = None
session_factory = None


def init_database() -> None:
    global engine, session_factory
    settings = get_settings()
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    engine = create_async_engine(settings.database_url, echo=False)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)


async def create_tables() -> None:
    if engine is None:
        init_database()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def get_session() -> AsyncIterator[AsyncSession]:
    if session_factory is None:
        init_database()
    async with session_factory() as session:
        yield session
