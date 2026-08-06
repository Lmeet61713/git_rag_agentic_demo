from pathlib import Path

import pytest
from sqlalchemy import select

from backend.app import database
from backend.app.config import get_settings
from backend.app.database import create_tables, init_database
from backend.app.models import ChatMessage, ModelConfig, Repo, User
from backend.app.security import encrypt_secret
from backend.app.services import (
    agent,
    index_service,
    memory,
    model_config,
    repo_service,
    retrieval,
    sync_service,
    vector_store,
)
from backend.app.services.embedding import HashEmbedding
from backend.app.services.github import GitHubClient
from backend.app.services.parser_service import (
    DocumentChunk,
    chunk_text,
    describe_image,
    detect_type,
)
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


def test_build_index_summary():
    manifest = [
        {"path": "README.md", "file_type": "doc", "language": "markdown", "size": 120, "file_hash": "h1", "skipped": ""},
        {"path": "src/main.py", "file_type": "code", "language": "python", "size": 80, "file_hash": "h2", "skipped": ""},
        {"path": "assets/logo.png", "file_type": "image", "language": None, "size": 40, "file_hash": "h3", "skipped": ""},
    ]
    chunks = [
        DocumentChunk(project_id="a/b", path="README.md", file_type="doc", text="README 项目介绍", language="markdown"),
        DocumentChunk(project_id="a/b", path="src/main.py", file_type="code", text="def main(): pass", language="python"),
    ]
    summary = index_service.build_index_summary(manifest, chunks, commit_sha="abc123")
    assert "3 个文件" in summary
    assert "图片 1 个" in summary
    assert "README 摘录" in summary
    assert "abc123" in summary


def test_build_context_includes_history():
    messages = [
        ChatMessage(role="user", content="上一轮的问题"),
        ChatMessage(role="assistant", content="上一轮的答案"),
    ]
    context = agent._build_context(messages, [], [])
    assert "历史对话" in context
    assert "上一轮的问题" in context
    assert "上一轮的答案" in context


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
async def test_recall_long_term_chinese_filter_and_project_isolation():
    init_database()
    await create_tables()
    async with database.session_factory() as db:
        user = User(github_id="15", username="memory-scope-tester")
        db.add(user)
        await db.commit()
        await db.refresh(user)
        await memory.save_long_term_memory(
            db,
            user.id,
            "用户偏好 Vue 前端开发",
            project_id="a/frontend",
        )
        await memory.save_long_term_memory(
            db,
            user.id,
            "用户偏好 Python 后端开发",
            project_id="b/backend",
        )

        recalled = await memory.recall_long_term(db, user.id, "Vue 前端")
        assert [entry.project_id for entry in recalled] == ["a/frontend"]

        recalled = await memory.recall_long_term(
            db,
            user.id,
            "python",
            project_id="a/frontend",
        )
        assert recalled == []

        recalled = await memory.recall_long_term(db, user.id, "完全不相关的词xyz")
        assert recalled == []


@pytest.mark.asyncio
async def test_chat_message_persists_tool_and_mode():
    init_database()
    await create_tables()
    async with database.session_factory() as db:
        user = User(github_id="16", username="message-meta-tester")
        db.add(user)
        await db.commit()
        await db.refresh(user)
        session = await memory.ensure_session(db, user.id)
        message = await memory.save_message(
            db,
            session.id,
            "assistant",
            "检索到 README 内容",
            sources=[],
            tool="doc_search",
            mode="llm",
        )
        assert message.tool == "doc_search"
        assert message.mode == "llm"
        loaded = await memory.recent_messages(db, session.id)
        assert loaded[0].tool == "doc_search"
        assert loaded[0].mode == "llm"


