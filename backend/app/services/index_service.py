from collections import Counter
from datetime import UTC, datetime

from sqlalchemy import delete, select

from backend.app import database
from backend.app.config import get_settings
from backend.app.models import IndexedFile, IndexJob, Repo
from backend.app.services import parser_service, sync_service, vector_store
from backend.app.services.embedding import get_embedding


def plan_incremental(
    chunks: list[parser_service.DocumentChunk],
    manifest: list[dict],
    previous_hashes: dict[str, str],
) -> tuple[list[parser_service.DocumentChunk], set[str]]:
    new_hashes = {item["path"]: item.get("file_hash") or "" for item in manifest}
    changed_paths = {
        path for path, file_hash in new_hashes.items() if previous_hashes.get(path) != file_hash
    }
    removed_paths = set(previous_hashes) - set(new_hashes)
    embed_paths = {chunk.path for chunk in chunks if chunk.path in changed_paths}
    embed_chunks = [chunk for chunk in chunks if chunk.path in embed_paths]
    return embed_chunks, changed_paths | removed_paths


def build_index_summary(
    manifest: list[dict],
    chunks: list[parser_service.DocumentChunk],
    commit_sha: str | None = None,
) -> str:
    files = [item for item in manifest if not item.get("skipped")]
    skipped = [item for item in manifest if item.get("skipped")]
    counts = Counter(item["file_type"] for item in files)
    languages = Counter(item.get("language") for item in files if item.get("language"))
    top_dirs = Counter(item["path"].split("/", 1)[0] for item in files)
    lines = [
        f"索引完成：{len(files)} 个文件，{len(chunks)} 个向量分块，跳过 {len(skipped)} 个文件。",
        (
            f"类型统计：代码 {counts.get('code', 0)} 个，"
            f"文档 {counts.get('doc', 0)} 个，图片 {counts.get('image', 0)} 个。"
        ),
    ]
    if languages:
        top_languages = "、".join(f"{name} {count}" for name, count in languages.most_common(5))
        lines.append(f"主要语言：{top_languages}。")
    if top_dirs:
        top_directories = "、".join(f"{name} {count}" for name, count in top_dirs.most_common(5))
        lines.append(f"主要目录：{top_directories}。")
    readme = next(
        (chunk for chunk in chunks if chunk.path.rsplit("/", 1)[-1].lower().startswith("readme")),
        None,
    )
    if readme:
        excerpt = readme.text.strip().replace("\n", " ")[:240]
        lines.append(f"README 摘录：{excerpt}")
    if commit_sha:
        lines.append(f"索引 commit：{commit_sha}。")
    return "\n".join(lines)


async def create_index_job(repo_id: int) -> IndexJob:
    if database.session_factory is None:
        database.init_database()
    async with database.session_factory() as db:
        job = IndexJob(repo_id=repo_id, status="pending")
        db.add(job)
        await db.commit()
        await db.refresh(job)
        return job


