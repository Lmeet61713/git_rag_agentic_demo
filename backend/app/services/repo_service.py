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
        saved.append(repo)

    await db.commit()
    return saved


async def list_repos(db: AsyncSession, user_id: int) -> list[Repo]:
    result = await db.execute(
        select(Repo).where(Repo.user_id == user_id).order_by(Repo.full_name)
    )
    return list(result.scalars())
