import re

from backend.app.services.embedding import chinese_tokens


def _query_terms(query: str) -> list[str]:
    terms = chinese_tokens(query)
    if terms:
        return terms
    return [
        token
        for token in re.findall(r"[\w\u4e00-\u9fff]{2,}", query.lower())
        if token not in {"如何", "怎么", "什么", "哪个", "哪些", "这个", "那个"}
    ]


def _lexical_relevance(query: str, text: str, path: str, file_type: str | None) -> float:
    terms = _query_terms(query)
    if not terms:
        return 0.5
    text_lower = text.lower()
    path_lower = path.lower()
    hits = 0
    for term in terms:
        if term in text_lower or term in path_lower:
            hits += 1
    ratio = hits / len(terms)
    file_type = file_type or ""
    if any(keyword in query for keyword in ["图片", "截图", "logo", "banner", "图"]) and file_type == "image":
        ratio += 0.15
    if any(keyword in query for keyword in ["文档", "说明", "readme", "手册", "教程"]) and file_type in {"doc", "project_summary"}:
        ratio += 0.10
    if any(keyword in query for keyword in ["概览", "项目介绍", "目录结构", "overview"]) and file_type == "project_summary":
        ratio += 0.15
    return min(ratio, 1.0)


def rerank_results(query: str, results: list[dict]) -> list[dict]:
    """Blend semantic score with lexical overlap and reorder retrieval results."""
    if not results:
        return []
    raw_scores = [max(float(item.get("score", 0.0)), 0.0) for item in results]
    max_score = max(raw_scores) if raw_scores else 0.0
    reranked = []
    for index, item in enumerate(results):
        normalized = raw_scores[index] / max_score if max_score > 0 else 1.0
        lexical = _lexical_relevance(
            query,
            item.get("text", ""),
            item.get("path", ""),
            item.get("file_type"),
        )
        item["relevance"] = round(lexical, 4)
        item["rerank_score"] = round(0.6 * normalized + 0.4 * lexical, 4)
        reranked.append(item)
    reranked.sort(key=lambda item: item["rerank_score"], reverse=True)
    return reranked


def filter_by_relevance(query: str, results: list[dict]) -> list[dict]:
    """Keep strong retrieval evidence and drop obvious low-relevance outliers."""
    reranked = rerank_results(query, results)
    if len(reranked) <= 1:
        return reranked
    top_score = reranked[0].get("rerank_score", 0.0)
    kept = [
        item
        for item in reranked
        if item.get("rerank_score", 0.0) >= max(0.45, 0.55 * top_score)
        or item.get("relevance", 0.0) >= 0.5
    ]
    return kept or reranked[:1]