@pytest.mark.asyncio
async def test_image_description_fallback_includes_relative_path(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "dashscope_api_key", "")
    description = await describe_image(Path("assets/logo.png"), display_path="assets/logo.png")
    assert "assets/logo.png" in description


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
async def test_image_retrieval_returns_image_source(monkeypatch):
    init_database()
    await create_tables()
    monkeypatch.setattr(retrieval, "get_embedding", lambda: HashEmbedding())
    monkeypatch.setattr(vector_store, "get_vector_store", lambda: SqliteVectorStore())
    store = SqliteVectorStore()
    await store.upsert(
        [
            {
                "id": "img/demo:assets/logo.png:0",
                "project_id": "img/demo",
                "path": "assets/logo.png",
                "file_type": "image",
                "language": None,
                "text": "logo banner 红色主视觉",
                "vector": [1.0, 0.0, 0.0],
            }
        ]
    )
    results = await retrieval.search("logo", project_id="img/demo", file_type="image")
    assert results
    assert results[0]["file_type"] == "image"
    assert results[0]["path"] == "assets/logo.png"


@pytest.mark.asyncio
async def test_project_overview_prioritizes_readme(monkeypatch):
    init_database()
    await create_tables()
    monkeypatch.setattr(retrieval, "get_embedding", lambda: HashEmbedding())
    monkeypatch.setattr(vector_store, "get_vector_store", lambda: SqliteVectorStore())
    store = SqliteVectorStore()
    embedding = HashEmbedding()
    readme_vector, setup_vector = embedding.embed(
        [
            "这是一个项目介绍，包含项目功能、架构、目录和安装使用说明。",
            "本地开发环境安装说明。",
        ]
    )
    await store.upsert(
        [
            {
                "id": "c/d:README.md:0",
                "project_id": "c/d",
                "path": "README.md",
                "file_type": "doc",
                "language": "markdown",
                "text": "这是一个项目介绍，包含项目功能、架构、目录和安装使用说明。",
                "vector": readme_vector,
            },
            {
                "id": "c/d:docs/setup.md:0",
                "project_id": "c/d",
                "path": "docs/setup.md",
                "file_type": "doc",
                "language": "markdown",
                "text": "本地开发环境安装说明。",
                "vector": setup_vector,
            },
        ]
    )
    results = await retrieval.project_overview("c/d", top_k=5)
    assert results
    assert results[0]["path"] == "README.md"
    await store.delete("c/d")


@pytest.mark.asyncio
async def test_agent_fallback_answer_with_sources(monkeypatch):
    init_database()
    await create_tables()
    monkeypatch.setattr(retrieval, "get_embedding", lambda: HashEmbedding())
    monkeypatch.setattr(vector_store, "get_vector_store", lambda: SqliteVectorStore())
    store = SqliteVectorStore()
    vector = HashEmbedding().embed(
        ["This project includes an installation guide for local setup."]
    )[0]
    await store.upsert(
        [
            {
                "id": "a/b:README.md:0",
                "project_id": "a/b",
                "path": "README.md",
                "file_type": "doc",
                "language": "markdown",
                "text": "This project includes an installation guide for local setup.",
                "vector": vector,
            }
        ]
    )
    async with database.session_factory() as db:
        user = User(github_id="2", username="tester2")
        db.add(user)
        await db.commit()
        await db.refresh(user)
        session_id, answer, sources, tool = await agent.ask(
            db,
            user.id,
            "installation guide a/b",
        )
        assert session_id is not None
        assert "README.md" in answer
        assert len(sources) == 1
        assert sources[0]["path"] == "README.md"
        assert tool == "search"


@pytest.mark.asyncio
async def test_sync_logs_roundtrip():
    init_database()
    await create_tables()
    async with database.session_factory() as db:
        user = User(github_id="5", username="tester5")
        db.add(user)
        await db.commit()
        await db.refresh(user)
        repo = Repo(
            user_id=user.id,
            owner="owner",
            repo="demo-logs",
            full_name="owner/demo-logs",
        )
        db.add(repo)
        await db.commit()
        await db.refresh(repo)

        await sync_service.record_sync_log(db, repo.id, status="success", message="同步完成", commit_sha="abc123")
        await sync_service.record_sync_log(db, repo.id, status="failed", message="网络超时")
        logs = await sync_service.list_sync_logs(db, repo.id)
        assert len(logs) == 2
        assert logs[0].status == "success"
        assert logs[0].commit_sha == "abc123"
        assert logs[-1].status == "failed"


