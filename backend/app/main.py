import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.sessions import SessionMiddleware

from backend.app.api import auth, chat, config, files, jobs, memory, repos, search
from backend.app.config import get_settings
from backend.app.database import create_tables, init_database


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_database()
    await create_tables()
    yield


def create_app() -> FastAPI:
    settings = get_settings()
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        filename=settings.data_dir / "backend.log",
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        encoding="utf-8",
    )
    app = FastAPI(title=settings.app_name, lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[
            settings.frontend_origin,
            "http://localhost:5173",
            "http://127.0.0.1:5173",
            "http://localhost:5174",
            "http://127.0.0.1:5174",
        ],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.add_middleware(
        SessionMiddleware,
        secret_key=settings.session_secret,
        max_age=3600 * 24 * 7,
        same_site="lax",
    )

    app.include_router(auth.router, prefix="/api/auth", tags=["auth"])
    app.include_router(repos.router, prefix="/api/repos", tags=["repos"])
    app.include_router(jobs.router, prefix="/api/jobs", tags=["jobs"])
    app.include_router(search.router, prefix="/api", tags=["search"])
    app.include_router(chat.router, prefix="/api", tags=["chat"])
    app.include_router(files.router, prefix="/api/files", tags=["files"])
    app.include_router(config.router, prefix="/api/config", tags=["config"])
    app.include_router(memory.router, prefix="/api/memory", tags=["memory"])

    @app.get("/api/health")
    async def health():
        return {"status": "ok", "app": settings.app_name}

    return app


app = create_app()
