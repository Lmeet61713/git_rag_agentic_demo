import asyncio
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.config import get_settings
from backend.app.models import SyncLog


def repo_mirror_path(owner: str, repo: str) -> Path:
    settings = get_settings()
    return settings.data_dir / "repos" / owner / repo


async def _run_git(args: list[str], cwd: Path | None = None) -> str:
    settings = get_settings()
    if cwd is not None:
        cwd.mkdir(parents=True, exist_ok=True)
    process = await asyncio.create_subprocess_exec(
        settings.git_bin,
        *args,
        cwd=str(cwd) if cwd else None,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await process.communicate()
    if process.returncode != 0:
        raise RuntimeError(stderr.decode("utf-8", errors="replace"))
    return stdout.decode("utf-8", errors="replace").strip()


async def clone_repo(owner: str, repo: str) -> str:
    target = repo_mirror_path(owner, repo)
    url = f"https://github.com/{owner}/{repo}.git"
    if (target / ".git").exists():
        return await refresh_repo(owner, repo, target)
    await _run_git(["clone", "--depth", "1", url, str(target)])
    return await current_commit(target)


async def refresh_repo(owner: str, repo: str, target: Path | None = None) -> str:
    target = target or repo_mirror_path(owner, repo)
    await _run_git(["fetch", "origin"], cwd=target)
    branch = await _run_git(["rev-parse", "--abbrev-ref", "HEAD"], cwd=target)
    await _run_git(["reset", "--hard", f"origin/{branch}"], cwd=target)
    return await current_commit(target)


async def current_commit(target: Path) -> str:
    return await _run_git(["rev-parse", "HEAD"], cwd=target)


def repo_size_mb(target: Path) -> float:
    total = 0
    for path in target.rglob("*"):
        try:
            if path.is_file():
                total += path.stat().st_size
        except OSError:
            continue
    return total / (1024 * 1024)


async def record_sync_log(
    db: AsyncSession,
    repo_id: int,
    action: str = "sync",
    status: str = "success",
    message: str = "",
    commit_sha: str | None = None,
) -> SyncLog:
    entry = SyncLog(
        repo_id=repo_id,
        action=action,
        status=status,
        message=message,
        commit_sha=commit_sha,
    )
    db.add(entry)
    await db.commit()
    await db.refresh(entry)
    return entry


async def list_sync_logs(db: AsyncSession, repo_id: int, limit: int = 50) -> list[SyncLog]:
    result = await db.execute(
        select(SyncLog)
        .where(SyncLog.repo_id == repo_id)
        .order_by(SyncLog.id.desc())
        .limit(limit)
    )
    return list(reversed(list(result.scalars())))