async def run_index_job(job_id: int) -> None:
    if database.session_factory is None:
        database.init_database()
    async with database.session_factory() as db:
        job = await db.get(IndexJob, job_id)
        if job is None:
            return
        repo = await db.get(Repo, job.repo_id)
        if repo is None:
            return
        job.status = "running"
        job.stage = "cloning"
        job.progress = 5
        await db.commit()

    try:
        try:
            commit_sha = await sync_service.clone_repo(repo.owner, repo.repo)
        except Exception:
            mirror = sync_service.repo_mirror_path(repo.owner, repo.repo)
            if not (mirror / ".git").exists():
                raise
            commit_sha = await sync_service.current_commit(mirror)
        if database.session_factory is None:
            database.init_database()
        async with database.session_factory() as db:
            job = await db.get(IndexJob, job_id)
            repo = await db.get(Repo, job.repo_id)
            repo.last_commit_sha = commit_sha
            repo.index_status = "indexing"
            job.stage = "scanning"
            job.progress = 20
            await sync_service.record_sync_log(
                db,
                repo.id,
                action="sync",
                status="success",
                message=f"仓库同步完成，commit {commit_sha}",
                commit_sha=commit_sha,
            )

        chunks, manifest = await parser_service.build_document_chunks(repo.owner, repo.repo)
        project_id = f"{repo.owner}/{repo.repo}"

        if database.session_factory is None:
            database.init_database()
        async with database.session_factory() as db:
            job = await db.get(IndexJob, job_id)
            repo = await db.get(Repo, job.repo_id)
            job.stage = "parsing"
            job.progress = 45
            result = await db.execute(select(IndexedFile).where(IndexedFile.repo_id == repo.id))
            previous_hashes = {item.path: item.file_hash or "" for item in result.scalars()}
            await db.commit()

        embed_chunks, touched_paths = plan_incremental(chunks, manifest, previous_hashes)
        embedding = get_embedding()

        if database.session_factory is None:
            database.init_database()
        async with database.session_factory() as db:
            job = await db.get(IndexJob, job_id)
            job.stage = "embedding"
            job.progress = 70
            await db.commit()

        store = vector_store.get_vector_store()
        settings = get_settings()
        if previous_hashes:
            for path in sorted(touched_paths):
                await store.delete(project_id, path)
        else:
            await store.delete(project_id)
        batch_size = max(1, settings.embedding_batch_size)
        for start in range(0, len(embed_chunks), batch_size):
            batch = embed_chunks[start : start + batch_size]
            vectors = embedding.embed([chunk.text for chunk in batch])
            records = []
            for chunk, vector in zip(batch, vectors):
                records.append(
                    {
                        "id": f"{project_id}:{chunk.path}:{chunk.chunk_index}",
                        "project_id": project_id,
                        "path": chunk.path,
                        "file_type": chunk.file_type,
                        "language": chunk.language,
                        "text": chunk.text,
                        "vector": vector,
                        "chunk_index": chunk.chunk_index,
                        "metadata": {
                            "symbol": chunk.symbol,
                            **chunk.metadata,
                        },
                    }
                )
            await store.upsert(records)
            del vectors, records

        if database.session_factory is None:
            database.init_database()
        async with database.session_factory() as db:
            job = await db.get(IndexJob, job_id)
            repo = await db.get(Repo, job.repo_id)
            job.stage = "writing"
            job.progress = 90
            await db.execute(delete(IndexedFile).where(IndexedFile.repo_id == repo.id))
            for item in manifest:
                if item.get("skipped"):
                    continue
                db.add(
                    IndexedFile(
                        repo_id=repo.id,
                        path=item["path"],
                        file_type=item["file_type"],
                        language=item.get("language"),
                        file_hash=item.get("file_hash"),
                        size=item.get("size", 0),
                    )
                )
            repo.last_commit_sha = commit_sha
            repo.index_status = "indexed"
            repo.last_indexed_at = datetime.now(UTC).replace(tzinfo=None)
            repo.summary = build_index_summary(manifest, chunks, commit_sha=commit_sha)
            job.status = "success"
            job.progress = 100
            job.stage = "writing"
            await db.commit()
    except Exception as exc:
        if database.session_factory is None:
            database.init_database()
        async with database.session_factory() as db:
            job = await db.get(IndexJob, job_id)
            if job is not None:
                job.status = "failed"
                job.error = str(exc)
                repo = await db.get(Repo, job.repo_id)
                if repo is not None:
                    repo.index_status = "failed"
                if repo is not None:
                    await sync_service.record_sync_log(
                        db,
                        repo.id,
                        action="sync" if job.stage == "cloning" else "index",
                        status="failed",
                        message=str(exc)[:2000],
                    )


async def get_job(job_id: int) -> IndexJob | None:
    if database.session_factory is None:
        database.init_database()
    async with database.session_factory() as db:
        return await db.get(IndexJob, job_id)


async def latest_job_for_repo(repo_id: int) -> IndexJob | None:
    if database.session_factory is None:
        database.init_database()
    async with database.session_factory() as db:
        result = await db.execute(
            select(IndexJob).where(IndexJob.repo_id == repo_id).order_by(IndexJob.id.desc()).limit(1)
        )
        return result.scalar_one_or_none()