@pytest.mark.asyncio
async def test_chat_session_crud_and_ownership():
    init_database()
    await create_tables()
    async with database.session_factory() as db:
        user = User(github_id="6", username="tester6")
        db.add(user)
        await db.commit()
        await db.refresh(user)
        other = User(github_id="7", username="tester7")
        db.add(other)
        await db.commit()
        await db.refresh(other)

        session = await memory.create_session(db, user.id, "测试会话")
        assert session.title == "测试会话"
        await memory.save_message(db, session.id, "user", "你好")
        messages = await memory.recent_messages(db, session.id)
        assert len(messages) == 1

        await memory.rename_session(db, session, "新标题")
        assert session.title == "新标题"
        assert await memory.get_owned_session(db, other.id, session.id) is None
        assert await memory.get_owned_session(db, user.id, session.id) is not None

        await memory.delete_session(db, session)
        assert await memory.list_sessions(db, user.id) == []


@pytest.mark.asyncio
async def test_model_catalog_contains_ollama(monkeypatch):
    async def fake_ollama_models() -> list[str]:
        return ["deepseek-r1:7b", "qwen3.5:2b"]

    monkeypatch.setattr(model_config, "_list_ollama_models", fake_ollama_models)
    catalog = await model_config.model_catalog()
    providers = [item["provider"] for item in catalog]
    assert providers == ["deepseek", "dashscope", "ollama"]
    assert "deepseek-r1:7b" in catalog[2]["models"]
    assert catalog[2]["requires_api_key"] is False


@pytest.mark.asyncio
async def test_resolve_active_ollama_without_api_key():
    init_database()
    await create_tables()
    async with database.session_factory() as db:
        user = User(github_id="8", username="tester8")
        db.add(user)
        await db.commit()
        await db.refresh(user)
        config = ModelConfig(
            user_id=user.id,
            provider="ollama",
            model_name="deepseek-r1:7b",
            base_url="http://127.0.0.1:11434",
            is_active=True,
        )
        db.add(config)
        await db.commit()
        resolved = await model_config.resolve_active(db, user.id)
        assert resolved is not None
        assert resolved["provider"] == "ollama"
        assert resolved["model"] == "deepseek-r1:7b"
        assert resolved["api_key"] == ""


@pytest.mark.asyncio
async def test_resolve_active_marks_invalid_key(monkeypatch):
    init_database()
    await create_tables()

    def boom(_value: str) -> str:
        raise ValueError("cannot decrypt")

    monkeypatch.setattr(model_config, "decrypt_secret", boom)
    async with database.session_factory() as db:
        user = User(github_id="12", username="badkey-tester")
        db.add(user)
        await db.commit()
        await db.refresh(user)
        config = ModelConfig(
            user_id=user.id,
            provider="deepseek",
            model_name="deepseek-v4-flash",
            base_url="https://api.deepseek.com",
            api_key_enc="garbage-token",
            is_active=True,
        )
        db.add(config)
        await db.commit()
        resolved = await model_config.resolve_active(db, user.id)
        assert resolved is not None
        assert resolved["provider"] == "deepseek"
        assert resolved["config_error"] == "invalid_api_key"


@pytest.mark.asyncio
async def test_agent_config_error_guides_reentry(monkeypatch):
    init_database()
    await create_tables()

    def boom(_value: str) -> str:
        raise ValueError("cannot decrypt")

    monkeypatch.setattr(model_config, "decrypt_secret", boom)
    async with database.session_factory() as db:
        user = User(github_id="13", username="config-error-tester")
        db.add(user)
        await db.commit()
        await db.refresh(user)
        config = ModelConfig(
            user_id=user.id,
            provider="deepseek",
            model_name="deepseek-v4-flash",
            base_url="https://api.deepseek.com",
            api_key_enc="garbage-token",
            is_active=True,
        )
        db.add(config)
        await db.commit()
        session_id, answer, sources, tool = await agent.ask(
            db,
            user.id,
            "这个项目大致有什么？",
        )
        assert session_id is not None
        assert tool == "config_error"
        assert sources == []
        assert "重新填写 API Key" in answer


