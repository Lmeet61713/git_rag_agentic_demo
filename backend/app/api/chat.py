import json

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.api.deps import get_current_user
from backend.app.database import get_session
from backend.app.models import User
from backend.app.schemas import (
    ChatMessageOut,
    ChatRequest,
    ChatResponse,
    ChatSessionCreate,
    ChatSessionOut,
    ChatSessionUpdate,
    SearchSource,
)
from backend.app.services import agent, memory

router = APIRouter()


def _answer_mode(answer: str) -> str:
    if answer.startswith(("当前 DeepSeek 模型配置", "当前 阿里云 DashScope 模型配置")):
        return "config_error"
    if "本地检索兜底" in answer or answer.startswith(
        ("当前未配置可用模型", "未找到与问题相关", "当前模型")
    ):
        return "fallback"
    return "llm"


@router.get("/chat/sessions", response_model=list[ChatSessionOut])
async def list_sessions(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
):
    sessions = await memory.list_sessions(db, user.id)
    return [ChatSessionOut.model_validate(session) for session in sessions]


@router.post("/chat/sessions", response_model=ChatSessionOut)
async def create_session(
    payload: ChatSessionCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
):
    session = await memory.create_session(db, user.id, payload.title)
    return ChatSessionOut.model_validate(session)


@router.get("/chat/sessions/{session_id}/messages", response_model=list[ChatMessageOut])
async def session_messages(
    session_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
):
    session = await memory.get_owned_session(db, user.id, session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="会话不存在")
    messages = await memory.recent_messages(db, session.id, limit=200)
    return [ChatMessageOut.model_validate(item) for item in messages]


@router.put("/chat/sessions/{session_id}", response_model=ChatSessionOut)
async def rename_session(
    session_id: int,
    payload: ChatSessionUpdate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
):
    session = await memory.get_owned_session(db, user.id, session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="会话不存在")
    session = await memory.rename_session(db, session, payload.title)
    return ChatSessionOut.model_validate(session)


@router.delete("/chat/sessions/{session_id}")
async def delete_session(
    session_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
):
    session = await memory.get_owned_session(db, user.id, session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="会话不存在")
    await memory.delete_session(db, session)
    return {"ok": True}


@router.post("/chat", response_model=ChatResponse)
async def chat(
    payload: ChatRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
):
    session_id, answer, sources, tool = await agent.ask(
        db, user.id, payload.message, payload.session_id
    )
    return ChatResponse(
        session_id=session_id,
        answer=answer,
        sources=[SearchSource.model_validate(item) for item in sources],
        mode=_answer_mode(answer),
        tool=tool,
    )


@router.post("/chat/stream")
async def chat_stream(
    payload: ChatRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
):
    async def event_source():
        async for event in agent.ask_stream(db, user.id, payload.message, payload.session_id):
            event_name = event["type"]
            if event_name == "start":
                yield f"event: start\ndata: {json.dumps({'session_id': event.get('session_id')}, ensure_ascii=False)}\n\n"
            elif event_name == "token":
                yield f"event: token\ndata: {json.dumps({'content': event['content']}, ensure_ascii=False)}\n\n"
            elif event_name == "tool":
                yield f"event: tool\ndata: {json.dumps({'tool': event['tool']}, ensure_ascii=False)}\n\n"
            elif event_name == "sources":
                yield f"event: sources\ndata: {json.dumps({'sources': event['sources']}, ensure_ascii=False)}\n\n"
            elif event_name == "done":
                yield f"event: done\ndata: {json.dumps({'session_id': event.get('session_id'), 'mode': event.get('mode'), 'tool': event.get('tool')}, ensure_ascii=False)}\n\n"

    return StreamingResponse(event_source(), media_type="text/event-stream")
