from collections.abc import AsyncIterator

from sqlalchemy import text
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
    if engine.url.drivername.startswith("sqlite"):
        async with engine.begin() as conn:
            result = await conn.execute(text("PRAGMA table_info(repos)"))
            columns = {row["name"] for row in result.mappings()}
            for column_name, column_type in (
                ("summary", "TEXT"),
                ("github_created_at", "VARCHAR(64)"),
            ):
                if column_name not in columns:
                    await conn.execute(
                        text(f"ALTER TABLE repos ADD COLUMN {column_name} {column_type}")
                    )

            result = await conn.execute(text("PRAGMA table_info(chat_messages)"))
            columns = {row["name"] for row in result.mappings()}
            for column_name, column_type, default in (
                ("tool", "VARCHAR(32)", "'search'"),
                ("mode", "VARCHAR(32)", "'llm'"),
            ):
                if column_name not in columns:
                    await conn.execute(
                        text(
                            f"ALTER TABLE chat_messages ADD COLUMN "
                            f"{column_name} {column_type} DEFAULT {default}"
                        )
                    )


async def get_session() -> AsyncIterator[AsyncSession]:
    if session_factory is None:
        init_database()
    async with session_factory() as session:
        yield session
