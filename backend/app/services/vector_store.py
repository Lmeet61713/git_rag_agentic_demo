import math
from typing import Protocol

from sqlalchemy import delete, select

from backend.app import database
from backend.app.models import VectorRecord


class VectorStore(Protocol):
    async def upsert(self, records: list[dict]) -> None: ...

    async def delete(self, project_id: str, path: str | None = None) -> None: ...

    async def query(self, vector: list[float], top_k: int = 8, filters: dict | None = None) -> list[dict]: ...

    async def keyword_candidates(self, filters: dict | None = None) -> list[dict]: ...

    async def count(self) -> int: ...


def _metadata_scalar(value):
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


class SqliteVectorStore:
    async def upsert(self, records: list[dict]) -> None:
        if not records:
            return
        if database.session_factory is None:
            database.init_database()
        async with database.session_factory() as db:
            for record in records:
                await db.merge(
                    VectorRecord(
                        id=record["id"],
                        project_id=record["project_id"],
                        path=record["path"],
                        file_type=record["file_type"],
                        language=record.get("language"),
                        text=record["text"],
                        metadata_json=record.get("metadata") or {},
                        vector=record["vector"],
                    )
                )
            await db.commit()

    async def delete(self, project_id: str, path: str | None = None) -> None:
        if database.session_factory is None:
            database.init_database()
        async with database.session_factory() as db:
            stmt = delete(VectorRecord).where(VectorRecord.project_id == project_id)
            if path:
                stmt = stmt.where(VectorRecord.path == path)
            await db.execute(stmt)
            await db.commit()

    async def query(self, vector: list[float], top_k: int = 8, filters: dict | None = None) -> list[dict]:
        filters = filters or {}
        if database.session_factory is None:
            database.init_database()
        async with database.session_factory() as db:
            stmt = select(VectorRecord)
            if filters.get("project_id"):
                stmt = stmt.where(VectorRecord.project_id == filters["project_id"])
            if filters.get("file_type"):
                stmt = stmt.where(VectorRecord.file_type == filters["file_type"])
            if filters.get("language"):
                stmt = stmt.where(VectorRecord.language == filters["language"])
            rows = list((await db.execute(stmt)).scalars())
        scored = [(row, _cosine(vector, row.vector)) for row in rows]
        scored.sort(key=lambda item: item[1], reverse=True)
        return [
            {
                "id": row.id,
                "project_id": row.project_id,
                "path": row.path,
                "file_type": row.file_type,
                "language": row.language,
                "text": row.text,
                "metadata": row.metadata_json,
                "score": float(score),
            }
            for row, score in scored[:top_k]
        ]

    async def keyword_candidates(self, filters: dict | None = None) -> list[dict]:
        filters = filters or {}
        if database.session_factory is None:
            database.init_database()
        async with database.session_factory() as db:
            stmt = select(VectorRecord)
            if filters.get("project_id"):
                stmt = stmt.where(VectorRecord.project_id == filters["project_id"])
            if filters.get("file_type"):
                stmt = stmt.where(VectorRecord.file_type == filters["file_type"])
            if filters.get("language"):
                stmt = stmt.where(VectorRecord.language == filters["language"])
            rows = list((await db.execute(stmt)).scalars())
        return [
            {
                "id": row.id,
                "project_id": row.project_id,
                "path": row.path,
                "file_type": row.file_type,
                "language": row.language,
                "text": row.text,
                "metadata": row.metadata_json,
                "score": 0.0,
            }
            for row in rows
        ]

    async def count(self) -> int:
        if database.session_factory is None:
            database.init_database()
        async with database.session_factory() as db:
            return len((await db.execute(select(VectorRecord.id))).scalars().all())


def _cosine(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(x * x for x in b))
    if not norm_a or not norm_b:
        return 0.0
    return dot / (norm_a * norm_b)


