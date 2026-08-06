import base64
import hashlib
import json
import re
import threading
from dataclasses import dataclass, field
from pathlib import Path

import httpx

from backend.app.config import get_settings
from backend.app.services import sync_service

CODE_LANGUAGES = {
    ".py": "python",
    ".js": "javascript",
    ".jsx": "javascriptreact",
    ".ts": "typescript",
    ".tsx": "typescriptreact",
    ".java": "java",
    ".go": "go",
    ".rs": "rust",
    ".c": "c",
    ".h": "c",
    ".cpp": "cpp",
    ".hpp": "cpp",
    ".cs": "csharp",
    ".rb": "ruby",
    ".php": "php",
    ".swift": "swift",
    ".kt": "kotlin",
    ".sh": "shell",
    ".bash": "shell",
    ".sql": "sql",
    ".html": "html",
    ".css": "css",
    ".scss": "scss",
    ".vue": "vue",
    ".svelte": "svelte",
    ".json": "json",
    ".yaml": "yaml",
    ".yml": "yaml",
    ".toml": "toml",
    ".ini": "ini",
}

DOC_LANGUAGES = {
    ".md": "markdown",
    ".markdown": "markdown",
    ".txt": "text",
    ".rst": "rst",
    ".adoc": "asciidoc",
}

IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".svg"}

_image_cache: dict[str, str] = {}
_image_cache_lock = threading.Lock()

IGNORE_DIR_NAMES = {
    ".git",
    ".venv",
    "venv",
    "node_modules",
    "dist",
    "build",
    "__pycache__",
    ".idea",
    ".vscode",
    "artifacts",
    "logs",
    "storage",
    "data",
}

IGNORE_FILE_NAMES = {".DS_Store", "Thumbs.db", "*.pyc", "*.class", "*.jar", "*.zip", "*.tar.gz", "*.7z", "*.exe", "*.dll"}

FUNCTION_PATTERN = re.compile(
    r"^(?P<symbol>(?:async\s+)?(?:def|class|function|func|fn|public\s+(?:static\s+)?\w+|"
    r"private\s+(?:static\s+)?\w+|protected\s+(?:static\s+)?\w+)\s+\w+)",
    re.IGNORECASE,
)


@dataclass
class DocumentChunk:
    project_id: str
    path: str
    file_type: str
    text: str
    language: str | None = None
    file_hash: str | None = None
    chunk_index: int = 0
    symbol: str | None = None
    metadata: dict = field(default_factory=dict)


def _image_cache_path() -> Path:
    return get_settings().data_dir / "image_descriptions.json"


def _load_image_cache() -> dict[str, str]:
    global _image_cache
    if _image_cache:
        return _image_cache
    path = _image_cache_path()
    if path.exists():
        try:
            _image_cache = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            _image_cache = {}
    return _image_cache


def _save_image_cache() -> None:
    path = _image_cache_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(_image_cache, ensure_ascii=False, indent=2), encoding="utf-8")


def _is_ignored(rel_path: Path) -> bool:
    parts = rel_path.parts
    if any(part in IGNORE_DIR_NAMES for part in parts):
        return True
    name = rel_path.name
    if name in IGNORE_FILE_NAMES:
        return True
    return any(name.endswith(suffix) for suffix in IGNORE_FILE_NAMES if suffix.startswith("*"))


def detect_type(path: Path) -> tuple[str, str | None]:
    suffix = path.suffix.lower()
    if suffix in CODE_LANGUAGES:
        return "code", CODE_LANGUAGES[suffix]
    if suffix in DOC_LANGUAGES:
        return "doc", DOC_LANGUAGES[suffix]
    if suffix in IMAGE_EXTENSIONS:
        return "image", None
    return "other", None


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def scan_files(repo_dir: Path) -> list[Path]:
    files: list[Path] = []
    for path in repo_dir.rglob("*"):
        if not path.is_file():
            continue
        rel = path.relative_to(repo_dir)
        if _is_ignored(rel):
            continue
        files.append(path)
    return files


def chunk_text(text: str, chunk_size: int | None = None, overlap: int | None = None) -> list[str]:
    settings = get_settings()
    size = chunk_size or settings.chunk_size
    overlap_n = overlap if overlap is not None else settings.chunk_overlap
    lines = text.splitlines()
    chunks: list[str] = []
    current: list[str] = []
    length = 0
    for line in lines:
        if length + len(line) > size and current:
            chunks.append("\n".join(current))
            keep = current[-overlap_n:] if overlap_n else []
            current = keep.copy()
            length = sum(len(item) for item in current)
        current.append(line)
        length += len(line) + 1
    if current:
        chunks.append("\n".join(current))
    return chunks or [""]


