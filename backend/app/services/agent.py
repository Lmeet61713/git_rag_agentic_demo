import logging
import re
from collections import Counter, defaultdict
from typing import TypedDict

import httpx
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.models import IndexedFile, Repo
from backend.app.services import memory, model_config, relevance, retrieval, web_search
from backend.app.services.file_service import read_project_file
from backend.app.services.tool_registry import (
    ToolSelection,
    extract_tool_selection_json,
    tool_catalog_text,
)

logger = logging.getLogger(__name__)


class AgentState(TypedDict, total=False):
    db: AsyncSession
    user_id: int
    message: str
    session: object
    config: dict | None
    fallback_config: dict | None
    out_of_scope: bool
    project_id: str | None
    project_explicit: bool
    file_type: str | None
    tool: str
    turns: int
    results: list[dict]
    retry: bool

READ_FILE_PATTERN = re.compile(
    r"(?:读取|读文件|read file)\s*(?:文件)?\s*"
    r"(?P<owner>[\w.-]+)/(?P<repo>[\w.-]+)(?:[/\s]+)(?P<path>[\w./@_+\-]+)",
    re.IGNORECASE,
)
DIRECT_QUESTION_PATTERN = re.compile(
    r"(你好|您好|哈喽|在吗|hi|hello|hey|请问你是|你是谁|你是哪个|你是什么|你叫什么|"
    r"你有什么能力|你能做什么|你可以做什么|介绍一下你自己|什么模型|哪个模型|who are you|what model|what can you do)",
    re.IGNORECASE,
)
APP_GUIDE_PATTERN = re.compile(
    r"(直接把代码发给你|发代码|粘贴代码|怎么入库|怎么同步|怎么提问|"
    r"是否支持|支持吗|怎么操作|如何开始|应用怎么用|如何使用这个应用|有哪些功能|支持什么功能|有什么功能)",
    re.IGNORECASE,
)
REPO_META_PATTERN = re.compile(
    r"(最早|最晚|最近创建|创建时间|哪个仓库|哪些仓库|仓库列表|按时间|排序)",
    re.IGNORECASE,
)
GENERAL_CHAT_PATTERN = re.compile(
    r"(今天天气|明天天气|天气怎么样|最近天气|下雨|气温|温度|"
    r"讲个笑话|讲笑话|笑话|随便聊聊|聊聊天|闲聊|最近怎么样|你开心吗|"
    r"推荐一部电影|电影推荐|推荐音乐|音乐推荐|听什么歌|"
    r"个人问题|情感问题|人生建议|哲学问题|"
    r"翻译一下|写一首诗|写一篇作文|"
    r"股票推荐|彩票|世界杯|奥运会|娱乐新闻|八卦)",
    re.IGNORECASE,
)

PROVIDER_LABELS = {
    "deepseek": "DeepSeek",
    "dashscope": "阿里云 DashScope",
    "ollama": "本地 Ollama",
}

GENERAL_CHAT_FALLBACK = (
    "我主要回答已入库 GitHub 仓库的代码、文档、图片和项目概览问题。"
    "你刚才的问题不属于仓库问答，我暂时不擅长，建议换一个与项目相关的问题。"
)
CHAT_SYSTEM_PROMPT = (
    "你是 MyAgentic 的本地代码助手。用户正在和你闲聊或问与仓库无关的问题。"
    "请用简短、自然、友好的中文回答，不要检索仓库，不要编造事实。"
)
REPO_BRIEF_MARKERS = [
    "仓库里有什么",
    "仓库里都有什么",
    "大概有哪些",
    "有哪些项目",
    "有哪些仓库",
    "有哪些库",
    "介绍所有仓库",
    "简单介绍所有",
    "介绍一下仓库",
    "仓库简介",
    "所有仓库",
    "所有项目",
    "项目一览",
    "项目简介",
    "仓库列表",
    "都有什么项目",
]
WEB_SEARCH_MARKERS = [
    "联网搜索",
    "联网",
    "网络搜索",
    "搜索一下",
    "网上搜",
    "最新",
    "新闻",
    "实时",
    "网上的",
    "网络上",
]
WEB_SEARCH_SYSTEM_PROMPT = (
    "你是 MyAgentic 的本地代码助手。用户要求联网搜索。"
    "请基于下面的联网搜索结果回答，并列出每条来源 URL；"
    "如果结果为空或无法回答，要明确说明，不能编造事实。"
)

