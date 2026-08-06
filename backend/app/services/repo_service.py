from urllib.parse import urlparse

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.models import Repo, User
from backend.app.security import decrypt_secret
from backend.app.services.github import GitHubClient


def normalize_repo(repo: dict) -> dict:
    full_name = repo.get("full_name") or ""
    owner, _, name = full_name.partition("/")
    return {
        "owner": owner or repo.get("owner", {}).get("login", ""),
        "repo": name or repo.get("name", ""),
        "full_name": full_name,
        "html_url": repo.get("html_url") or "",
        "default_branch": repo.get("default_branch") or "main",
        "github_created_at": repo.get("created_at") or "",
    }


async def sync_repos_from_github(db: AsyncSession, user: User) -> list[Repo]:
    token = decrypt_secret(user.access_token_enc)
    if not token:
        raise ValueError("GitHub token is missing for user")
    client = GitHubClient(token)
    remote_repos = await client.list_public_repos()

    result = await db.execute(select(Repo).where(Repo.user_id == user.id))
    existing = {repo.full_name: repo for repo in result.scalars()}
    saved: list[Repo] = []

    for item in remote_repos:
        data = normalize_repo(item)
        if not data["full_name"]:
            continue
        repo = existing.get(data["full_name"])
        if repo is None:
            repo = Repo(user_id=user.id, index_status="not_indexed")
            db.add(repo)
        repo.owner = data["owner"]
        repo.repo = data["repo"]
        repo.full_name = data["full_name"]
        repo.html_url = data["html_url"]
        repo.default_branch = data["default_branch"]
        repo.github_created_at = data["github_created_at"] or None
        saved.append(repo)

    await db.commit()
    return saved


def parse_repo_url(url: str) -> tuple[str, str]:
    value = url.strip()
    if not value:
        raise ValueError("仓库链接不能为空")
    if "/" in value and "://" not in value and "." not in value.split("/", 1)[0]:
        parts = [part for part in value.split("/") if part]
        if len(parts) >= 2:
            return parts[0], parts[1].removesuffix(".git")
    if "/" in value and not value.startswith("http"):
        value = f"https://{value}"
    parsed = urlparse(value)
    if parsed.netloc not in {"github.com", "www.github.com"}:
        raise ValueError("仅支持 github.com 公开仓库链接")
    parts = [part for part in parsed.path.strip("/").split("/") if part]
    if len(parts) < 2:
        raise ValueError("链接格式应为 https://github.com/owner/repo")
    owner = parts[0]
    repo = parts[1].removesuffix(".git")
    if not owner or not repo:
        raise ValueError("链接缺少 owner 或 repo")
    return owner, repo


async def import_repo(db: AsyncSession, user: User, owner: str, repo: str) -> Repo:
    token = decrypt_secret(user.access_token_enc)
    if not token:
        raise ValueError("GitHub token is missing for user")
    client = GitHubClient(token)
    remote = await client.get_repo(owner, repo)
    data = normalize_repo(remote)
    if not data["full_name"]:
        raise ValueError("无法解析仓库元数据")
    result = await db.execute(
        select(Repo).where(
            Repo.user_id == user.id,
            Repo.owner == data["owner"],
            Repo.repo == data["repo"],
        )
    )
    item = result.scalar_one_or_none()
    if item is None:
        item = Repo(user_id=user.id, index_status="not_indexed")
        db.add(item)
    item.owner = data["owner"]
    item.repo = data["repo"]
    item.full_name = data["full_name"]
    item.html_url = data["html_url"]
    item.default_branch = data["default_branch"]
    item.github_created_at = data["github_created_at"] or None
    await db.commit()
    await db.refresh(item)
    return item


async def list_repos(db: AsyncSession, user_id: int) -> list[Repo]:
    result = await db.execute(
        select(Repo).where(Repo.user_id == user_id).order_by(Repo.full_name)
    )
    return list(result.scalars())
