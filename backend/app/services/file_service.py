from backend.app.services.sync_service import repo_mirror_path


async def read_project_file(
    owner: str,
    repo: str,
    path: str,
    max_chars: int = 12000,
) -> str | None:
    mirror = repo_mirror_path(owner, repo).resolve()
    target = (mirror / path).resolve()
    if mirror not in target.parents and target != mirror:
        return None
    if not target.is_file():
        return None
    try:
        text = target.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    if len(text) > max_chars:
        text = text[:max_chars] + "\n...[内容过长已截断]"
    return text
