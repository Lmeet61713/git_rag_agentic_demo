from collections import Counter
from pathlib import Path

import pytest

from backend.app import database
from backend.app.database import create_tables, init_database
from backend.app.models import ModelConfig, Repo, User
from backend.app.security import encrypt_secret
from backend.app.services import agent, relevance, retrieval, vector_store
from backend.app.services.embedding import HashEmbedding, get_embedding
from backend.app.services.parser_service import DocumentChunk
from backend.app.services.repo_service import parse_repo_url
from backend.app.services.tech_summary import build_project_summary
from backend.app.services.tool_registry import ToolSelection
from backend.app.services.vector_store import SqliteVectorStore

MODEL_ONNX = (
    Path(__file__).resolve().parents[3]
    / "data"
    / "models"
    / "bge-small-zh-v1.5"
    / "onnx"
    / "model.onnx"
)


@pytest.mark.skipif(not MODEL_ONNX.exists(), reason="ONNX model not downloaded")
def test_onnx_embedding_dimension():
    embedding = get_embedding()
    assert embedding.dim == 512
    vectors = embedding.embed(["hello world", "你好世界"])
    assert len(vectors) == 2
    assert all(len(vector) == 512 for vector in vectors)


def test_project_summary_includes_tech_stack():
    manifest = [
        {"path": "README.md", "file_type": "doc", "language": "markdown", "size": 10, "file_hash": "a", "skipped": ""},
        {"path": "package.json", "file_type": "code", "language": "json", "size": 10, "file_hash": "b", "skipped": ""},
        {"path": "src/main.py", "file_type": "code", "language": "python", "size": 10, "file_hash": "c", "skipped": ""},
    ]
    chunks = [
        DocumentChunk(
            project_id="owner/demo",
            path="README.md",
            file_type="doc",
            text="这是 Vue 项目，使用 Vite 构建。",
            language="markdown",
        ),
        DocumentChunk(
            project_id="owner/demo",
            path="package.json",
            file_type="code",
            text='{"dependencies":{"vue":"3","vite":"5"}}',
            language="json",
        ),
        DocumentChunk(
            project_id="owner/demo",
            path="src/main.py",
            file_type="code",
            text="from fastapi import FastAPI",
            language="python",
        ),
    ]
    summary_chunk, entry = build_project_summary("owner/demo", manifest, chunks)
    assert summary_chunk.file_type == "project_summary"
    assert entry["file_type"] == "project_summary"
    assert "vue" in summary_chunk.text
    assert "python" in summary_chunk.text
    assert "vue" in summary_chunk.metadata["languages"]
    assert "python" in summary_chunk.metadata["languages"]
    assert "python 1" in summary_chunk.metadata["primary_languages"]


def test_intro_query_detection():
    assert agent._is_intro_query("简单介绍一下项目 Homer")
    assert agent._is_intro_query("这个项目是什么")
    assert agent._is_intro_query("这个项目大致做什么的？")
    assert agent._is_intro_query("简单说下 PersonalMind_AI")
    assert not agent._is_intro_query("哪个仓库用了 Vue 框架？")


def test_rerank_prefers_lexical_match():
    results = [
        {
            "id": "a",
            "project_id": "owner/demo",
            "path": "src/unrelated.py",
            "file_type": "code",
            "text": "completely unrelated random content",
            "score": 0.8,
        },
        {
            "id": "b",
            "project_id": "owner/demo",
            "path": "README.md",
            "file_type": "doc",
            "text": "安装说明与使用步骤",
            "score": 0.5,
        },
    ]
    reranked = relevance.rerank_results("README 安装说明", results)
    assert reranked[0]["id"] == "b"
    assert reranked[0]["relevance"] > reranked[1]["relevance"]


def test_filter_by_relevance_drops_low_relevance_outlier():
    results = [
        {
            "id": "good",
            "project_id": "owner/demo",
            "path": "README.md",
            "file_type": "doc",
            "text": "安装说明与使用步骤",
            "score": 0.6,
        },
        {
            "id": "bad",
            "project_id": "owner/demo",
            "path": "random.py",
            "file_type": "code",
            "text": "完全无关的内容",
            "score": 0.1,
        },
    ]
    filtered = relevance.filter_by_relevance("README 安装说明", results)
    assert [item["id"] for item in filtered] == ["good"]


def test_reflect_keeps_explicit_project_scope():
    assert agent._graph_reflect(
        {
            "project_id": "owner/target",
            "project_explicit": True,
            "tool": "image_search",
            "file_type": "image",
            "results": [],
        }
    ) == {"retry": False}
    assert agent._graph_reflect(
        {
            "project_id": "owner/target",
            "project_explicit": True,
            "tool": "search",
            "file_type": "doc",
            "results": [],
        }
    ) == {"file_type": None, "retry": True}
    assert agent._graph_reflect(
        {
            "project_id": "owner/target",
            "project_explicit": False,
            "file_type": "doc",
            "results": [],
        }
    ) == {"file_type": None, "retry": True}