LANGUAGE_LABELS = {
    "python": "Python",
    "javascript": "JavaScript",
    "typescript": "TypeScript",
    "vue": "Vue",
    "react": "React",
    "go": "Go",
    "rust": "Rust",
    "c": "C",
    "cpp": "C++",
    "java": "Java",
    "kotlin": "Kotlin",
    "swift": "Swift",
    "php": "PHP",
    "ruby": "Ruby",
    "sql": "SQL",
    "html": "HTML",
    "css": "CSS",
    "shell": "Shell",
    "bash": "Bash",
    "json": "JSON",
    "yaml": "YAML",
    "markdown": "Markdown",
}


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
    if messages:
        parts.append("历史对话：")
        for item in messages[-10:]:
            role = "用户" if item.role == "user" else "助手"
            parts.append(f"- {role}: {item.content[:500]}")
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
        base_url = config["base_url"].rstrip("/")
        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ]
        async with httpx.AsyncClient(timeout=60) as client:
            if config.get("provider") == "ollama" and not base_url.endswith("/v1"):
                url = f"{base_url}/api/chat"
                headers = {}
                payload = {"model": config["model"], "messages": messages, "stream": False}
            else:
                url = f"{base_url}/chat/completions"
                headers = {"Authorization": f"Bearer {config['api_key']}"}
                payload = {
                    "model": config["model"],
                    "messages": messages,
                    "stream": False,
                }
            response = await client.post(
                url,
                headers=headers,
                json=payload,
            )
            response.raise_for_status()
            data = response.json()
            if "choices" in data:
                return data["choices"][0]["message"]["content"]
            return data.get("message", {}).get("content")
    except Exception as exc:
        logger.warning(
            "LLM call failed provider=%s model=%s: %s",
            config.get("provider"),
            config.get("model"),
            exc,
        )
        return None


async def _call_llm_chain(
    config: dict | None,
    fallback_config: dict | None,
    system: str,
    user: str,
) -> tuple[str | None, bool]:
    if config and not config.get("config_error"):
        text = await _call_llm(config, system, user)
        if text:
            return text, False
    if fallback_config:
        text = await _call_llm(fallback_config, system, user)
        if text:
            return text, True
    return None, False


def _answer_mode(answer: str, tool: str, used_fallback: bool = False) -> str:
    if tool == "config_error":
        return "config_error"
    if used_fallback:
        return "fallback_llm"
    if answer.startswith(("当前 DeepSeek 模型配置", "当前 阿里云 DashScope 模型配置")):
        return "config_error"
    if "本地检索兜底" in answer or answer.startswith(
        ("当前未配置可用模型", "未找到与问题相关", "当前模型")
    ):
        return "fallback"
    return "llm"


def _fallback_answer(
    message: str,
    results: list[dict],
    config: dict | None = None,
    tool: str = "search",
) -> str:
    if tool == "web_search":
        if results:
            return _format_web_results(results, head="模型调用失败，以下为联网搜索结果：")
        if config:
            provider = PROVIDER_LABELS.get(config["provider"], config["provider"])
            return (
                f"联网搜索已完成，但当前模型 {provider} · {config['model']} "
                "调用失败，无法总结结果。"
            )
        return "联网搜索已完成，但未配置可用的总结模型。"
    if not results:
        if config:
            provider = PROVIDER_LABELS.get(config["provider"], config["provider"])
            return (
                f"当前模型 {provider} · {config['model']} 调用失败，"
                "未找到检索结果。请检查模型名称、API Key 或网络。"
            )
        return "未找到与问题相关的内容。请确认仓库已经入库，或换一种问法。"
    if config:
        provider = PROVIDER_LABELS.get(config["provider"], config["provider"])
        head = (
            f"当前模型 {provider} · {config['model']} 调用失败，"
            "以下为本地向量检索兜底结果，未经模型总结："
        )
    else:
        head = "当前未配置可用模型，以下为本地向量检索兜底结果，未经模型总结："
    lines = [head, ""]
    lines.append(f"根据检索到的 {len(results)} 条相关内容，最相关的来源如下：")
    lines.append("")
    for index, item in enumerate(results, start=1):
        lines.append(f"{index}. {item['project_id']} / {item['path']}")
        snippet = item["text"].strip().replace("\n", " ")[:200]
        lines.append(f"   {snippet}")
        lines.append("")
    lines.append("如需模型总结，请在模型配置页面选择 DeepSeek、DashScope 或本地 Ollama 模型。")
    return "\n".join(lines)


def _direct_answer(message: str, config: dict | None) -> str | None:
    if not DIRECT_QUESTION_PATTERN.search(message):
        return None
    if config:
        provider = PROVIDER_LABELS.get(config["provider"], config["provider"])
        return (
            f"我是 MyAgentic 的本地代码助手，当前使用 {provider} 的 {config['model']} 模型。"
            "你可以问我已入库仓库的代码、文档、图片或项目概览问题。"
        )
    return (
        "当前未配置可用模型。我是 MyAgentic 的本地代码助手，"
        "现在只能使用本地向量检索给出带来源的兜底回答；"
        "可以在模型配置页选择 DeepSeek、DashScope 或本地 Ollama 模型。"
    )


def _app_guide_answer(message: str) -> str | None:
    if not APP_GUIDE_PATTERN.search(message) and not (
        ("能不能" in message or "是否可以" in message)
        and any(
            keyword in message for keyword in ["入库", "同步", "检索", "提问", "配置"]
        )
    ):
        return None
    if "项目" in message and "发给你" not in message:
        return None
    if "代码" in message and "入库" in message:
        return (
            "直接把代码发给我不会自动入库。当前入库流程是：GitHub OAuth 登录，"
            "在仓库列表选择公开仓库，点击“入库”，系统会完成 clone、解析和向量化。"
            "聊天框里粘贴的代码只是对话内容，不会写入本地索引。"
        )
    return (
        "当前使用方式：先通过 GitHub 登录，在仓库列表选择公开仓库并点击“入库”，"
        "等待状态变为已入库后，再到聊天页提问代码、文档、图片或项目概览。"
        "模型配置页可以选择 DeepSeek、DashScope 或本地 Ollama。"
    )