def chunk_code(text: str) -> list[tuple[str, str | None]]:
    chunks: list[tuple[str, str | None]] = []
    current_symbol: str | None = None
    current: list[str] = []
    length = 0
    settings = get_settings()
    for line in text.splitlines():
        match = FUNCTION_PATTERN.match(line.strip())
        if match:
            current_symbol = match.group("symbol")
        if length + len(line) > settings.chunk_size and current:
            chunks.append(("\n".join(current), current_symbol))
            current = []
            length = 0
        current.append(line)
        length += len(line) + 1
    if current:
        chunks.append(("\n".join(current), current_symbol))
    return chunks


async def describe_image(
    path: Path,
    file_hash: str | None = None,
    display_path: str | None = None,
) -> str:
    settings = get_settings()
    fallback = f"图片资源 {display_path or path.name}"
    cache = _load_image_cache()
    if file_hash and file_hash in cache:
        return cache[file_hash]
    if not settings.dashscope_api_key:
        return fallback
    model = settings.dashscope_vl_model or ""
    if not model:
        return fallback
    suffix = path.suffix.lower().lstrip(".")
    mime = f"image/{suffix}" if suffix in {"png", "jpeg", "jpg", "gif", "webp", "bmp"} else "image/png"
    data_url = f"data:{mime};base64,{base64.b64encode(path.read_bytes()).decode()}"
    try:
        async with httpx.AsyncClient(timeout=60) as client:
            response = await client.post(
                f"{settings.dashscope_base_url}/chat/completions",
                headers={"Authorization": f"Bearer {settings.dashscope_api_key}"},
                json={
                    "model": model,
                    "messages": [
                        {
                            "role": "user",
                            "content": [
                                {"type": "text", "text": "用中文简要描述这张图片的内容，适合用于检索。"},
                                {"type": "image_url", "image_url": {"url": data_url}},
                            ],
                        }
                    ],
                },
            )
            response.raise_for_status()
            data = response.json()
            description = data["choices"][0]["message"]["content"]
            if file_hash:
                with _image_cache_lock:
                    _image_cache[file_hash] = description
                    _save_image_cache()
            return description
    except Exception:
        return fallback


async def build_document_chunks(owner: str, repo: str) -> tuple[list[DocumentChunk], list[dict]]:
    repo_dir = sync_service.repo_mirror_path(owner, repo)
    project_id = f"{owner}/{repo}"
    chunks: list[DocumentChunk] = []
    manifest: list[dict] = []
    settings = get_settings()

    for path in scan_files(repo_dir):
        rel = path.relative_to(repo_dir).as_posix()
        file_type, language = detect_type(path)
        try:
            size = path.stat().st_size
            if size > settings.max_file_size_mb * 1024 * 1024:
                manifest.append(
                    {"path": rel, "file_type": file_type, "language": language, "size": size, "file_hash": "", "skipped": "too_large"}
                )
                continue
        except OSError:
            continue

        file_hash = file_sha256(path)
        manifest.append(
            {"path": rel, "file_type": file_type, "language": language, "size": size, "file_hash": file_hash, "skipped": ""}
        )

        if file_type == "image":
            description = await describe_image(path, file_hash, display_path=rel)
            chunks.append(
                DocumentChunk(
                    project_id=project_id,
                    path=rel,
                    file_type="image",
                    language=None,
                    text=description,
                    file_hash=file_hash,
                    chunk_index=0,
                    metadata={"original_file": rel},
                )
            )
            continue

        if file_type not in {"code", "doc"}:
            continue

        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue

        if file_type == "code":
            pieces = chunk_code(text)
            for index, (piece, symbol) in enumerate(pieces):
                chunks.append(
                    DocumentChunk(
                        project_id=project_id,
                        path=rel,
                        file_type="code",
                        language=language,
                        text=piece,
                        file_hash=file_hash,
                        chunk_index=index,
                        symbol=symbol,
                    )
                )
        else:
            for index, piece in enumerate(chunk_text(text)):
                chunks.append(
                    DocumentChunk(
                        project_id=project_id,
                        path=rel,
                        file_type="doc",
                        language=language,
                        text=piece,
                        file_hash=file_hash,
                        chunk_index=index,
                    )
                )
    from backend.app.services.tech_summary import build_project_summary

    summary_chunk, summary_entry = build_project_summary(project_id, manifest, chunks)
    chunks.append(summary_chunk)
    manifest.append(summary_entry)
    return chunks, manifest
