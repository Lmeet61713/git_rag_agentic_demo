import shutil

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.api.deps import get_current_user
from backend.app.config import get_settings
from backend.app.database import get_session
from backend.app.models import IndexedFile, Repo, User
from backend.app.schemas import IndexJobOut, RepoOut
from backend.app.services import index_service, repo_service, sync_service, vector_store

router = APIRouter()


@router.get("", response_model=list[RepoOut])
async def list_user_repos(
    refresh: bool = False,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
):
    repos = await repo_service.list_repos(db, user.id)
    if refresh or not repos:
        try:
            await repo_service.sync_repos_from_github(db, user)
            repos = await repo_service.list_repos(db, user.id)
        except Exception as exc:
            raise HTTPException(status_code=502, detail=f"同步 GitHub 仓库失败：{exc}") from exc
    return [RepoOut.model_validate(repo) for repo in repos]


async def _get_repo(db: AsyncSession, user: User, owner: str, repo: str) -> Repo:
    result = await db.execute(
        select(Repo).where(
            Repo.user_id == user.id,
            Repo.owner == owner,
            Repo.repo == repo,
        )
    )
    item = result.scalar_one_or_none()
    if item is None:
        raise HTTPException(status_code=404, detail="仓库不存在")
    return item


@router.post("/{owner}/{repo}/index", response_model=IndexJobOut)
async def index_repo(
    owner: str,
    repo: str,
    background_tasks: BackgroundTasks,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
):
    item = await _get_repo(db, user, owner, repo)
    if item.index_status == "indexing":
        latest = await index_service.latest_job_for_repo(item.id)
        if latest and latest.status == "running":
            raise HTTPException(status_code=409, detail="该仓库正在索引中")
    job = await index_service.create_index_job(item.id)
    background_tasks.add_task(index_service.run_index_job, job.id)
    return IndexJobOut.model_validate(job)


@router.post("/{owner}/{repo}/reindex", response_model=IndexJobOut)
async def reindex_repo(
    owner: str,
    repo: str,
    background_tasks: BackgroundTasks,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
):
    return await index_repo(owner, repo, background_tasks, user, db)


@router.delete("/{owner}/{repo}/index")
async def delete_repo_index(
    owner: str,
    repo: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
):
    item = await _get_repo(db, user, owner, repo)
    project_id = f"{owner}/{repo}"
    store = vector_store.get_vector_store()
    await store.delete(project_id)
    await db.execute(IndexedFile.__table__.delete().where(IndexedFile.repo_id == item.id))
    item.index_status = "not_indexed"
    item.last_indexed_at = None
    await db.commit()
    mirror = sync_service.repo_mirror_path(owner, repo)
    resolved = mirror.resolve()
    data_root = get_settings().data_dir.resolve()
    if resolved != data_root and data_root in resolved.parents:
        shutil.rmtree(resolved, ignore_errors=True)
    return {"ok": True}
