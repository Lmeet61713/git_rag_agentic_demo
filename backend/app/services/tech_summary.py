import hashlib
import json
import re
from collections import Counter

CONFIG_NAMES = {
    "package.json": "javascript",
    "requirements.txt": "python",
    "pyproject.toml": "python",
    "go.mod": "go",
    "cargo.toml": "rust",
    "composer.json": "php",
    "pom.xml": "java",
    "build.gradle": "java",
    "Gemfile": "ruby",
}


def _read_config(chunks, path_suffix: str) -> str:
    for chunk in chunks:
        if chunk.path.lower().endswith(path_suffix):
            return chunk.text[:1200]
    return ""


def _config_tech_stack(chunks) -> set[str]:
    tech: set[str] = set()
    package_text = _read_config(chunks, "package.json")
    if package_text:
        try:
            start = package_text.find("{")
            end = package_text.rfind("}")
            data = json.loads(package_text[start : end + 1])
            for section in ("dependencies", "devDependencies"):
                tech.update(data.get(section, {}).keys())
        except Exception:
            tech.update(re.findall(r'"([A-Za-z0-9_.@/-]+)"\s*:', package_text))
    for name, language in CONFIG_NAMES.items():
        if name == "package.json":
            continue
        text = _read_config(chunks, name)
        if text:
            tech.add(language)
    return tech


def build_project_summary(project_id: str, manifest: list[dict], chunks: list) -> tuple:
    from backend.app.services.parser_service import DocumentChunk

    files = [item for item in manifest if not item.get("skipped")]
    languages = Counter(item.get("language") for item in files if item.get("language"))
    file_types = Counter(item.get("file_type") for item in files if item.get("file_type"))
    top_dirs = Counter(item["path"].split("/", 1)[0] for item in files if "/" in item["path"])
    tech = _config_tech_stack(chunks)
    if languages:
        tech.update(languages.keys())
    readme = next(
        (
            chunk
            for chunk in chunks
            if chunk.path.rsplit("/", 1)[-1].lower().startswith("readme")
        ),
        None,
    )
    lines = [
        f"项目：{project_id}",
        f"技术栈：{'、'.join(sorted(tech)) or '未识别'}",
        f"主要语言：{'、'.join(f'{name} {count}' for name, count in languages.most_common(8)) or '无'}",
        f"文件类型：{('、'.join(f'{name} {count}' for name, count in file_types.most_common())) or '无'}",
        f"主要目录：{'、'.join(f'{name} {count}' for name, count in top_dirs.most_common(8)) or '无'}",
    ]
    if readme:
        lines.append(f"README 摘要：{readme.text.strip().replace(chr(10), ' ')[:600]}")
    summary = "\n".join(lines)
    file_hash = hashlib.sha256(summary.encode("utf-8")).hexdigest()
    primary_languages = "、".join(
        f"{name} {count}" for name, count in languages.most_common(8)
    )
    chunk = DocumentChunk(
        project_id=project_id,
        path=".project_summary.md",
        file_type="project_summary",
        text=summary,
        language=None,
        file_hash=file_hash,
        chunk_index=0,
        metadata={
            "tech_stack": "、".join(sorted(tech)),
            "languages": "、".join(sorted(tech)),
            "primary_languages": primary_languages,
        },
    )
    entry = {
        "path": ".project_summary.md",
        "file_type": "project_summary",
        "language": None,
        "size": len(summary.encode("utf-8")),
        "file_hash": file_hash,
        "skipped": "",
    }
    return chunk, entry
