import logging
import secrets

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.config import get_settings
from backend.app.database import get_session
from backend.app.models import User
from backend.app.schemas import UserOut
from backend.app.security import encrypt_secret
from backend.app.services.github import GitHubClient, exchange_github_code

logger = logging.getLogger(__name__)

router = APIRouter()

OAUTH_ERROR_CODES = {
    "bad_verification_code": "oauth_code_expired",
    "incorrect_client_credentials": "oauth_config_error",
    "redirect_uri_mismatch": "oauth_callback_mismatch",
}


@router.get("/login")
async def login(request: Request):
    settings = get_settings()
    if not settings.github_client_id:
        raise HTTPException(status_code=503, detail="GitHub OAuth 尚未配置，请先填写 GITHUB_CLIENT_ID")
    state = secrets.token_urlsafe(16)
    request.session["oauth_state"] = state
    url = (
        "https://github.com/login/oauth/authorize"
        f"?client_id={settings.github_client_id}"
        f"&redirect_uri={settings.github_callback_url}"
        "&scope=read:user"
        f"&state={state}"
    )
    return {"login_url": url}


@router.get("/callback")
async def callback(
    request: Request,
    code: str = "",
    state: str = "",
    db: AsyncSession = Depends(get_session),
):
    settings = get_settings()
    if not code or not state or request.session.get("oauth_state") != state:
        return RedirectResponse(f"{settings.frontend_origin}/login?error=invalid_state")
    try:
        token_data = await exchange_github_code(code)
        access_token = token_data.get("access_token")
        if not access_token:
            logger.warning("GitHub token exchange returned no access_token: %s", token_data)
            error_code = OAUTH_ERROR_CODES.get(token_data.get("error"), "oauth_failed")
            return RedirectResponse(f"{settings.frontend_origin}/login?error={error_code}")
        github = GitHubClient(access_token)
        github_user = await github.get_user()
        result = await db.execute(select(User).where(User.github_id == str(github_user["id"])))
        user = result.scalar_one_or_none()
        if user is None:
            user = User(github_id=str(github_user["id"]))
            db.add(user)
        user.username = github_user.get("login", "")
        user.avatar_url = github_user.get("avatar_url")
        user.access_token_enc = encrypt_secret(access_token)
        await db.commit()
        await db.refresh(user)
        request.session.clear()
        request.session["user_id"] = user.id
        return RedirectResponse(f"{settings.frontend_origin}/repos")
    except Exception:
        logger.exception("GitHub OAuth callback failed")
        return RedirectResponse(f"{settings.frontend_origin}/login?error=oauth_failed")


@router.get("/me")
async def me(request: Request, db: AsyncSession = Depends(get_session)):
    user_id = request.session.get("user_id")
    if not user_id:
        return {"user": None}
    user = await db.get(User, int(user_id))
    if user is None:
        return {"user": None}
    return {"user": UserOut.model_validate(user)}


@router.post("/logout")
async def logout(request: Request):
    request.session.clear()
    return {"ok": True}