def _general_chat_answer(message: str) -> str | None:
    if not GENERAL_CHAT_PATTERN.search(message):
        return None
    return (
        "我主要回答已入库 GitHub 仓库的代码、文档、图片和项目概览问题。"
        "你刚才的问题不属于仓库问答，我暂时不擅长，建议换一个与项目相关的问题。"
    )


def _general_chat_plan(
    session: object,
    message: str,
    config: dict | None,
) -> dict:
    if config and not config.get("config_error"):
        return {
            "session": session,
            "results": [],
            "tool": "general_chat",
            "config": config,
            "system": CHAT_SYSTEM_PROMPT,
            "context": "",
        }
    return {
        "session": session,
        "answer": _general_chat_answer(message)
        or GENERAL_CHAT_FALLBACK,
        "results": [],
        "tool": "general_chat",
        "config": config,
        "out_of_scope": True,
    }


def _out_of_scope_plan(
    session: object,
    message: str,
    config: dict | None = None,
) -> dict:
    return _general_chat_plan(session, message, config)


def _format_repo_time(value: str | None) -> str:
    if not value:
        return "时间未知"
    return value.replace("T", " ").replace("Z", " UTC")[:19]


def _repo_meta_answer(message: str, repos: list[Repo]) -> str | None:
    if not REPO_META_PATTERN.search(message):
        return None
    if not repos:
        return "当前没有可用的仓库元数据，请先同步仓库。"

    def sort_key(repo: Repo) -> str:
        return (
            repo.github_created_at
            or (repo.created_at.strftime("%Y-%m-%dT%H:%M:%S") if repo.created_at else "")
            or "9999-99-99T99:99:99"
        )

    if "最早" in message:
        repo = min(repos, key=sort_key)
        return f"最早创建的仓库是 {repo.full_name}，创建时间 {_format_repo_time(repo.github_created_at)}。"
    if "最晚" in message or "最近创建" in message:
        repo = max(repos, key=sort_key)
        return f"最近创建的仓库是 {repo.full_name}，创建时间 {_format_repo_time(repo.github_created_at)}。"
    lines = ["仓库按创建时间排序："]
    for repo in sorted(repos, key=sort_key):
        lines.append(f"- {repo.full_name}（{_format_repo_time(repo.github_created_at)}）")
    return "\n".join(lines)


