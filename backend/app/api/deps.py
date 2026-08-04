from fastapi import Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.database import get_session
from backend.app.models import User


async def get_current_user(
    request: Request,
    db: AsyncSession = Depends(get_session),
) -> User:
    user_id = request.session.get("user_id")
    if not user_id:
        raise HTTPException(status_code=401, detail="未登录")
    user = await db.get(User, int(user_id))
    if user is None:
        raise HTTPException(status_code=401, detail="登录状态无效")
    return user