def get_vector_store() -> VectorStore:
    try:
        import chromadb  # noqa: F401

        return ChromaVectorStore()
    except Exception:
        return SqliteVectorStore()


class ChromaVectorStore:
    def __init__(self):
        import chromadb

        from backend.app.config import get_settings

        settings = get_settings()
        settings.chroma_dir.mkdir(parents=True, exist_ok=True)
        self.client = chromadb.PersistentClient(path=str(settings.chroma_dir))
        self.collection = self.client.get_or_create_collection(
            name="myagentic",
            metadata={"hnsw:space": "cosine"},
        )

    async def upsert(self, records: list[dict]) -> None:
        if not records:
            return
        self.collection.upsert(
            ids=[record["id"] for record in records],
            embeddings=[record["vector"] for record in records],
            documents=[record["text"] for record in records],
            metadatas=[
                {
                    "project_id": record["project_id"],
                    "path": record["path"],
                    "file_type": record["file_type"],
                    "language": _metadata_scalar(record.get("language")),
                    "chunk_index": int(record.get("chunk_index", 0)),
                    **{key: _metadata_scalar(value) for key, value in (record.get("metadata") or {}).items()},
                }
                for record in records
            ],
        )

    async def delete(self, project_id: str, path: str | None = None) -> None:
        conditions = [{"project_id": project_id}]
        if path:
            conditions.append({"path": path})
        where = conditions[0] if len(conditions) == 1 else {"$and": conditions}
        self.collection.delete(where=where)

    async def query(self, vector: list[float], top_k: int = 8, filters: dict | None = None) -> list[dict]:
        filters = filters or {}
        where = None
        conditions = []
        if filters.get("project_id"):
            conditions.append({"project_id": filters["project_id"]})
        if filters.get("file_type"):
            conditions.append({"file_type": filters["file_type"]})
        if filters.get("language"):
            conditions.append({"language": filters["language"]})
        if conditions:
            where = conditions[0] if len(conditions) == 1 else {"$and": conditions}
        result = self.collection.query(
            query_embeddings=[vector],
            n_results=max(top_k, 1),
            where=where,
        )
        items = []
        for index, doc in enumerate(result.get("documents") or [[]]):
            metadata_list = (result.get("metadatas") or [[]])[index]
            distances = (result.get("distances") or [[]])[index]
            for i, text in enumerate(doc):
                metadata = metadata_list[i] if i < len(metadata_list) else {}
                distance = distances[i] if i < len(distances) else 0.0
                items.append(
                    {
                        "id": (result.get("ids") or [[]])[index][i],
                        "project_id": metadata.get("project_id", ""),
                        "path": metadata.get("path", ""),
                        "file_type": metadata.get("file_type", ""),
                        "language": metadata.get("language"),
                        "text": text,
                        "metadata": metadata,
                        "score": float(1.0 - distance),
                    }
                )
        return items

    async def keyword_candidates(self, filters: dict | None = None) -> list[dict]:
        filters = filters or {}
        where = None
        conditions = []
        if filters.get("project_id"):
            conditions.append({"project_id": filters["project_id"]})
        if filters.get("file_type"):
            conditions.append({"file_type": filters["file_type"]})
        if filters.get("language"):
            conditions.append({"language": filters["language"]})
        if conditions:
            where = conditions[0] if len(conditions) == 1 else {"$and": conditions}
        result = self.collection.get(where=where, include=["documents", "metadatas"])
        items = []
        for index, doc in enumerate(result.get("documents") or []):
            metadata = (result.get("metadatas") or [])[index] or {}
            items.append(
                {
                    "id": (result.get("ids") or [])[index],
                    "project_id": metadata.get("project_id", ""),
                    "path": metadata.get("path", ""),
                    "file_type": metadata.get("file_type", ""),
                    "language": metadata.get("language"),
                    "text": doc,
                    "metadata": metadata,
                    "score": 0.0,
                }
            )
        return items

    async def count(self) -> int:
        return self.collection.count()
