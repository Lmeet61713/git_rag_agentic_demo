from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.api.deps import get_current_user
from backend.app.database import get_session
from backend.app.models import User
from backend.app.schemas import MemoryEntryIn, MemoryEntryOut, MemoryEntryUpdate
from backend.app.services import memory

router = APIRouter()


@router.get("", response_model=list[MemoryEntryOut])
async def list_memory(
    project_id: str | None = None,
    session_id: int | None = None,
    type: str | None = None,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
):
    entries = await memory.list_memory(
        db,
        user.id,
        project_id=project_id,
        session_id=session_id,
        memory_type=type,
    )
    return [MemoryEntryOut.model_validate(item) for item in entries]


@router.post("", response_model=MemoryEntryOut)
async def create_memory(
    payload: MemoryEntryIn,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
):
    entry = await memory.create_memory(
        db,
        user.id,
        payload.content,
        project_id=payload.project_id,
        session_id=payload.session_id,
        memory_type=payload.type,
    )
    return MemoryEntryOut.model_validate(entry)


@router.put("/{memory_id}", response_model=MemoryEntryOut)
async def update_memory(
    memory_id: int,
    payload: MemoryEntryUpdate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
):
    entry = await memory.get_owned_memory(db, user.id, memory_id)
    if entry is None:
        raise HTTPException(status_code=404, detail="记忆不存在")
    entry = await memory.update_memory(
        db,
        entry,
        content=payload.content,
        project_id=payload.project_id,
        session_id=payload.session_id,
        memory_type=payload.type,
    )
    return MemoryEntryOut.model_validate(entry)


@router.delete("/{memory_id}")
async def delete_memory(
    memory_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
):
    entry = await memory.get_owned_memory(db, user.id, memory_id)
    if entry is None:
        raise HTTPException(status_code=404, detail="记忆不存在")
    await memory.delete_memory(db, entry)
    return {"ok": True}