def _normalize_repo_name(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", value.lower())


def _language_label(value: str) -> str:
    return LANGUAGE_LABELS.get(value.lower(), value)


def _languages_from_summary(summary: str | None) -> list[str]:
    if not summary:
        return []
    for line in summary.splitlines():
        if line.startswith("主要语言："):
            raw = line[len("主要语言："):]
            return [
                _language_label(part.split()[0])
                for part in raw.split("、")
                if part.strip()
            ]
    return []


def _repo_one_line(repo: Repo) -> str:
    if repo.summary:
        for line in repo.summary.splitlines():
            if line.startswith("README 摘录："):
                excerpt = line[len("README 摘录："):].strip()
                if excerpt:
                    return excerpt
        if not repo.summary.startswith("索引完成"):
            first_line = repo.summary.splitlines()[0].strip()
            if first_line:
                return first_line
    return "已入库项目，详情见仓库页。"


def _repo_language_list(
    repo_id: int,
    repo: Repo,
    language_counts: dict[int, Counter[str]],
) -> list[str]:
    counts = language_counts.get(repo_id)
    if counts:
        return [_language_label(language) for language, _ in counts.most_common()]
    return _languages_from_summary(repo.summary)


def _format_project_intro(
    repo: Repo,
    language_counts: dict[int, Counter[str]] | None = None,
) -> str:
    lines = [f"### {repo.full_name}"]
    lines.append(f"- **简介**：{_repo_one_line(repo)}")
    languages = _repo_language_list(
        repo.id,
        repo,
        language_counts or {},
    )
    if languages:
        lines.append(f"- **主要语言**：{'、'.join(languages)}")
    if repo.summary:
        for line in repo.summary.splitlines():
            if line.startswith("主要目录："):
                lines.append(f"- **主要目录**：{line[len('主要目录：'):]}")
                break
    return "\n".join(lines)


def _repo_brief_text(
    repos: list[Repo],
    language_counts: dict[int, Counter[str]] | None = None,
) -> str:
    if not repos:
        return "当前还没有已入库的仓库，请先在“仓库”页完成入库后再试。"
    lines = ["### 仓库一览"]
    counts = language_counts or {}
    for repo in sorted(repos, key=lambda item: item.repo.lower()):
        languages = _repo_language_list(repo.id, repo, counts)
        language_text = f"；主要语言：{'、'.join(languages)}" if languages else ""
        lines.append(f"- **{repo.full_name}**：{_repo_one_line(repo)}{language_text}")
    return "\n".join(lines)


def _repo_brief_answer(
    message: str,
    repos: list[Repo],
    language_counts: dict[int, Counter[str]] | None = None,
) -> str | None:
    if not any(marker in message for marker in REPO_BRIEF_MARKERS):
        return None
    return _repo_brief_text(repos, language_counts)


def _is_tech_query(message: str) -> bool:
    markers = [
        "技术栈",
        "框架",
        "哪个仓库用",
        "哪些仓库用",
        "哪个仓库使用",
        "哪些仓库使用",
        "用什么语言",
        "是不是用",
        "有没有用",
        "用了什么",
        "使用什么",
    ]
    return any(marker in message for marker in markers)


def _is_intro_query(message: str) -> bool:
    markers = [
        "介绍一下",
        "简单介绍",
        "简单说下",
        "简单说说",
        "介绍下",
        "项目介绍",
        "项目是做什么",
        "项目是什么",
        "这是什么项目",
        "大致做什么",
        "是干嘛的",
        "是做什么的",
        "概述",
        "概要",
        "简介",
    ]
    return any(marker in message for marker in markers)


def _matching_repos(message: str, repos: list[Repo], recent: list) -> list[Repo]:
    haystack = f"{message} {' '.join(item.content for item in recent[-6:])}".lower()
    normalized_haystack = _normalize_repo_name(haystack)
    matches = []
    for repo in repos:
        if (
            repo.full_name.lower() in haystack
            or repo.repo.lower() in haystack
            or (
                _normalize_repo_name(repo.repo)
                and _normalize_repo_name(repo.repo) in normalized_haystack
            )
        ):
            matches.append(repo)
    return matches


def _project_intro_answer(
    message: str,
    repos: list[Repo],
    recent: list,
    language_counts: dict[int, Counter[str]] | None = None,
) -> str | None:
    if not _is_intro_query(message):
        return None
    matches = _matching_repos(message, repos, recent)
    if not matches:
        return (
            "请告诉我你想了解哪个仓库，例如 `Lmeet61713/YueDu` 或直接给出仓库名。"
            "我可以用项目摘要直接介绍，不需要先做向量检索。"
        )
    lines = []
    counts = language_counts or {}
    for repo in matches:
        lines.append(_format_project_intro(repo, counts))
    return "\n".join(lines)


def _format_web_results(results: list[dict], head: str = "### 联网搜索结果") -> str:
    if not results:
        return "联网搜索没有返回结果，请换一个更具体的关键词。"
    lines = [head]
    for index, item in enumerate(results, start=1):
        text = item.get("text", "")
        first_line = text.splitlines()[0] if text else "无标题"
        lines.append(f"{index}. **{first_line}**")
        lines.append(f"   来源：{item.get('path', '')}")
        snippet = "\n".join(text.splitlines()[1:])[:200] if len(text.splitlines()) > 1 else ""
        if snippet:
            lines.append(f"   {snippet}")
    return "\n".join(lines)


async def _web_search_plan(
    db: AsyncSession,
    session: object,
    message: str,
    web_config: dict | None,
    config: dict | None,
    fallback_config: dict | None,
) -> dict:
    if web_config is None:
        return {
            "session": session,
            "answer": "联网搜索未配置 API Key，请到“模型配置”页填写 Tavily 联网搜索 API Key。",
            "results": [],
            "tool": "web_search",
        }
    if web_config.get("config_error"):
        return {
            "session": session,
            "answer": "联网搜索 API Key 无效，请重新填写并保存。",
            "results": [],
            "tool": "web_search",
        }
    try:
        results = await web_search.tavily_search(
            message,
            web_config["api_key"],
            web_config.get("base_url", "https://api.tavily.com"),
        )
    except Exception as exc:
        logger.warning("web search failed: %s", exc)
        return {
            "session": session,
            "answer": f"联网搜索失败：{exc}",
            "results": [],
            "tool": "web_search",
        }
    if not results:
        return {
            "session": session,
            "answer": "联网搜索没有返回结果，请换一个更具体的关键词。",
            "results": [],
            "tool": "web_search",
        }
    if config and not config.get("config_error"):
        return {
            "session": session,
            "results": results,
            "tool": "web_search",
            "config": config,
            "fallback_config": fallback_config,
            "system": WEB_SEARCH_SYSTEM_PROMPT,
            "context": _build_context([], [], results),
        }
    return {
        "session": session,
        "answer": _format_web_results(results),
        "results": results,
        "tool": "web_search",
    }


def _forced_non_retrieval_answer(
    message: str,
    config: dict | None,
    repos: list[Repo],
    recent: list,
    language_counts: dict[int, Counter[str]] | None = None,
) -> dict | None:
    direct_markers = [
        "请问你是",
        "你是谁",
        "你是哪个",
        "你是什么",
        "你叫什么",
        "你有什么能力",
        "你能做什么",
        "你可以做什么",
        "介绍一下你自己",
        "你好",
        "您好",
        "什么模型",
        "哪个模型",
    ]
    app_guide_markers = [
        "应用怎么用",
        "如何使用这个应用",
        "有哪些功能",
        "支持什么功能",
        "有什么功能",
        "怎么入库",
        "怎么提问",
        "是否支持",
        "支持吗",
    ]
    intro_markers = [
        "介绍一下",
        "简单介绍",
        "项目介绍",
        "项目是什么",
        "这是什么项目",
        "概述",
        "概要",
        "简介",
    ]
    if any(marker in message for marker in direct_markers):
        answer = _direct_answer(message, config)
        return {
            "answer": answer
            or "我是 MyAgentic 的本地代码助手，可以帮你检索和分析已入库仓库的代码、文档、图片，也可以回答项目概览、技术栈和使用方式。",
            "tool": "direct",
        }
    if any(marker in message for marker in app_guide_markers):
        answer = _app_guide_answer(message)
        return {
            "answer": answer
            or (
                "当前使用方式：先通过 GitHub 登录，在仓库列表选择公开仓库并点击“入库”，"
                "等待状态变为已入库后，再到聊天页提问代码、文档、图片或项目概览。"
            ),
            "tool": "app_guide",
        }
    if any(marker in message for marker in REPO_BRIEF_MARKERS):
        answer = _repo_brief_answer(message, repos, language_counts)
        return {
            "answer": answer
            or "当前还没有可展示的仓库，请先登录并刷新仓库列表。",
            "tool": "repo_brief",
        }
    if any(marker in message for marker in intro_markers):
        answer = _project_intro_answer(message, repos, recent, language_counts)
        return {
            "answer": answer or "请告诉我你想了解哪个仓库，例如 `Lmeet61713/YueDu`。",
            "tool": "project_intro",
        }
    return None


def _tool_from_route(file_type: str | None, message: str) -> str:
    if _is_tech_query(message):
        return "repo_tech"
    return {
        "overview": "overview",
        "image": "image_search",
        "doc": "doc_search",
    }.get(file_type or "", "search")


_SYSTEM_PROMPT = (
    "你是 MyAgentic 的本地代码助手。如果用户只是问好或询问你的身份、当前模型，"
    "直接回答，不要检索。其他问题只能根据给定的检索结果回答，"
    "回答必须列出来源文件路径；除非用户明确要求粘贴代码，否则不要大段复制代码，"
    "用自然语言概括并给出文件路径；如果检索结果为空或证据不足，要明确说明未找到，不能编造来源。"
)


def _split_chunks(text: str, size: int = 120) -> list[str]:
    return [text[index : index + size] for index in range(0, len(text), size)]


async def _graph_route(state: dict) -> dict:
    message = state["message"]
    project_match = re.search(r"(?P<owner>[\w.-]+)/(?P<repo>[\w.-]+)", message)
    project_explicit = project_match is not None
    if state.get("tool") in {
        "repo_tech",
        "overview",
        "doc_search",
        "image_search",
        "search",
    }:
        return {
            "message": message,
            "project_id": state.get("project_id"),
            "file_type": state.get("file_type"),
            "tool": state["tool"],
            "project_explicit": project_explicit,
            "turns": 0,
        }
    project_id, file_type = _route(message)
    return {
        "message": message,
        "project_id": project_id,
        "file_type": file_type,
        "tool": _tool_from_route(file_type, message),
        "project_explicit": project_explicit,
        "turns": 0,
    }


async def _graph_retrieve(state: dict) -> dict:
    message = state["message"]
    project_id = state.get("project_id")
    tool = state.get("tool", "search")
    if tool == "repo_tech":
        results = await retrieval.project_search(message, project_id=project_id, top_k=8)
    elif tool == "overview":
        results = await retrieval.project_overview(project_id, top_k=12)
    else:
        file_type = {"image_search": "image", "doc_search": "doc"}.get(tool, state.get("file_type"))
        results = await retrieval.search(message, project_id=project_id, file_type=file_type)
    return {"results": results, "turns": int(state.get("turns", 0)) + 1}


def _after_retrieve(state: dict) -> str:
    if int(state.get("turns", 0)) >= 3:
        return "validate" if state.get("results") else "__end__"
    return "validate"


async def _graph_validate(state: dict) -> dict:
    message = state.get("message", "")
    if _general_chat_answer(message):
        return {"results": [], "out_of_scope": True}
    results = state.get("results") or []
    if results:
        reranked = relevance.rerank_results(message, results)
        filtered = relevance.filter_by_relevance(message, reranked)
        if state.get("config") and len(filtered) > 1:
            filtered = await _validate_results_with_llm(
                state["config"],
                message,
                filtered,
            )
        results = filtered
    return {"results": results}


def _after_validate(state: dict) -> str:
    if state.get("out_of_scope"):
        return "__end__"
    if not state.get("results") and int(state.get("turns", 0)) < 3:
        return "reflect"
    return "__end__"


def _graph_reflect(state: dict) -> dict:
    if state.get("results"):
        return {"retry": False}
    tool = state.get("tool")
    if state.get("project_explicit") and tool in {"image_search", "doc_search"}:
        return {"retry": False}
    if state.get("file_type"):
        return {"file_type": None, "retry": True}
    if state.get("project_id"):
        if state.get("project_explicit"):
            return {"retry": False}
        return {"project_id": None, "retry": True}
    return {"retry": False}


def _after_reflect(state: dict) -> str:
    return "retrieve" if state.get("retry") else "__end__"


def _build_graph():
    try:
        from langgraph.graph import StateGraph
    except Exception:
        return None
    graph = StateGraph(AgentState)
    graph.add_node("route", _graph_route)
    graph.add_node("retrieve", _graph_retrieve)
    graph.add_node("validate", _graph_validate)
    graph.add_node("reflect", _graph_reflect)
    graph.set_entry_point("route")
    graph.add_edge("route", "retrieve")
    graph.add_conditional_edges(
        "retrieve",
        _after_retrieve,
        {"validate": "validate", "reflect": "reflect", "__end__": "__end__"},
    )
    graph.add_conditional_edges(
        "validate",
        _after_validate,
        {"reflect": "reflect", "__end__": "__end__"},
    )
    graph.add_conditional_edges("reflect", _after_reflect, {"retrieve": "retrieve", "__end__": "__end__"})
    return graph.compile()


TOOL_SELECTION_SYSTEM = (
    "你是 MyAgentic 的意图路由。根据用户问题选择最合适的工具。"
    "除非用户明确询问仓库内的代码、文档、图片、技术栈或某个功能实现，"
    "否则不要选择需要检索的工具。只输出 JSON，不要输出其他文本。\n"
    + tool_catalog_text()
)


async def _select_tool_with_llm(config: dict, message: str) -> ToolSelection | None:
    if not config:
        return None
    user_prompt = (
        f"用户问题：{message}\n\n"
        "请输出 ToolSelection JSON，字段为 tool、project_id、path、reason。"
    )
    text = await _call_llm(config, TOOL_SELECTION_SYSTEM, user_prompt)
    data = extract_tool_selection_json(text or "")
    if not data:
        return None
    try:
        return ToolSelection.model_validate(data)
    except Exception:
        return None


VALIDATION_SYSTEM = (
    "你是检索结果校验器。判断每条检索结果是否真的能回答用户问题。"
    "只输出 JSON，格式为 {\"relevant_indices\": [0, 2]} 或 {\"relevant_indices\": []}。"
    "不要输出其他文本。"
)


async def _validate_results_with_llm(
    config: dict,
    message: str,
    results: list[dict],
) -> list[dict]:
    if not config or len(results) <= 1:
        return results
    lines = ["用户问题：" + message, "", "检索结果："]
    for index, item in enumerate(results):
        lines.append(
            f"{index}. {item['project_id']} {item['path']} "
            f"({item['file_type']}): {item['text'][:240]}"
        )
    text = await _call_llm(config, VALIDATION_SYSTEM, "\n".join(lines))
    data = extract_tool_selection_json(text or "")
    if not data:
        return results
    indices = data.get("relevant_indices") or data.get("indices") or []
    if not isinstance(indices, list):
        return results
    if not indices:
        return []
    kept = [
        results[index]
        for index in indices
        if isinstance(index, int) and 0 <= index < len(results)
    ]
    return kept or results[:1]


async def _manual_retrieve_loop(state: dict) -> dict:
    state = {**state, **await _graph_route(state)}
    while int(state.get("turns", 0)) < 3:
        state.update(await _graph_retrieve(state))
        if _general_chat_answer(state.get("message", "")):
            state["results"] = []
            state["out_of_scope"] = True
            break
        results = relevance.rerank_results(
            state.get("message", ""),
            state.get("results", []),
        )
        results = relevance.filter_by_relevance(state.get("message", ""), results)
        if state.get("config"):
            results = await _validate_results_with_llm(
                state["config"],
                state.get("message", ""),
                results,
            )
        state["results"] = results
        if results:
            break
        if state.get("project_id"):
            if state.get("project_explicit") and state.get("tool") in {"image_search", "doc_search"}:
                break
            if state.get("project_explicit"):
                if state.get("file_type"):
                    state["file_type"] = None
                    continue
                break
            state["project_id"] = None
            continue
        if state.get("file_type"):
            state["file_type"] = None
            continue
        break
    return state


async def _plan(
    db: AsyncSession,
    user_id: int,
    message: str,
    session_id: int | None,
) -> dict:
    session = await memory.ensure_session(db, user_id, session_id)
    await memory.save_message(db, session.id, "user", message)

    result = await db.execute(select(Repo).where(Repo.user_id == user_id))
    repos = list(result.scalars())
    recent = await memory.recent_messages(db, session.id)
    language_result = await db.execute(
        select(IndexedFile.repo_id, IndexedFile.language, func.count(IndexedFile.id))
        .where(IndexedFile.language.is_not(None))
        .group_by(IndexedFile.repo_id, IndexedFile.language)
    )
    language_counts: dict[int, Counter[str]] = defaultdict(Counter)
    for repo_id, language, count in language_result:
        language_counts[repo_id][language] = count
    config = await model_config.resolve_active(db, user_id)
    fallback_config = None
    if config and config.get("provider") != "ollama":
        fallback_config = await model_config.resolve_fallback(db, user_id)
    web_config = await model_config.resolve_web_search(db, user_id)
    if config and config.get("config_error") and config.get("provider") != "ollama" and not fallback_config:
        provider = PROVIDER_LABELS.get(config["provider"], config["provider"])
        return {
            "session": session,
            "answer": (
                f"当前 {provider} 模型配置存在 {config['config_error']}，"
                "请到模型配置页重新填写 API Key 并保存。"
            ),
            "results": [],
            "tool": "config_error",
        }
    forced = _forced_non_retrieval_answer(
        message,
        config,
        repos,
        recent,
        language_counts,
    )
    if forced:
        return {
            "session": session,
            "answer": forced["answer"],
            "results": [],
            "tool": forced["tool"],
        }

    if any(marker in message for marker in WEB_SEARCH_MARKERS):
        return await _web_search_plan(
            db,
            session,
            message,
            web_config,
            config,
            fallback_config,
        )

    read_match = READ_FILE_PATTERN.search(message)
    if read_match:
        content = await read_project_file(
            read_match.group("owner"),
            read_match.group("repo"),
            read_match.group("path"),
        )
        return {
            "session": session,
            "answer": f"文件内容：\n\n{content}" if content else "未找到该文件，请确认路径是否正确。",
            "results": [],
            "tool": "read_file",
        }

    selection = await _select_tool_with_llm(config, message)
    if selection is not None:
        if selection.tool == "web_search":
            return await _web_search_plan(
                db,
                session,
                message,
                web_config,
                config,
                fallback_config,
            )
        intro_matches = _matching_repos(message, repos, recent) if _is_intro_query(message) else []
        if intro_matches and selection.tool not in {"project_intro", "repo_brief"}:
            selection = ToolSelection(
                tool="project_intro",
                project_id=intro_matches[0].full_name,
                reason="口语化项目介绍，避免降级到向量检索",
            )
        tool = selection.tool
        if tool == "direct":
            return {
                "session": session,
                "answer": _direct_answer(message, config)
                or "我是 MyAgentic 的本地代码助手，可以帮你检索和分析已入库仓库的代码、文档、图片，也可以回答项目概览、技术栈和使用方式。",
                "results": [],
                "tool": "direct",
            }
        if tool == "app_guide":
            return {
                "session": session,
                "answer": _app_guide_answer(message)
                or (
                    "当前使用方式：先通过 GitHub 登录，在仓库列表选择公开仓库并点击“入库”，"
                    "等待状态变为已入库后，再到聊天页提问代码、文档、图片或项目概览。"
                ),
                "results": [],
                "tool": "app_guide",
            }
        if tool == "general_chat":
            return _general_chat_plan(session, message, config)
        if tool == "repo_brief":
            return {
                "session": session,
                "answer": _repo_brief_text(repos, language_counts),
                "results": [],
                "tool": "repo_brief",
            }
        if tool == "project_intro":
            intro_answer = _project_intro_answer(message, repos, recent, language_counts)
            if intro_answer is None and selection.project_id:
                for repo in repos:
                    if repo.full_name == selection.project_id:
                        intro_answer = _format_project_intro(repo, language_counts)
                        break
            return {
                "session": session,
                "answer": intro_answer
                or "请告诉我你想了解哪个仓库，例如 `Lmeet61713/YueDu`。",
                "results": [],
                "tool": "project_intro",
            }
        if tool == "repo_meta":
            repo_meta_answer = _repo_meta_answer(message, repos)
            return {
                "session": session,
                "answer": repo_meta_answer
                or "请告诉我你想查询仓库的哪类元数据，例如创建时间或仓库列表。",
                "results": [],
                "tool": "repo_meta",
            }
        if tool == "read_file":
            content = None
            if selection.project_id and selection.path:
                owner, _, repo = selection.project_id.partition("/")
                content = await read_project_file(owner, repo, selection.path)
            return {
                "session": session,
                "answer": f"文件内容：\n\n{content}" if content else "未找到该文件，请确认路径是否正确。",
                "results": [],
                "tool": "read_file",
            }
        project_id_from_message, _ = _route(message)
        memories = await memory.recall_long_term(
            db,
            user_id,
            message,
            project_id=selection.project_id or project_id_from_message,
        )
        graph = _build_graph()
        state = {
            "db": db,
            "user_id": user_id,
            "message": message,
            "session": session,
            "config": config,
            "fallback_config": fallback_config,
            "tool": tool,
            "project_id": selection.project_id,
            "file_type": {
                "doc_search": "doc",
                "image_search": "image",
            }.get(tool),
        }
        if graph is None:
            state = await _manual_retrieve_loop(state)
        else:
            state = await graph.ainvoke(state)
        if state.get("out_of_scope"):
            return _out_of_scope_plan(session, message, config)
        state["context"] = _build_context(recent[-10:], memories, state.get("results", []))
        state.update(
            {
                "config": config,
                "fallback_config": fallback_config,
                "recent": recent,
                "memories": memories,
                "session": session,
            }
        )
        return state

    direct = _direct_answer(message, config)
    if direct:
        return {"session": session, "answer": direct, "results": [], "tool": "direct"}

    app_guide = _app_guide_answer(message)
    if app_guide:
        return {"session": session, "answer": app_guide, "results": [], "tool": "app_guide"}

    intro_answer = _project_intro_answer(message, repos, recent, language_counts)
    if intro_answer:
        return {"session": session, "answer": intro_answer, "results": [], "tool": "project_intro"}
    if not _is_tech_query(message):
        repo_meta = _repo_meta_answer(message, repos)
        if repo_meta:
            return {"session": session, "answer": repo_meta, "results": [], "tool": "repo_meta"}

    project_id_from_message, _ = _route(message)
    memories = await memory.recall_long_term(
        db,
        user_id,
        message,
        project_id=project_id_from_message,
    )
    graph = _build_graph()
    state = {
        "db": db,
        "user_id": user_id,
        "message": message,
        "session": session,
        "config": config,
        "fallback_config": fallback_config,
    }
    if graph is None:
        state = await _manual_retrieve_loop(state)
    else:
        state = await graph.ainvoke(state)
    if state.get("out_of_scope"):
        return _out_of_scope_plan(session, message, config)
    state["context"] = _build_context(recent[-10:], memories, state.get("results", []))
    state.update(
        {
            "config": config,
            "fallback_config": fallback_config,
            "recent": recent,
            "memories": memories,
            "session": session,
        }
    )
    return state


async def _stream_llm(config: dict, system: str, user: str):
    import json

    base_url = config["base_url"].rstrip("/")
    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]
    try:
        async with httpx.AsyncClient(timeout=120) as client:
            if config.get("provider") == "ollama" and not base_url.endswith("/v1"):
                url = f"{base_url}/api/chat"
                headers = {}
                payload = {"model": config["model"], "messages": messages, "stream": True}
                async with client.stream("POST", url, headers=headers, json=payload) as response:
                    response.raise_for_status()
                    async for line in response.aiter_lines():
                        if not line.strip():
                            continue
                        try:
                            data = json.loads(line)
                        except Exception as exc:
                            logger.warning("Ollama stream parse failed: %s", exc)
                            continue
                        content = data.get("message", {}).get("content")
                        if content:
                            yield content
            else:
                url = f"{base_url}/chat/completions"
                headers = {"Authorization": f"Bearer {config['api_key']}"}
                payload = {
                    "model": config["model"],
                    "messages": messages,
                    "stream": True,
                }
                async with client.stream("POST", url, headers=headers, json=payload) as response:
                    response.raise_for_status()
                    async for line in response.aiter_lines():
                        if not line.startswith("data:"):
                            continue
                        data_line = line[5:].strip()
                        if data_line == "[DONE]":
                            break
                        try:
                            data = json.loads(data_line)
                        except Exception as exc:
                            logger.warning("OpenAI-compatible stream parse failed: %s", exc)
                            continue
                        delta = data.get("choices", [{}])[0].get("delta", {}).get("content")
                        if delta:
                            yield delta
    except Exception:
        return


