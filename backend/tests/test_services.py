from pathlib import Path

import pytest
from sqlalchemy import select

from backend.app import database
from backend.app.database import create_tables, init_database
from backend.app.models import Repo, User
from backend.app.security import encrypt_secret
from backend.app.services import agent, index_service, memory, repo_service, retrieval
from backend.app.services.embedding import HashEmbedding
from backend.app.services.github import GitHubClient
from backend.app.services.parser_service import DocumentChunk, chunk_text, detect_type
from backend.app.services.vector_store import SqliteVectorStore


def test_chunk_text():
    text = "\n".join(f"line {index}" for index in range(20))
    chunks = chunk_text(text, chunk_size=30, overlap=2)
    assert len(chunks) >= 2
    assert "".join(chunks)


def test_detect_type():
    assert detect_type(Path("src/main.py")) == ("code", "python")
    assert detect_type(Path("README.md")) == ("doc", "markdown")
    assert detect_type(Path("assets/logo.png")) == ("image", None)


def test_hash_embedding():
    embedding = HashEmbedding()
    vectors = embedding.embed(["hello world", "世界 你好"])
    assert len(vectors) == 2
    assert all(len(vector) == HashEmbedding.dim for vector in vectors)


def test_plan_incremental():
    chunks = [
        DocumentChunk(project_id="a/b", path="README.md", file_type="doc", text="new", file_hash="h1"),
        DocumentChunk(project_id="a/b", path="src/main.py", file_type="code", text="new code", file_hash="h2"),
        DocumentChunk(project_id="a/b", path="unchanged.py", file_type="code", text="old", file_hash="h3"),
    ]
    manifest = [
        {"path": "README.md", "file_hash": "h1"},
        {"path": "src/main.py", "file_hash": "h2"},
        {"path": "unchanged.py", "file_hash": "h3"},
    ]
    previous = {"unchanged.py": "h3", "deleted.py": "old"}
    embed_chunks, touched = index_service.plan_incremental(chunks, manifest, previous)
    assert {chunk.path for chunk in embed_chunks} == {"README.md", "src/main.py"}
    assert touched == {"README.md", "src/main.py", "deleted.py"}


@pytest.mark.asyncio
async def test_sync_repos_persists_full_name(monkeypatch):
    init_database()
    await create_tables()

    async def fake_list_public_repos(self):
        return [
            {
                "full_name": "owner/demo",
                "owner": {"login": "owner"},
                "name": "demo",
                "html_url": "https://github.com/owner/demo",
                "default_branch": "main",
            }
        ]

    monkeypatch.setattr(GitHubClient, "list_public_repos", fake_list_public_repos)
    async with database.session_factory() as db:
        user = User(
            github_id="4",
            username="tester4",
            access_token_enc=encrypt_secret("fake-token"),
        )
        db.add(user)
        await db.commit()
        await db.refresh(user)
        await repo_service.sync_repos_from_github(db, user)
        repo = await db.execute(select(Repo).where(Repo.user_id == user.id))
        saved = repo.scalar_one()
        assert saved.full_name == "owner/demo"


@pytest.mark.asyncio
async def test_memory_flow():
    init_database()
    await create_tables()
    async with database.session_factory() as db:
        user = User(github_id="1", username="tester")
        db.add(user)
        await db.commit()
        await db.refresh(user)

        session = await memory.ensure_session(db, user.id)
        await memory.save_message(db, session.id, "user", "你好")
        messages = await memory.recent_messages(db, session.id)
        assert len(messages) == 1

        await memory.save_long_term_memory(db, user.id, "用户偏好 Python", project_id="a/b")
        recalled = await memory.recall_long_term(db, user.id, "python")
        assert len(recalled) == 1


@pytest.mark.asyncio
async def test_memory_crud():
    init_database()
    await create_tables()
    async with database.session_factory() as db:
        user = User(github_id="3", username="tester3")
        db.add(user)
        await db.commit()
        await db.refresh(user)

        entry = await memory.create_memory(db, user.id, "用户偏好 Python", project_id="a/b")
        listed = await memory.list_memory(db, user.id, project_id="a/b")
        assert len(listed) == 1
        assert listed[0].content == "用户偏好 Python"

        await memory.update_memory(db, entry, content="用户偏好 Rust")
        assert entry.content == "用户偏好 Rust"

        await memory.delete_memory(db, entry)
        assert await memory.list_memory(db, user.id) == []


@pytest.mark.asyncio
async def test_sqlite_vector_store():
    init_database()
    await create_tables()
    store = SqliteVectorStore()
    vector = [1.0, 0.0, 0.0]
    await store.upsert(
        [
            {
                "id": "a/b:README.md:0",
                "project_id": "a/b",
                "path": "README.md",
                "file_type": "doc",
                "language": "markdown",
                "text": "installation guide",
                "vector": vector,
            }
        ]
    )
    results = await store.query(vector, top_k=5, filters={"project_id": "a/b", "file_type": "doc"})
    assert len(results) == 1
    assert results[0]["path"] == "README.md"


@pytest.mark.asyncio
async def test_project_overview_prioritizes_readme():
    init_database()
    await create_tables()
    store = SqliteVectorStore()
    vector = [1.0, 0.0, 0.0]
    await store.upsert(
        [
            {
                "id": "c/d:README.md:0",
                "project_id": "c/d",
                "path": "README.md",
                "file_type": "doc",
                "language": "markdown",
                "text": "This project provides an installation guide and architecture overview.",
                "vector": vector,
            },
            {
                "id": "c/d:docs/setup.md:0",
                "project_id": "c/d",
                "path": "docs/setup.md",
                "file_type": "doc",
                "language": "markdown",
                "text": "Setup instructions for local development.",
                "vector": vector,
            },
        ]
    )
    results = await retrieval.project_overview("c/d", top_k=5)
    assert results
    assert results[0]["path"] == "README.md"
    await store.delete("c/d")


@pytest.mark.asyncio
async def test_agent_fallback_answer_with_sources():
    init_database()
    await create_tables()
    store = SqliteVectorStore()
    await store.upsert(
        [
            {
                "id": "a/b:README.md:0",
                "project_id": "a/b",
                "path": "README.md",
                "file_type": "doc",
                "language": "markdown",
                "text": "This project includes an installation guide for local setup.",
                "vector": [1.0, 0.0, 0.0],
            }
        ]
    )
    async with database.session_factory() as db:
        user = User(github_id="2", username="tester2")
        db.add(user)
        await db.commit()
        await db.refresh(user)
        session_id, answer, sources = await agent.ask(db, user.id, "how to install")
        assert session_id is not None
        assert "README.md" in answer
        assert len(sources) == 1
        assert sources[0]["path"] == "README.md"