def test_repo_brief_returns_names_and_languages():
    repos = [
        Repo(
            id=1,
            user_id=1,
            owner="owner",
            repo="demo",
            full_name="owner/demo",
            summary="README 摘录：示例项目\n主要语言：python 3",
        ),
        Repo(
            id=2,
            user_id=1,
            owner="owner",
            repo="golang-tool",
            full_name="owner/golang-tool",
            summary="README 摘录：Go 工具项目\n主要语言：go 5",
        ),
    ]
    counts = {
        1: Counter({"python": 3, "vue": 2}),
        2: Counter({"go": 5}),
    }
    answer = agent._repo_brief_answer("仓库里有什么项目", repos, counts)
    assert answer is not None
    assert "owner/demo" in answer
    assert "示例项目" in answer
    assert "Python" in answer
    assert "Go" in answer


@pytest.mark.asyncio
async def test_personalmind_informal_intro_returns_project_intro(monkeypatch):
    init_database()
    await create_tables()
    monkeypatch.setattr(vector_store, "get_vector_store", lambda: SqliteVectorStore())
    monkeypatch.setattr(retrieval, "get_embedding", lambda: HashEmbedding())

    async def fake_select(_config, _message):
        return ToolSelection(tool="search", reason="测试应被介绍意图覆盖")

    monkeypatch.setattr(agent, "_select_tool_with_llm", fake_select)
    async with database.session_factory() as db:
        user = User(github_id="207", username="personal-intro-tester")
        db.add(user)
        await db.commit()
        await db.refresh(user)
        repo = Repo(
            user_id=user.id,
            owner="Lmeet61713",
            repo="PersonalMind_AI",
            full_name="Lmeet61713/PersonalMind_AI",
            index_status="indexed",
            summary="README 摘录：个人 AI 助手项目\n主要语言：python 8",
        )
        db.add(repo)
        await db.commit()
        session_id, answer, sources, tool = await agent.ask(
            db,
            user.id,
            "emmmm，那就简单介绍一下PersonalMind_AI这个项目吧，它大致做什么的？",
        )
        assert session_id is not None
        assert tool == "project_intro"
        assert sources == []
        assert "Lmeet61713/PersonalMind_AI" in answer
        assert "个人 AI 助手项目" in answer


@pytest.mark.asyncio
async def test_general_chat_uses_llm_when_available(monkeypatch):
    init_database()
    await create_tables()
    monkeypatch.setattr(vector_store, "get_vector_store", lambda: SqliteVectorStore())
    monkeypatch.setattr(retrieval, "get_embedding", lambda: HashEmbedding())

    async def fake_llm(_config, _system, _user):
        return "随便聊聊挺好的，我们换个仓库相关的问题吧。"

    async def fake_select(_config, _message):
        return ToolSelection(tool="general_chat", reason="闲聊")

    monkeypatch.setattr(agent, "_call_llm", fake_llm)
    monkeypatch.setattr(agent, "_select_tool_with_llm", fake_select)
    async with database.session_factory() as db:
        user = User(github_id="208", username="general-chat-tester")
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
            "今天天气怎么样？",
        )
        assert session_id is not None
        assert tool == "general_chat"
        assert sources == []
        assert answer == "随便聊聊挺好的，我们换个仓库相关的问题吧。"


@pytest.mark.asyncio
async def test_manual_loop_does_not_broaden_explicit_image_project(monkeypatch):
    init_database()
    await create_tables()
    monkeypatch.setattr(vector_store, "get_vector_store", lambda: SqliteVectorStore())
    monkeypatch.setattr(retrieval, "get_embedding", lambda: HashEmbedding())
    store = SqliteVectorStore()
    await store.upsert(
        [
            {
                "id": "other/repo:assets/logo.png:0",
                "project_id": "other/repo",
                "path": "assets/logo.png",
                "file_type": "image",
                "language": None,
                "text": "图片资源 assets/logo.png",
                "vector": [1.0, 0.0, 0.0],
            }
        ]
    )
    state = await agent._manual_retrieve_loop(
        {
            "message": "找一下 owner/target 的图片或 logo",
            "config": None,
            "fallback_config": None,
            "session": None,
        }
    )
    assert state.get("project_id") == "owner/target"
    assert state.get("results") == []


@pytest.mark.asyncio
async def test_llm_tool_selection_returns_direct(monkeypatch):
    async def fake_llm(_config, _system, _user):
        return '{"tool":"direct","project_id":null,"path":null,"reason":"只问助手能力，不需要检索"}'

    monkeypatch.setattr(agent, "_call_llm", fake_llm)
    selection = await agent._select_tool_with_llm(
        {"provider": "deepseek", "model": "deepseek-chat"},
        "你有什么能力？",
    )
    assert selection is not None
    assert selection.tool == "direct"


