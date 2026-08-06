import json
import re
from typing import Literal

from pydantic import BaseModel, Field

ToolName = Literal[
    "direct",
    "app_guide",
    "general_chat",
    "project_intro",
    "repo_meta",
    "repo_brief",
    "repo_tech",
    "overview",
    "doc_search",
    "image_search",
    "search",
    "read_file",
]


class ToolSelection(BaseModel):
    tool: ToolName = Field(description="本次回答应该使用的工具名称")
    project_id: str | None = Field(
        default=None,
        description="目标仓库的 owner/repo；仅在问题明确指定仓库时填写",
    )
    path: str | None = Field(
        default=None,
        description="需要读取的仓库内文件路径；仅 read_file 使用",
    )
    reason: str = Field(
        default="",
        description="选择该工具的原因，简短说明为什么不该使用其他工具",
    )


TOOL_CATALOG = [
    {
        "name": "direct",
        "description": "直接回答助手身份、能力、问候或当前模型信息",
        "when_to_use": "用户只是问你能做什么、你是谁、模型是什么，不涉及具体仓库内容",
        "retrieval": False,
    },
    {
        "name": "app_guide",
        "description": "回答 MyAgentic 应用使用方式、入库、同步、支持能力",
        "when_to_use": "用户问怎么使用本应用、怎么入库、是否支持某项功能",
        "retrieval": False,
    },
    {
        "name": "general_chat",
        "description": "回答天气、闲聊、生活或个人信息等与仓库无关的话题",
        "when_to_use": "用户问题与代码、文档、图片和仓库无关，属于普通闲聊或生活问题",
        "retrieval": False,
    },
    {
        "name": "project_intro",
        "description": "介绍某个仓库的项目概况",
        "when_to_use": "用户要求简单介绍、概述某个项目，不需要具体代码证据",
        "retrieval": False,
    },
    {
        "name": "repo_meta",
        "description": "查询仓库创建时间、排序或仓库列表",
        "when_to_use": "用户问最早/最近创建、仓库列表、按时间排序",
        "retrieval": False,
    },
    {
        "name": "repo_brief",
        "description": "列出所有已入库仓库的名称、一句话简介和主要语言",
        "when_to_use": "用户问仓库里有什么项目、大概有哪些仓库、简单介绍所有仓库",
        "retrieval": False,
    },
    {
        "name": "repo_tech",
        "description": "按技术栈或语言查找仓库",
        "when_to_use": "用户问哪些仓库用了 Vue/FastAPI/Python 等技术",
        "retrieval": True,
    },
    {
        "name": "overview",
        "description": "项目概览与目录结构检索",
        "when_to_use": "用户问项目大致有什么、目录结构、功能模块",
        "retrieval": True,
    },
    {
        "name": "doc_search",
        "description": "检索 README、文档、说明、教程",
        "when_to_use": "用户问文档内容、安装步骤、使用说明",
        "retrieval": True,
    },
    {
        "name": "image_search",
        "description": "检索图片、截图、logo、banner",
        "when_to_use": "用户要找图片或视觉资源",
        "retrieval": True,
    },
    {
        "name": "search",
        "description": "通用向量检索代码、文档、图片",
        "when_to_use": "用户询问具体代码实现、跨仓库内容，且没有更适合的专用工具",
        "retrieval": True,
    },
    {
        "name": "read_file",
        "description": "直接读取仓库内指定文件",
        "when_to_use": "用户明确要求读取某个 owner/repo/path 文件",
        "retrieval": False,
    },
]


def tool_catalog_text() -> str:
    lines = ["可用工具："]
    for item in TOOL_CATALOG:
        lines.append(
            f"- {item['name']}：{item['description']}；"
            f"使用场景：{item['when_to_use']}；"
            f"是否需要检索：{'是' if item['retrieval'] else '否'}"
        )
    return "\n".join(lines)


def extract_tool_selection_json(text: str) -> dict | None:
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if not match:
        return None
    try:
        data = json.loads(match.group(0))
    except Exception:
        return None
    return data if isinstance(data, dict) else None
