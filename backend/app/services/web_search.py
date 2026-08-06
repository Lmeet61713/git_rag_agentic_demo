import logging

import httpx

logger = logging.getLogger(__name__)


async def tavily_search(
    query: str,
    api_key: str,
    base_url: str = "https://api.tavily.com",
    max_results: int = 5,
) -> list[dict]:
    url = f"{base_url.rstrip('/')}/search"
    payload = {
        "api_key": api_key,
        "query": query,
        "max_results": max_results,
        "search_depth": "basic",
    }
    async with httpx.AsyncClient(timeout=20) as client:
        response = await client.post(url, json=payload)
        response.raise_for_status()
        data = response.json()
    results = []
    for index, item in enumerate(data.get("results", [])[:max_results]):
        title = item.get("title", "")
        content = item.get("content", "")
        text = f"{title}\n{content}".strip()
        if not text:
            continue
        results.append(
            {
                "project_id": "web",
                "path": item.get("url", ""),
                "file_type": "web",
                "language": None,
                "text": text,
                "score": max(1.0 - index * 0.08, 0.5),
            }
        )
    return results