@pytest.mark.asyncio
async def test_agent_direct_question_does_not_retrieve(monkeypatch):
    init_database()
    await create_tables()
    monkeypatch.setattr(vector_store, "get_vector_store", lambda: SqliteVectorStore())
    monkeypatch.setattr(retrieval, "get_embedding", lambda: HashEmbedding())

    async def fake_select(_config, _message):
        return ToolSelection(tool="direct", reason="能力咨询")

    monkeypatch.setattr(agent, "_select_tool_with_llm", fake_select)
    async with database.session_factory() as db:
        user = User(github_id="203", username="tool-tester")
        db.add(user)
        await db.commit()
        await db.refresh(user)
        session_id, answer, sources, tool = await agent.ask(db, user.id, "你有什么能力？")
        assert session_id is not None
        assert tool == "direct"
        assert sources == []
        assert answer


@pytest.mark.asyncio
async def test_polite_identity_question_does_not_retrieve(monkeypatch):
    init_database()
    await create_tables()
    monkeypatch.setattr(vector_store, "get_vector_store", lambda: SqliteVectorStore())
    monkeypatch.setattr(retrieval, "get_embedding", lambda: HashEmbedding())
    async with database.session_factory() as db:
        user = User(github_id="204", username="identity-tester")
        db.add(user)
        await db.commit()
        await db.refresh(user)
        session_id, answer, sources, tool = await agent.ask(
            db,
            user.id,
            "请问你是？",
        )
        assert session_id is not None
        assert tool == "direct"
        assert sources == []
        assert "MyAgentic" in answer


@pytest.mark.asyncio
async def test_weather_question_drops_retrieved_sources(monkeypatch):
    init_database()
    await create_tables()
    monkeypatch.setattr(vector_store, "get_vector_store", lambda: SqliteVectorStore())
    monkeypatch.setattr(retrieval, "get_embedding", lambda: HashEmbedding())

    retrieval_calls = []

    async def fake_search(*_args, **_kwargs):
        retrieval_calls.append(1)
        return [
            {
                "project_id": "owner/demo",
                "path": "README.md",
                "file_type": "doc",
                "language": "markdown",
                "text": "项目使用说明",
                "score": 0.9,
            }
        ]

    async def fake_select(_config, _message):
        return ToolSelection(tool="search", reason="用户问题被强制送入检索")

    monkeypatch.setattr(agent, "_select_tool_with_llm", fake_select)
    monkeypatch.setattr(retrieval, "search", fake_search)
    async with database.session_factory() as db:
        user = User(github_id="205", username="chat-tester")
        db.add(user)
        await db.commit()
        await db.refresh(user)
        session_id, answer, sources, tool = await agent.ask(
            db,
            user.id,
            "今天天气怎么样？",
        )
        assert session_id is not None
        assert tool == "general_chat"
        assert sources == []
        assert "不属于仓库问答" in answer
        assert retrieval_calls


@pytest.mark.asyncio
async def test_project_intro_uses_summary_without_retrieval(monkeypatch):
    init_database()
    await create_tables()
    monkeypatch.setattr(vector_store, "get_vector_store", lambda: SqliteVectorStore())
    monkeypatch.setattr(retrieval, "get_embedding", lambda: HashEmbedding())
    async with database.session_factory() as db:
        user = User(github_id="202", username="intro-tester")
        db.add(user)
        await db.commit()
        await db.refresh(user)
        repo = Repo(
            user_id=user.id,
            owner="owner",
            repo="homer",
            full_name="owner/homer",
            summary="Homer 项目：结合双摄像头目标检测与动态物品显著性分析。",
            index_status="indexed",
        )
        db.add(repo)
        await db.commit()
        session_id, answer, sources, tool = await agent.ask(
            db,
            user.id,
            "简单介绍一下项目 Homer",
        )
        assert session_id is not None
        assert tool == "project_intro"
        assert sources == []
        assert "Homer 项目" in answer


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("https://github.com/owner/repo", ("owner", "repo")),
        ("github.com/owner/repo.git", ("owner", "repo")),
        ("owner/repo", ("owner", "repo")),
    ],
)
def test_parse_repo_url_valid(url, expected):
    assert parse_repo_url(url) == expected


def test_parse_repo_url_rejects_non_github():
    with pytest.raises(ValueError):
        parse_repo_url("https://gitlab.com/owner/repo")


