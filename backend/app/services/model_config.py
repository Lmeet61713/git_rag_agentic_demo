import logging

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.config import get_settings
from backend.app.models import ModelConfig
from backend.app.schemas import ModelConfigIn
from backend.app.security import decrypt_secret, encrypt_secret

DEEPSEEK_MODELS = [
    "deepseek-v4-flash",
    "deepseek-v4-pro",
    "deepseek-chat",
    "deepseek-reasoner",
]
DASHSCOPE_MODELS = [
    "qwen3.7-max",
    "qwen3.7-plus",
    "qwen3.6-flash",
    "qwen3.5-plus",
    "qwen3.5-flash",
    "qwen3-max",
    "qwen3-vl-plus",
    "qwen3-vl-max",
    "qwen-turbo",
    "qwen-plus",
    "qwen-max",
    "qwen-long",
    "qwen-vl-plus",
    "qwen-vl-max",
]
TAVILY_MODELS = ["web_search"]

logger = logging.getLogger(__name__)


def _provider_default_base_url(provider: str) -> str:
    settings = get_settings()
    if provider == "deepseek":
        return settings.deepseek_base_url
    if provider == "dashscope":
        return settings.dashscope_base_url
    if provider == "ollama":
        return settings.ollama_base_url
    if provider == "tavily":
        return settings.tavily_base_url
    return ""


async def _list_ollama_models() -> list[str]:
    settings = get_settings()
    try:
        async with httpx.AsyncClient(timeout=3) as client:
            response = await client.get(f"{settings.ollama_base_url.rstrip('/')}/api/tags")
            response.raise_for_status()
            names = [
                item.get("name")
                for item in response.json().get("models", [])
                if item.get("name")
            ]
            if names:
                return sorted(names)
    except Exception as exc:
        logger.warning("Ollama model list unavailable, fallback to manifest dir: %s", exc)
    if settings.ollama_models_dir.is_dir():
        return sorted(item.name for item in settings.ollama_models_dir.iterdir() if item.is_dir())
    return []


async def model_catalog() -> list[dict]:
    settings = get_settings()
    return [
        {
            "provider": "deepseek",
            "label": "DeepSeek",
            "models": DEEPSEEK_MODELS,
            "base_url": settings.deepseek_base_url,
            "requires_api_key": True,
        },
        {
            "provider": "dashscope",
            "label": "阿里云 DashScope",
            "models": DASHSCOPE_MODELS,
            "base_url": settings.dashscope_base_url,
            "requires_api_key": True,
        },
        {
            "provider": "ollama",
            "label": "本地 Ollama",
            "models": await _list_ollama_models(),
            "base_url": settings.ollama_base_url,
            "requires_api_key": False,
        },
        {
            "provider": "tavily",
            "label": "Tavily 联网搜索",
            "models": TAVILY_MODELS,
            "base_url": settings.tavily_base_url,
            "requires_api_key": True,
        },
    ]


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
    if data.provider == "tavily":
        config.is_active = False
    else:
        config.is_active = data.is_active
    if data.is_active and data.provider != "tavily":
        await db.execute(ModelConfig.__table__.update().where(
            ModelConfig.user_id == user_id,
            ModelConfig.id != config.id,
        ).values(is_active=False))
    await db.commit()
    await db.refresh(config)
    return config


async def resolve_active(db: AsyncSession, user_id: int) -> dict | None:
    result = await db.execute(
        select(ModelConfig).where(
            ModelConfig.user_id == user_id,
            ModelConfig.is_active.is_(True),
            ModelConfig.provider != "tavily",
        )
    )
    config = result.scalar_one_or_none()
    if config is not None:
        api_key = ""
        config_error = None
        try:
            if config.api_key_enc:
                api_key = decrypt_secret(config.api_key_enc)
        except Exception:
            logger.exception("resolve_active decrypt failed for user=%s", user_id)
            config_error = "invalid_api_key"
        if config.provider != "ollama" and not api_key:
            config_error = config_error or "missing_api_key"
        if config.provider == "ollama" or api_key or config_error:
            return {
                "provider": config.provider,
                "model": config.model_name,
                "api_key": api_key,
                "base_url": config.base_url or _provider_default_base_url(config.provider),
                "config_error": config_error,
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


async def resolve_web_search(db: AsyncSession, user_id: int) -> dict | None:
    result = await db.execute(
        select(ModelConfig).where(
            ModelConfig.user_id == user_id,
            ModelConfig.provider == "tavily",
        )
    )
    config = result.scalar_one_or_none()
    api_key = ""
    config_error = None
    base_url = config.base_url if config and config.base_url else get_settings().tavily_base_url
    if config and config.api_key_enc:
        try:
            api_key = decrypt_secret(config.api_key_enc)
        except Exception:
            logger.exception("resolve_web_search decrypt failed for user=%s", user_id)
            config_error = "invalid_api_key"
    if not api_key:
        api_key = get_settings().tavily_api_key
    if not api_key:
        return None
    return {
        "provider": "tavily",
        "api_key": api_key,
        "base_url": base_url,
        "config_error": config_error,
    }


async def resolve_fallback(db: AsyncSession, user_id: int) -> dict | None:
    """Return the local Ollama config as a backup when remote LLM calls fail."""
    result = await db.execute(
        select(ModelConfig)
        .where(
            ModelConfig.user_id == user_id,
            ModelConfig.provider == "ollama",
            ModelConfig.model_name != "",
        )
        .order_by(ModelConfig.is_active.desc(), ModelConfig.id.desc())
    )
    configs = list(result.scalars())
    if not configs:
        return None
    config = configs[0]
    return {
        "provider": "ollama",
        "model": config.model_name,
        "api_key": "",
        "base_url": config.base_url or _provider_default_base_url("ollama"),
        "config_error": None,
    }
