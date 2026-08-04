import re

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.services import memory, model_config, retrieval
from backend.app.services.file_service import read_project_file

READ_FILE_PATTERN = re.compile(
    r"(?:读取|读文件|read file)\s*(?:文件)?\s*"
    r"(?P<owner>[\w.-]+)/(?P<repo>[\w.-]+)(?:[/\s]+)(?P<path>[\w./@_+\-]+)",
    re.IGNORECASE,
)


def _route(message: str) -> tuple[str | None, str | None]:
    project_match = re.search(r"(?P<owner>[\w.-]+)/(?P<repo>[\w.-]+)", message)
    project_id = f"{project_match.group('owner')}/{project_match.group('repo')}" if project_match else None
    if any(keyword in message for keyword in ["概览", "项目介绍", "项目有什么", "目录结构", "overview"]):
        return project_id, "overview"
    if any(keyword in message for keyword in ["图片", "截图", "logo", "图", "banner"]):
        return project_id, "image"
    if any(keyword in message for keyword in ["文档", "说明", "readme", "手册", "教程"]):
        return project_id, "doc"
    return project_id, None


def _build_context(messages: list, memories: list, results: list[dict]) -> str:
    parts = []
    if memories:
        parts.append("长期记忆：\n" + "\n".join(f"- {item.content}" for item in memories))
    if results:
        parts.append("检索结果：")
        for item in results:
            parts.append(f"- {item['project_id']} {item['path']} ({item['file_type']}): {item['text'][:300]}")
    else:
        parts.append("检索结果为空。")
    return "\n".join(parts)


async def _call_llm(config: dict, system: str, user: str) -> str | None:
    try:
        async with httpx.AsyncClient(timeout=60) as client:
            response = await client.post(
                f"{config['base_url'].rstrip('/')}/chat/completions",
                headers={"Authorization": f"Bearer {config['api_key']}"},
                json={
                    "model": config["model"],
                    "messages": [
                        {"role": "system", "content": system},
                        {"role": "user", "content": user},
                    ],
                    "stream": False,
                },
            )
            response.raise_for_status()
            data = response.json()
            return data["choices"][0]["message"]["content"]
    except Exception:
        return None


def _fallback_answer(message: str, results: list[dict]) -> str:
    if not results:
        return "未找到与问题相关的内容。请确认仓库已经入库，或换一种问法。"
    lines = [f"根据检索到的 {len(results)} 条相关内容，最相关的来源如下：", ""]
    for index, item in enumerate(results, start=1):
        lines.append(f"{index}. {item['project_id']} / {item['path']}")
        snippet = item["text"].strip().replace("\n", " ")[:200]
        lines.append(f"   {snippet}")
        lines.append("")
    lines.append("以上内容来自本地向量检索，尚未经过模型总结。")
    return "\n".join(lines)


async def ask(db: AsyncSession, user_id: int, message: str, session_id: int | None = None) -> tuple[int, str, list[dict]]:
    session = await memory.ensure_session(db, user_id, session_id)
    await memory.save_message(db, session.id, "user", message)

    read_match = READ_FILE_PATTERN.search(message)
    if read_match:
        content = await read_project_file(
            read_match.group("owner"),
            read_match.group("repo"),
            read_match.group("path"),
        )
        answer = f"文件内容：\n\n{content}" if content else "未找到该文件，请确认路径是否正确。"
        await memory.save_message(db, session.id, "assistant", answer)
        return session.id, answer, []

    recent = await memory.recent_messages(db, session.id)
    project_id, file_type = _route(message)
    memories = await memory.recall_long_term(db, user_id, message, project_id=project_id)
    if file_type == "overview":
        results = await retrieval.project_overview(project_id, top_k=12)
    else:
        results = await retrieval.search(message, project_id=project_id, file_type=file_type)

    context = _build_context(recent[-10:], memories, results)
    config = await model_config.resolve_active(db, user_id)
    answer = None
    if config:
        system = (
            "你是 MyAgentic 的本地代码助手。只能根据给定的检索结果回答，"
            "回答必须列出来源文件路径。如果检索结果为空，要明确说明未找到。"
        )
        answer = await _call_llm(config, system, f"问题：{message}\n\n{context}")
    if not answer:
        answer = _fallback_answer(message, results)

    await memory.save_message(db, session.id, "assistant", answer, sources=results)
    await memory.maybe_save_summary(db, user_id, session.id)
    return session.id, answer, results
