import re

from backend.app.config import get_settings
from backend.app.services import vector_store
from backend.app.services.embedding import chinese_tokens, get_embedding

LANGUAGE_ALIASES = {
    "python": ["python", "py"],
    "javascript": ["javascript", "node"],
    "typescript": ["typescript", "ts"],
    "vue": ["vue", "vue3", "vuejs"],
    "react": ["react", "reactjs"],
    "go": ["golang", "go"],
    "rust": ["rust", "rs"],
    "c": ["c语言", "c/c++", "cpp", "c++"],
    "java": ["java"],
    "kotlin": ["kotlin"],
    "swift": ["swift"],
    "php": ["php"],
    "ruby": ["ruby"],
    "sql": ["sql"],
    "html": ["html"],
    "css": ["css"],
    "shell": ["shell", "bash"],
    "json": ["json"],
    "yaml": ["yaml", "yml"],
}


def _alias_in_query(alias: str, query_lower: str) -> bool:
    compact = re.sub(r"\s+", "", query_lower)
    if alias == "c":
        return "c语言" in compact or "c++" in compact or "c/c++" in compact
    if alias in {"py", "ts", "js", "go", "rs"}:
        return re.search(rf"(?<![a-z0-9]){re.escape(alias)}(?![a-z0-9])", query_lower) is not None
    return alias in query_lower


def detect_languages(query: str) -> list[str]:
    query_lower = query.lower()
    return [
        canonical
        for canonical, aliases in LANGUAGE_ALIASES.items()
        if any(_alias_in_query(alias, query_lower) for alias in aliases)
    ]


def _keyword_score(query: str, text: str, path: str) -> float:
    tokens = {token for token in chinese_tokens(query)}
    if not tokens:
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
    return min(score / len(tokens), 1.5)


def _combined_score(vector_score: float, keyword_score: float) -> float:
    keyword = min(max(keyword_score, 0.0), 1.0)
    if keyword <= 0.0:
        return 0.65 * vector_score
    if vector_score <= 0.0:
        return 0.45 * keyword
    return 0.65 * vector_score + 0.35 * keyword


def _merge_candidates(vector_candidates: list[dict], keyword_candidates: list[dict]) -> dict[str, dict]:
    merged: dict[str, dict] = {}
    keyword_by_id = {item["id"]: item for item in keyword_candidates}
    for item in vector_candidates:
        keyword_item = keyword_by_id.pop(item["id"], None)
        keyword_score = (
            _keyword_score(
                item.get("_query", ""),
                keyword_item.get("text", ""),
                keyword_item.get("path", ""),
            )
            if keyword_item
            else 0.0
        )
        item["score"] = _combined_score(float(item.get("score", 0.0)), keyword_score)
        merged[item["id"]] = item
    for item in keyword_candidates:
        if item["id"] in merged:
            continue
        score = _keyword_score(item.get("_query", ""), item.get("text", ""), item.get("path", ""))
        if score > 0:
            item["score"] = _combined_score(0.0, score)
            merged[item["id"]] = item
    return merged


def _filter_by_confidence(results: list[dict]) -> list[dict]:
    if not results:
        return []
    settings = get_settings()
    top_score = float(results[0]["score"])
    threshold = max(settings.search_min_score, top_score - settings.search_top1_gap)
    return [item for item in results if float(item["score"]) >= threshold]


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
    filters: dict = {}
    if project_id:
        filters["project_id"] = project_id
    if file_type:
        filters["file_type"] = file_type

    store = vector_store.get_vector_store()
    vector_candidates = await store.query(embedding.embed([query])[0], top_k=top_k * 3, filters=filters)
    keyword_candidates = await store.keyword_candidates(filters)
    for item in vector_candidates:
        item["_query"] = query
    for item in keyword_candidates:
        item["_query"] = query
    merged = _merge_candidates(vector_candidates, keyword_candidates)
    results = sorted(
        (
            {
                "project_id": item["project_id"],
                "path": item["path"],
                "file_type": item["file_type"],
                "language": item.get("language"),
                "text": item["text"],
                "score": float(item["score"]),
            }
            for item in merged.values()
        ),
        key=lambda item: item["score"],
        reverse=True,
    )
    return _filter_by_confidence(results)[:top_k]


async def project_search(
    query: str,
    project_id: str | None = None,
    top_k: int | None = None,
) -> list[dict]:
    results = await search(
        query,
        project_id=project_id,
        file_type="project_summary",
        top_k=top_k or 6,
    )
    languages = detect_languages(query)
    if not languages:
        return results

    store = vector_store.get_vector_store()
    filters: dict = {"file_type": "project_summary"}
    if project_id:
        filters["project_id"] = project_id
    candidates = await store.keyword_candidates(filters)
    boosted: list[dict] = []
    for item in candidates:
        metadata = item.get("metadata") or {}
        searchable = " ".join(
            str(metadata.get(key, ""))
            for key in ("languages", "primary_languages", "tech_stack")
        )
        searchable += f" {item.get('text', '')}"
        match_count = sum(1 for lang in languages if lang in searchable.lower())
        if match_count:
            item["score"] = 0.55 + 0.15 * match_count
            item["_language_boost"] = True
            boosted.append(item)
    if not boosted:
        return results

    merged = {
        (item.get("project_id"), item.get("path")): item
        for item in results
    }
    for item in boosted:
        merged[(item.get("project_id"), item.get("path"))] = item
    ranked = sorted(
        merged.values(),
        key=lambda item: float(item.get("score", 0.0)),
        reverse=True,
    )
    return ranked[: top_k or 6]


async def project_overview(project_id: str | None, top_k: int | None = None) -> list[dict]:
    query = "README 项目介绍 功能 架构 目录 使用 安装"
    if project_id:
        results = await search(query, project_id=project_id, top_k=top_k or 12)
    else:
        results = await search(query, top_k=top_k or 12)
    summary_results = await project_search(query, project_id=project_id, top_k=4)
    by_id = {item["path"]: item for item in results}
    for item in summary_results:
        by_id[item["path"]] = item
    results = list(by_id.values())
    results.sort(
        key=lambda item: (
            0 if item["file_type"] == "project_summary" else 1 if _readmeish(item["path"]) else 2,
            -item["score"],
        )
    )
    return results
