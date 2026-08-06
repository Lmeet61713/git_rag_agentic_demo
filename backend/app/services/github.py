import logging

import httpx

from backend.app.config import get_settings

logger = logging.getLogger(__name__)


class GitHubClient:
    def __init__(self, token: str):
        self.token = token
        self.settings = get_settings()

    def _headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self.token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }

    async def _get(self, path: str, params: dict | None = None) -> list | dict:
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.get(
                f"{self.settings.github_api_base}{path}",
                headers=self._headers(),
                params=params,
            )
            response.raise_for_status()
            return response.json()

    async def get_user(self) -> dict:
        return await self._get("/user")

    async def list_public_repos(self) -> list[dict]:
        repos: list[dict] = []
        page = 1
        while True:
            data = await self._get(
                "/user/repos",
                params={
                    "per_page": 100,
                    "page": page,
                    "affiliation": "owner",
                    "visibility": "public",
                },
            )
            if not isinstance(data, list):
                break
            repos.extend(data)
            if len(data) < 100:
                break
            page += 1
        return repos

    async def get_default_branch(self, owner: str, repo: str) -> str:
        data = await self._get(f"/repos/{owner}/{repo}")
        if isinstance(data, dict):
            return data.get("default_branch") or "main"
        return "main"

    async def get_repo(self, owner: str, repo: str) -> dict:
        data = await self._get(f"/repos/{owner}/{repo}")
        if not isinstance(data, dict):
            raise TypeError(f"GitHub 仓库不存在：{owner}/{repo}")
        return data


async def exchange_github_code(code: str) -> dict:
    settings = get_settings()
    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.post(
            "https://github.com/login/oauth/access_token",
            json={
                "client_id": settings.github_client_id,
                "client_secret": settings.github_client_secret,
                "code": code,
                "redirect_uri": settings.github_callback_url,
            },
            headers={"Accept": "application/json"},
        )
        try:
            data = response.json()
        except Exception:
            data = {"raw_body": response.text[:500]}
        logger.warning("GitHub token exchange: status=%s body=%s", response.status_code, data)
        response.raise_for_status()
        return data
