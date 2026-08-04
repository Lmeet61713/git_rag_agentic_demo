import json

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.api.deps import get_current_user
from backend.app.database import get_session
from backend.app.models import User
from backend.app.schemas import ChatRequest, ChatResponse, SearchSource
from backend.app.services import agent

router = APIRouter()


@router.post("/chat", response_model=ChatResponse)
async def chat(
    payload: ChatRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
):
    session_id, answer, sources = await agent.ask(
        db, user.id, payload.message, payload.session_id
    )
    return ChatResponse(
        session_id=session_id,
        answer=answer,
        sources=[SearchSource.model_validate(item) for item in sources],
    )


@router.post("/chat/stream")
async def chat_stream(
    payload: ChatRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
):
    async def event_source():
        yield "event: start\ndata: {}\n\n"
        session_id, answer, sources = await agent.ask(
            db, user.id, payload.message, payload.session_id
        )
        message_event = json.dumps(
            {"session_id": session_id, "content": answer},
            ensure_ascii=False,
        )
        yield f"event: message\ndata: {message_event}\n\n"
        sources_event = json.dumps({"sources": sources}, ensure_ascii=False)
        yield f"event: sources\ndata: {sources_event}\n\n"
        yield "event: done\ndata: {}\n\n"

    return StreamingResponse(event_source(), media_type="text/event-stream")
