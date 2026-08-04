import re

from backend.app.config import get_settings
from backend.app.services import vector_store
from backend.app.services.embedding import get_embedding


def _keyword_score(query: str, text: str, path: str) -> float:
    tokens = {token for token in re.findall(r"[\w\u4e00-\u9fff]+", query.lower()) if len(token) > 1}
    if not tokens:
        return 0.0
    text_lower = text.lower()
    path_lower = path.lower()
    score = 0.0
    for token in tokens:
        if token in text_lower:
            score += 1.0
        if token in path_lower:
            score += 2.0
    return score / len(tokens)


def _readmeish(path: str) -> bool:
    normalized = path.lower()
    name = normalized.rsplit("/", 1)[-1]
    return (
        name.startswith("readme")
        or name in {"index.md", "index.markdown", "guide.md", "intro.md", "introduction.md"}
        or normalized.startswith("docs/")
    )


async def search(
    query: str,
    project_id: str | None = None,
    file_type: str | None = None,
    top_k: int | None = None,
) -> list[dict]:
    settings = get_settings()
    top_k = top_k or settings.search_top_k
    embedding = get_embedding()
    vector = embedding.embed([query])[0]
    filters: dict = {}
    if project_id:
        filters["project_id"] = project_id
    if file_type:
        filters["file_type"] = file_type

    store = vector_store.get_vector_store()
    candidates = await store.query(vector, top_k=top_k * 3, filters=filters)
    results = []
    for item in candidates:
        combined = 0.7 * item["score"] + 0.3 * _keyword_score(query, item["text"], item["path"])
        results.append(
            {
                "project_id": item["project_id"],
                "path": item["path"],
                "file_type": item["file_type"],
                "language": item.get("language"),
                "text": item["text"],
                "score": combined,
            }
        )
    results.sort(key=lambda item: item["score"], reverse=True)
    return results[:top_k]


async def project_overview(project_id: str | None, top_k: int | None = None) -> list[dict]:
    query = "README 项目介绍 功能 架构 目录 使用 安装"
    if project_id:
        results = await search(query, project_id=project_id, top_k=top_k or 12)
    else:
        results = await search(query, top_k=top_k or 12)
    results.sort(key=lambda item: (0 if _readmeish(item["path"]) else 1, -item["score"]))
    return results
