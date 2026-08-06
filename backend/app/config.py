from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT_DIR = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=ROOT_DIR / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "MyAgentic"
    host: str = "127.0.0.1"
    port: int = 8000
    data_dir: Path = ROOT_DIR / "data"
    chroma_dir: Path = ROOT_DIR / "storage" / "chroma"
    database_url: str = f"sqlite+aiosqlite:///{(ROOT_DIR / 'data' / 'app.db').as_posix()}"
    github_client_id: str = ""
    github_client_secret: str = ""
    github_callback_url: str = "http://127.0.0.1:8000/api/auth/callback"
    session_secret: str = "change-me"
    app_secret_key: str = "change-me"
    embedding_model_path: str = ""
    embedding_batch_size: int = 32
    search_min_score: float = 0.25
    search_top1_gap: float = 0.15
    deepseek_api_key: str = ""
    deepseek_base_url: str = "https://api.deepseek.com"
    deepseek_model: str = ""
    dashscope_api_key: str = ""
    dashscope_base_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    dashscope_model: str = ""
    dashscope_vl_model: str = ""
    ollama_base_url: str = "http://127.0.0.1:11434"
    ollama_models_dir: Path = Path("E:/mmmmmmmmmmmmmmmm/ollama_cache/manifests/registry.ollama.ai/library")
    frontend_origin: str = "http://127.0.0.1:5173"
    github_api_base: str = "https://api.github.com"
    git_bin: str = "git"
    max_repo_size_mb: int = 500
    max_file_size_mb: int = 5
    chunk_size: int = 800
    chunk_overlap: int = 100
    memory_top_k: int = 5
    search_top_k: int = 8


@lru_cache
def get_settings() -> Settings:
    return Settings()