@pytest.mark.asyncio
async def test_union_retrieval_finds_keyword_when_vector_misses(monkeypatch):
    init_database()
    await create_tables()
    monkeypatch.setattr(retrieval, "get_embedding", lambda: HashEmbedding())
    monkeypatch.setattr(vector_store, "get_vector_store", lambda: SqliteVectorStore())
    store = SqliteVectorStore()
    unrelated_vector = HashEmbedding().embed(["completely unrelated content"])[0]
    await store.upsert(
        [
            {
                "id": "x:README.md:0",
                "project_id": "x",
                "path": "README.md",
                "file_type": "doc",
                "language": "markdown",
                "text": "安装说明与使用步骤",
                "vector": unrelated_vector,
            }
        ]
    )
    results = await retrieval.search("README 安装说明", project_id="x", top_k=5)
    assert results
    assert results[0]["path"] == "README.md"


@pytest.mark.asyncio
async def test_agent_manual_loop_filters_irrelevant_results(monkeypatch):
    init_database()
    await create_tables()
    monkeypatch.setattr(retrieval, "get_embedding", lambda: HashEmbedding())
    monkeypatch.setattr(vector_store, "get_vector_store", lambda: SqliteVectorStore())
    monkeypatch.setattr(agent, "_build_graph", lambda: None)
    store = SqliteVectorStore()
    embedding = HashEmbedding()
    good_vector, bad_vector = embedding.embed(
        [
            "README 安装说明与使用步骤",
            "random unrelated content",
        ]
    )
    await store.upsert(
        [
            {
                "id": "manual/README.md:0",
                "project_id": "manual",
                "path": "README.md",
                "file_type": "doc",
                "language": "markdown",
                "text": "README 安装说明与使用步骤",
                "vector": good_vector,
            },
            {
                "id": "manual/random.py:0",
                "project_id": "manual",
                "path": "random.py",
                "file_type": "code",
                "language": "python",
                "text": "random unrelated content",
                "vector": bad_vector,
            },
        ]
    )
    async with database.session_factory() as db:
        user = User(github_id="206", username="rerank-tester")
        db.add(user)
        await db.commit()
        await db.refresh(user)
        _session_id, _answer, sources, tool = await agent.ask(
            db,
            user.id,
            "README 安装说明",
        )
        assert tool in {"search", "doc_search"}
        assert sources
        assert all(item["path"] == "README.md" for item in sources)


@pytest.mark.asyncio
async def test_confidence_filter_returns_empty(monkeypatch):
    init_database()
    await create_tables()
    monkeypatch.setattr(retrieval, "get_embedding", lambda: HashEmbedding())
    monkeypatch.setattr(vector_store, "get_vector_store", lambda: SqliteVectorStore())
    store = SqliteVectorStore()
    vector = HashEmbedding().embed(["random unrelated text"])[0]
    await store.upsert(
        [
            {
                "id": "x:unrelated.py:0",
                "project_id": "x",
                "path": "unrelated.py",
                "file_type": "code",
                "language": "python",
                "text": "random unrelated text",
                "vector": vector,
            }
        ]
    )
    results = await retrieval.search("zzqqxxyy", project_id="x", top_k=5)
    assert results == []


@pytest.mark.asyncio
async def test_agent_tech_query_routes_to_repo_tech(monkeypatch):
    init_database()
    await create_tables()
    monkeypatch.setattr(vector_store, "get_vector_store", lambda: SqliteVectorStore())
    monkeypatch.setattr(retrieval, "get_embedding", lambda: HashEmbedding())
    assert agent._is_tech_query("哪个仓库用了 Vue 框架？")
    assert agent._tool_from_route(None, "哪个仓库用了 Vue 框架？") == "repo_tech"
    async with database.session_factory() as db:
        user = User(github_id="200", username="tech-tester")
        db.add(user)
        await db.commit()
        await db.refresh(user)
        session_id, _answer, sources, tool = await agent.ask(
            db,
            user.id,
            "哪个仓库用了 Vue 框架？",
        )
        assert session_id is not None
        assert tool == "repo_tech"
        assert sources == []


@pytest.mark.asyncio
async def test_ask_stream_emits_token_events_in_order(monkeypatch):
    init_database()
    await create_tables()
    monkeypatch.setattr(vector_store, "get_vector_store", lambda: SqliteVectorStore())
    monkeypatch.setattr(retrieval, "get_embedding", lambda: HashEmbedding())
    async with database.session_factory() as db:
        user = User(github_id="201", username="stream-tester")
        db.add(user)
        await db.commit()
        await db.refresh(user)
        events = [event async for event in agent.ask_stream(db, user.id, "哪个仓库用了 Vue 框架？")]
        assert events[0]["type"] == "start"
        assert events[1]["type"] == "tool"
        assert events[1]["tool"] == "repo_tech"
        assert any(event["type"] == "token" for event in events)
        assert events[-1]["type"] == "done"