async def ask(
    db: AsyncSession,
    user_id: int,
    message: str,
    session_id: int | None = None,
) -> tuple[int, str, list[dict], str]:
    plan = await _plan(db, user_id, message, session_id)
    session = plan["session"]
    results = plan.get("results", [])
    tool = plan.get("tool") or "search"
    answer = plan.get("answer")
    used_fallback = False
    system_prompt = plan.get("system") or _SYSTEM_PROMPT
    if plan.get("answer"):
        answer = plan["answer"]
    elif plan.get("config"):
        answer, used_fallback = await _call_llm_chain(
            plan["config"],
            plan.get("fallback_config"),
            system_prompt,
            f"问题：{message}\n\n{plan.get('context', '')}",
        )
    if not answer:
        answer = _fallback_answer(message, results, plan.get("config"), tool)

    await memory.save_message(
        db,
        session.id,
        "assistant",
        answer,
        sources=results,
        tool=tool,
        mode=_answer_mode(answer, tool, used_fallback),
    )
    await memory.maybe_save_summary(db, user_id, session.id)
    return session.id, answer, results, tool


async def ask_stream(
    db: AsyncSession,
    user_id: int,
    message: str,
    session_id: int | None = None,
):
    plan = await _plan(db, user_id, message, session_id)
    session = plan["session"]
    results = plan.get("results", [])
    tool = plan.get("tool") or "search"

    yield {"type": "start", "session_id": session.id}
    yield {"type": "tool", "tool": tool}
    if results:
        yield {"type": "sources", "sources": results}

    answer = plan.get("answer")
    used_fallback = False
    system_prompt = plan.get("system") or _SYSTEM_PROMPT
    if answer is None:
        answer = ""
        if plan.get("config") and not plan["config"].get("config_error"):
            async for chunk in _stream_llm(
                plan["config"],
                system_prompt,
                f"问题：{message}\n\n{plan.get('context', '')}",
            ):
                answer += chunk
                yield {"type": "token", "content": chunk}
        if not answer and plan.get("fallback_config"):
            used_fallback = True
            async for chunk in _stream_llm(
                plan["fallback_config"],
                system_prompt,
                f"问题：{message}\n\n{plan.get('context', '')}",
            ):
                answer += chunk
                yield {"type": "token", "content": chunk}
        if not answer:
            answer = _fallback_answer(message, results, plan.get("config"), tool)
            for chunk in _split_chunks(answer):
                yield {"type": "token", "content": chunk}
    else:
        for chunk in _split_chunks(answer):
            yield {"type": "token", "content": chunk}

    await memory.save_message(
        db,
        session.id,
        "assistant",
        answer,
        sources=results,
        tool=tool,
        mode=_answer_mode(answer, tool, used_fallback),
    )
    await memory.maybe_save_summary(db, user_id, session.id)
    yield {
        "type": "done",
        "session_id": session.id,
        "mode": (
            "config_error"
            if tool == "config_error"
            else "fallback_llm"
            if used_fallback
            else "fallback" if plan.get("answer") or not plan.get("config") else "llm"
        ),
        "tool": tool,
    }
