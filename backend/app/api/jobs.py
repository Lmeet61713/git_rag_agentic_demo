from fastapi import APIRouter, Depends, HTTPException

from backend.app.api.deps import get_current_user
from backend.app.models import User
from backend.app.schemas import IndexJobOut
from backend.app.services import index_service

router = APIRouter()


@router.get("/{job_id}", response_model=IndexJobOut)
async def get_job(job_id: int, user: User = Depends(get_current_user)):
    job = await index_service.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="任务不存在")
    return IndexJobOut.model_validate(job)
