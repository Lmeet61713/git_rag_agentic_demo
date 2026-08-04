from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.api.deps import get_current_user
from backend.app.database import get_session
from backend.app.models import User
from backend.app.schemas import ModelConfigIn, ModelConfigOut
from backend.app.services import model_config

router = APIRouter()


@router.get("/model", response_model=list[ModelConfigOut])
async def get_model_configs(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
):
    configs = await model_config.list_configs(db, user.id)
    return [
        ModelConfigOut(
            id=item.id,
            provider=item.provider,
            model_name=item.model_name,
            base_url=item.base_url,
            is_active=item.is_active,
            has_api_key=bool(item.api_key_enc),
            updated_at=item.updated_at,
        )
        for item in configs
    ]


@router.put("/model", response_model=ModelConfigOut)
async def save_model_config(
    payload: ModelConfigIn,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
):
    item = await model_config.save_config(db, user.id, payload)
    return ModelConfigOut(
        id=item.id,
        provider=item.provider,
        model_name=item.model_name,
        base_url=item.base_url,
        is_active=item.is_active,
        has_api_key=bool(item.api_key_enc),
        updated_at=item.updated_at,
    )
