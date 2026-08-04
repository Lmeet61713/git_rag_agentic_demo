from fastapi import APIRouter, Depends

from backend.app.api.deps import get_current_user
from backend.app.models import User
from backend.app.schemas import SearchResponse
from backend.app.services import retrieval

router = APIRouter()


@router.get("/search", response_model=SearchResponse)
async def search(
    q: str,
    project_id: str | None = None,
    file_type: str | None = None,
    user: User = Depends(get_current_user),
):
    results = await retrieval.search(q, project_id=project_id, file_type=file_type)
    return SearchResponse(query=q, results=results)


@router.get("/search/overview", response_model=SearchResponse)
async def search_overview(
    project_id: str,
    user: User = Depends(get_current_user),
):
    results = await retrieval.project_overview(project_id)
    return SearchResponse(query="项目概览", results=results)
