from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.config import get_settings
from backend.app.models import ChatMessage, ChatSession, MemoryEntry
from backend.app.services.embedding import chinese_tokens


async def ensure_session(db: AsyncSession, user_id: int, session_id: int | None = None) -> ChatSession:
    if session_id is not None:
        session = await db.get(ChatSession, session_id)
        if session is not None and session.user_id == user_id:
            return session
    session = ChatSession(user_id=user_id, title="新会话")
    db.add(session)
    await db.commit()
    await db.refresh(session)
    return session


async def list_sessions(db: AsyncSession, user_id: int) -> list[ChatSession]:
    result = await db.execute(
        select(ChatSession)
        .where(ChatSession.user_id == user_id)
        .order_by(ChatSession.id.desc())
    )
    return list(result.scalars())


async def create_session(db: AsyncSession, user_id: int, title: str = "新会话") -> ChatSession:
    session = ChatSession(user_id=user_id, title=title)
    db.add(session)
    await db.commit()
    await db.refresh(session)
    return session


async def get_owned_session(
    db: AsyncSession,
    user_id: int,
    session_id: int,
) -> ChatSession | None:
    result = await db.execute(
        select(ChatSession).where(
            ChatSession.id == session_id,
            ChatSession.user_id == user_id,
        )
    )
    return result.scalar_one_or_none()


async def rename_session(
    db: AsyncSession,
    session: ChatSession,
    title: str,
) -> ChatSession:
    session.title = title
    await db.commit()
    await db.refresh(session)
    return session


async def delete_session(db: AsyncSession, session: ChatSession) -> None:
    await db.execute(delete(ChatMessage).where(ChatMessage.session_id == session.id))
    await db.delete(session)
    await db.commit()


async def save_message(
    db: AsyncSession,
    session_id: int,
    role: str,
    content: str,
    sources: list | None = None,
    tool: str = "search",
    mode: str = "llm",
) -> ChatMessage:
    message = ChatMessage(
        session_id=session_id,
        role=role,
        content=content,
        sources=sources or [],
        tool=tool,
        mode=mode,
    )
    db.add(message)
    await db.commit()
    await db.refresh(message)
    return message


async def recent_messages(db: AsyncSession, session_id: int, limit: int = 20) -> list[ChatMessage]:
    result = await db.execute(
        select(ChatMessage)
        .where(ChatMessage.session_id == session_id)
        .order_by(ChatMessage.id.desc())
        .limit(limit)
    )
    return list(reversed(list(result.scalars())))


async def recall_long_term(
    db: AsyncSession,
    user_id: int,
    query: str,
    project_id: str | None = None,
    top_k: int | None = None,
) -> list[MemoryEntry]:
    top_k = top_k or get_settings().memory_top_k
    stmt = select(MemoryEntry).where(MemoryEntry.user_id == user_id, MemoryEntry.type == "long_term")
    if project_id:
        stmt = stmt.where(MemoryEntry.project_id == project_id)
    entries = list((await db.execute(stmt)).scalars())
    query_tokens = {token for token in chinese_tokens(query)}
    if not query_tokens:
        query_tokens = {token for token in query.lower().split() if len(token) > 1}
    if not query_tokens:
        return []
    scored = []
    for entry in entries:
        score = 0.0
        content = entry.content.lower()
        for token in query_tokens:
            if token in content:
                score += 1.0
        if score > 0:
            scored.append((entry, score))
    scored.sort(key=lambda item: item[1], reverse=True)
    return [entry for entry, score in scored[:top_k]]


async def save_long_term_memory(
    db: AsyncSession,
    user_id: int,
    content: str,
    project_id: str | None = None,
    session_id: int | None = None,
) -> MemoryEntry:
    entry = MemoryEntry(
        user_id=user_id,
        session_id=session_id,
        project_id=project_id,
        type="long_term",
        content=content,
    )
    db.add(entry)
    await db.commit()
    await db.refresh(entry)
    return entry


async def list_memory(
    db: AsyncSession,
    user_id: int,
    project_id: str | None = None,
    session_id: int | None = None,
    memory_type: str | None = None,
) -> list[MemoryEntry]:
    stmt = select(MemoryEntry).where(MemoryEntry.user_id == user_id)
    if project_id is not None:
        stmt = stmt.where(MemoryEntry.project_id == project_id)
    if session_id is not None:
        stmt = stmt.where(MemoryEntry.session_id == session_id)
    if memory_type is not None:
        stmt = stmt.where(MemoryEntry.type == memory_type)
    stmt = stmt.order_by(MemoryEntry.updated_at.desc(), MemoryEntry.id.desc())
    return list((await db.execute(stmt)).scalars())


async def create_memory(
    db: AsyncSession,
    user_id: int,
    content: str,
    project_id: str | None = None,
    session_id: int | None = None,
    memory_type: str = "long_term",
) -> MemoryEntry:
    entry = MemoryEntry(
        user_id=user_id,
        project_id=project_id,
        session_id=session_id,
        type=memory_type,
        content=content,
    )
    db.add(entry)
    await db.commit()
    await db.refresh(entry)
    return entry


async def get_owned_memory(db: AsyncSession, user_id: int, memory_id: int) -> MemoryEntry | None:
    result = await db.execute(
        select(MemoryEntry).where(MemoryEntry.id == memory_id, MemoryEntry.user_id == user_id)
    )
    return result.scalar_one_or_none()


async def update_memory(
    db: AsyncSession,
    entry: MemoryEntry,
    content: str | None = None,
    project_id: str | None = None,
    session_id: int | None = None,
    memory_type: str | None = None,
) -> MemoryEntry:
    if content is not None:
        entry.content = content
    if project_id is not None:
        entry.project_id = project_id
    if session_id is not None:
        entry.session_id = session_id
    if memory_type is not None:
        entry.type = memory_type
    await db.commit()
    await db.refresh(entry)
    return entry


async def delete_memory(db: AsyncSession, entry: MemoryEntry) -> None:
    await db.delete(entry)
    await db.commit()


async def maybe_save_summary(db: AsyncSession, user_id: int, session_id: int) -> None:
    messages = await recent_messages(db, session_id, limit=100)
    if len(messages) < 8 or len(messages) % 8 != 0:
        return
    content = "会话摘要：" + " ".join(f"{item.role}: {item.content[:200]}" for item in messages[-8:])
    result = await db.execute(
        select(MemoryEntry).where(
            MemoryEntry.user_id == user_id,
            MemoryEntry.session_id == session_id,
            MemoryEntry.type == "long_term",
            MemoryEntry.content.like("会话摘要：%"),
        )
    )
    existing = result.scalars().first()
    if existing is None:
        await save_long_term_memory(db, user_id, content, session_id=session_id)
        return
    existing.content = content
    await db.commit()
    await db.refresh(existing)