@pytest.mark.asyncio
async def test_agent_falls_back_to_ollama_when_deepseek_fails(monkeypatch):
    init_database()
    await create_tables()

    async def fake_llm(config, _system, _user):
        if config.get("provider") == "deepseek":
            return None
        return "Ollama 本地回答：这是保底模型生成的答案。"

    monkeypatch.setattr(agent, "_call_llm", fake_llm)
    async with database.session_factory() as db:
        user = User(github_id="14", username="fallback-tester")
        db.add(user)
        await db.commit()
        await db.refresh(user)
        db.add_all(
            [
                ModelConfig(
                    user_id=user.id,
                    provider="deepseek",
                    model_name="deepseek-v4-flash",
                    base_url="https://api.deepseek.com",
                    api_key_enc=encrypt_secret("fake-key"),
                    is_active=True,
                ),
                ModelConfig(
                    user_id=user.id,
                    provider="ollama",
                    model_name="deepseek-r1:7b",
                    base_url="http://127.0.0.1:11434",
                    is_active=False,
                ),
            ]
        )
        await db.commit()
        session_id, answer, _sources, _tool = await agent.ask(
            db,
            user.id,
            "这个项目大致有什么？",
        )
        assert session_id is not None
        assert "Ollama 本地回答" in answer


@pytest.mark.asyncio
async def test_agent_direct_answer_for_model_question():
    init_database()
    await create_tables()
    async with database.session_factory() as db:
        user = User(github_id="9", username="tester9")
        db.add(user)
        await db.commit()
        await db.refresh(user)
        config = ModelConfig(
            user_id=user.id,
            provider="deepseek",
            model_name="deepseek-v4-flash",
            base_url="https://api.deepseek.com",
            api_key_enc=encrypt_secret("fake-key"),
            is_active=True,
        )
        db.add(config)
        await db.commit()
        session_id, answer, sources, tool = await agent.ask(
            db,
            user.id,
            "你好，请问你是什么模型？",
        )
        assert "DeepSeek" in answer
        assert "deepseek-v4-flash" in answer
        assert sources == []
        assert session_id is not None
        assert tool == "direct"


@pytest.mark.asyncio
async def test_agent_app_guide_does_not_retrieve():
    init_database()
    await create_tables()
    async with database.session_factory() as db:
        user = User(github_id="10", username="tester10")
        db.add(user)
        await db.commit()
        await db.refresh(user)
        session_id, answer, sources, tool = await agent.ask(
            db,
            user.id,
            "直接把代码发给你会帮忙入库吗？",
        )
        assert "不会自动入库" in answer
        assert sources == []
        assert tool == "app_guide"
        assert session_id is not None


@pytest.mark.asyncio
async def test_agent_repo_meta_earliest_repo():
    init_database()
    await create_tables()
    async with database.session_factory() as db:
        user = User(github_id="11", username="tester11")
        db.add(user)
        await db.commit()
        await db.refresh(user)
        db.add_all(
            [
                Repo(
                    user_id=user.id,
                    owner="owner",
                    repo="older",
                    full_name="owner/older",
                    github_created_at="2023-01-01T00:00:00Z",
                ),
                Repo(
                    user_id=user.id,
                    owner="owner",
                    repo="newer",
                    full_name="owner/newer",
                    github_created_at="2024-06-01T00:00:00Z",
                ),
            ]
        )
        await db.commit()
        session_id, answer, sources, tool = await agent.ask(
            db,
            user.id,
            "最早代码库是哪个？",
        )
        assert "owner/older" in answer
        assert "2023" in answer
        assert sources == []
        assert tool == "repo_meta"
        assert session_id is not None
