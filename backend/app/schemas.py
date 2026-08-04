from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class UserOut(ORMModel):
    id: int
    github_id: str
    username: str
    avatar_url: str | None = None


class RepoOut(ORMModel):
    id: int
    owner: str
    repo: str
    full_name: str
    html_url: str = ""
    default_branch: str = "main"
    last_commit_sha: str | None = None
    index_status: str = "not_indexed"
    last_indexed_at: datetime | None = None


class IndexJobOut(ORMModel):
    id: int
    repo_id: int
    status: str
    stage: str
    progress: int
    error: str | None = None
    created_at: datetime
    updated_at: datetime


class ChatMessageOut(ORMModel):
    id: int
    session_id: int
    role: str
    content: str
    sources: list = Field(default_factory=list)
    created_at: datetime


class SearchSource(BaseModel):
    project_id: str
    path: str
    file_type: str
    language: str | None = None
    text: str
    score: float = 0.0


class SearchResponse(BaseModel):
    query: str
    results: list[SearchSource] = Field(default_factory=list)


class ChatRequest(BaseModel):
    session_id: int | None = None
    message: str


class ChatResponse(BaseModel):
    session_id: int
    answer: str
    sources: list[SearchSource] = Field(default_factory=list)


class ModelConfigIn(BaseModel):
    provider: str
    model_name: str = ""
    api_key: str = ""
    base_url: str = ""
    is_active: bool = False


class ModelConfigOut(ORMModel):
    id: int
    provider: str
    model_name: str
    base_url: str
    is_active: bool
    has_api_key: bool = False
    updated_at: datetime


class MemoryEntryOut(ORMModel):
    id: int
    user_id: int
    session_id: int | None = None
    project_id: str | None = None
    type: str = "long_term"
    content: str
    created_at: datetime
    updated_at: datetime


class MemoryEntryIn(BaseModel):
    content: str
    project_id: str | None = None
    session_id: int | None = None
    type: str = "long_term"


class MemoryEntryUpdate(BaseModel):
    content: str | None = None
    project_id: str | None = None
    session_id: int | None = None
    type: str | None = None
