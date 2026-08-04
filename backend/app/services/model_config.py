from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.config import get_settings
from backend.app.models import ModelConfig
from backend.app.schemas import ModelConfigIn
from backend.app.security import decrypt_secret, encrypt_secret


async def list_configs(db: AsyncSession, user_id: int) -> list[ModelConfig]:
    result = await db.execute(select(ModelConfig).where(ModelConfig.user_id == user_id))
    return list(result.scalars())


async def save_config(db: AsyncSession, user_id: int, data: ModelConfigIn) -> ModelConfig:
    result = await db.execute(
        select(ModelConfig).where(ModelConfig.user_id == user_id, ModelConfig.provider == data.provider)
    )
    config = result.scalar_one_or_none()
    if config is None:
        config = ModelConfig(user_id=user_id, provider=data.provider)
        db.add(config)
        await db.flush()
    config.model_name = data.model_name
    config.base_url = data.base_url
    if data.api_key:
        config.api_key_enc = encrypt_secret(data.api_key)
    config.is_active = data.is_active
    if data.is_active:
        await db.execute(ModelConfig.__table__.update().where(
            ModelConfig.user_id == user_id,
            ModelConfig.id != config.id,
        ).values(is_active=False))
    await db.commit()
    await db.refresh(config)
    return config


async def resolve_active(db: AsyncSession, user_id: int) -> dict | None:
    result = await db.execute(
        select(ModelConfig).where(ModelConfig.user_id == user_id, ModelConfig.is_active.is_(True))
    )
    config = result.scalar_one_or_none()
    if config is not None and config.api_key_enc:
        return {
            "provider": config.provider,
            "model": config.model_name,
            "api_key": decrypt_secret(config.api_key_enc),
            "base_url": config.base_url,
        }
    settings = get_settings()
    if settings.deepseek_api_key and settings.deepseek_model:
        return {
            "provider": "deepseek",
            "model": settings.deepseek_model,
            "api_key": settings.deepseek_api_key,
            "base_url": settings.deepseek_base_url,
        }
    if settings.dashscope_api_key and settings.dashscope_model:
        return {
            "provider": "dashscope",
            "model": settings.dashscope_model,
            "api_key": settings.dashscope_api_key,
            "base_url": settings.dashscope_base_url,
        }
    return None
