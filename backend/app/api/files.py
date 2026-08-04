from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse

from backend.app.api.deps import get_current_user
from backend.app.models import User
from backend.app.services.sync_service import repo_mirror_path

router = APIRouter()


@router.get("/{owner}/{repo}/{path:path}")
async def serve_file(
    owner: str,
    repo: str,
    path: str,
    user: User = Depends(get_current_user),
):
    mirror = repo_mirror_path(owner, repo).resolve()
    target = (mirror / path).resolve()
    if mirror not in target.parents and target != mirror:
        raise HTTPException(status_code=400, detail="非法路径")
    if not target.is_file():
        raise HTTPException(status_code=404, detail="文件不存在")
    return FileResponse(target)
