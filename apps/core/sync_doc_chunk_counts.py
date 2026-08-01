"""一次性回填：按 docs-mcp 真实分块数校正平台 documents.chunk_count。

背景：docs-mcp 升级分块策略后粒度变细（如 dingtalk-server-api 旧 2154 → 新 2845），
但平台 documents.chunk_count 是入库时一次性写入的快照，不会随后续重分块自愈，
导致文档库详情页「总分块数」与每行分块数长期陈旧。docs-mcp 是分块的唯一执行者，
其 SQLite（documents 表 = 分块行）是分块数的 source of truth；本脚本把真值拉回平台 DB。

取数方式：docs-mcp REST 不暴露 per-page 分块数，故直接查 docs-mcp-worker 容器内的
SQLite（/data/documents.db），按 (library, version, url) 聚合 COUNT(documents.id)。
url 与平台 documents.ingest_url 一一对应（入库时同源写入）。

环境适配：Linux/生产走原生 docker；Windows 开发走 WSL（docker 在 WSL2）。

幂等：重跑只会把 chunk_count 校成当前 docs-mcp 真值；无变化的行不动。
手动执行：./dev/sync-doc-chunk-counts
"""

import asyncio
import json
import logging
import shlex
import subprocess
import sys
import tempfile
from pathlib import Path

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import async_session
from models.db import Document, DocumentLibrary
from repositories import document_library_repo, document_repo

logger = logging.getLogger(__name__)

CONTAINER = "docs-mcp-worker"
DB_PATH_IN_CONTAINER = "/data/documents.db"
REMOTE_SCRIPT = "/app/sync_chunk_query.cjs"

# per-(library,version,url) 分块数查询模板；DB 路径与 library 名运行时注入。
# library 名注入 JSON 字面量，规避 shell 转义与中文编码穿过 WSL/docker 的问题。
_QUERY_SCRIPT = """\
const Database = require("better-sqlite3");
const db = new Database(%(db)s, { readonly: true, fileMustExist: true });
const LIB = %(lib)s;
const rows = db.prepare(
  "SELECT COALESCE(v.name,'') ver, p.url url, COUNT(d.id) n "
  + "FROM documents d JOIN pages p ON d.page_id=p.id "
  + "JOIN versions v ON p.version_id=v.id JOIN libraries l ON v.library_id=l.id "
  + "WHERE lower(l.name)=lower(?) "
  + "GROUP BY v.id, p.id"
).all(LIB);
console.log(JSON.stringify(rows));
db.close();
"""


def _probe_wsl() -> bool:
    """原生 docker 不可用则回落 WSL（Windows 开发：docker 在 WSL2）。"""
    try:
        subprocess.run(
            ["docker", "version", "--format", "{{.Server.Version}}"],
            capture_output=True,
            timeout=10,
            check=True,
        )
        return False
    except (
        FileNotFoundError,
        subprocess.CalledProcessError,
        subprocess.TimeoutExpired,
    ):
        return True


_USE_WSL = _probe_wsl()


def _to_wsl_path(win_path: str) -> str:
    """C:\\Users\\foo\\x.cjs → /mnt/c/Users/foo/x.cjs（drvfs 挂载所有固定盘）。"""
    p = win_path.replace("\\", "/")
    return f"/mnt/{p[0].lower()}{p[2:]}"


def _docker_run(argv: list[str]) -> str:
    """执行 docker 命令，返回 stdout。

    用 bytes 捕获再按 utf-8 解码：WSL 启动会在 stderr 打中文告示，Windows 默认
    GBK text 解码会抛 UnicodeDecodeError 并污染捕获，故显式 errors='replace'。
    """
    if not _USE_WSL:
        res = subprocess.run(argv, capture_output=True, timeout=120, check=True)
        return res.stdout.decode("utf-8", errors="replace")
    cmd = "docker " + " ".join(shlex.quote(a) for a in argv)
    res = subprocess.run(
        ["wsl", "-e", "bash", "-lc", cmd],
        capture_output=True,
        timeout=120,
        check=True,
    )
    # stdout=JSON(utf-8)；stderr 可能混 WSL 告示，丢弃即可
    return res.stdout.decode("utf-8", errors="replace")


def _fetch_per_page_chunks(library_name: str) -> dict[tuple[str, str], int]:
    """查 docs-mcp SQLite，返回 {(version, url): chunk_count}。"""
    script = _QUERY_SCRIPT % {
        "db": json.dumps(DB_PATH_IN_CONTAINER),
        "lib": json.dumps(library_name, ensure_ascii=False),
    }
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".cjs", delete=False, encoding="utf-8"
    ) as tf:
        tf.write(script)
        local_path = tf.name

    try:
        host_path = _to_wsl_path(local_path) if _USE_WSL else local_path
        _docker_run(["cp", host_path, f"{CONTAINER}:{REMOTE_SCRIPT}"])
        out = _docker_run(["exec", CONTAINER, "node", REMOTE_SCRIPT])
    finally:
        Path(local_path).unlink(missing_ok=True)

    # node 恰输出一行 JSON；取末条非空行，防 WSL/docker 告示混入 stdout
    last_line = next(ln for ln in reversed(out.splitlines()) if ln.strip())
    rows = json.loads(last_line)
    return {(r["ver"], r["url"]): int(r["n"]) for r in rows}


async def _sync_library(session: AsyncSession, library: DocumentLibrary) -> None:
    name = library.name
    try:
        truth = _fetch_per_page_chunks(name)
    except (
        subprocess.CalledProcessError,
        subprocess.TimeoutExpired,
        json.JSONDecodeError,
    ) as e:
        logger.error("fetch chunks failed for %s: %s", name, e)
        return

    docs = (
        await session.execute(
            select(
                Document.id,
                Document.version,
                Document.ingest_url,
                Document.chunk_count,
            ).where(func.lower(Document.library) == name.lower())
        )
    ).all()

    matched = changed = unmatched = 0
    for doc_id, version, ingest_url, old_count in docs:
        key = (version or "", ingest_url or "")
        if key not in truth:
            unmatched += 1
            continue
        matched += 1
        new_count = truth[key]
        if new_count != old_count:
            await session.execute(
                update(Document)
                .where(Document.id == doc_id)
                .values(chunk_count=new_count)
            )
            changed += 1

    document_count, total_chunks = await document_repo.count_and_chunks_by_library(
        session, name
    )
    await document_library_repo.update_counts(
        session, library.id, document_count, total_chunks
    )

    logger.info(
        "library %s: truth_pages=%d matched=%d changed=%d unmatched=%d -> docs=%d chunks=%d",
        name,
        len(truth),
        matched,
        changed,
        unmatched,
        document_count,
        total_chunks,
    )


async def run_chunk_sync() -> None:
    """遍历所有文档库校正分块数。单库失败不阻断其它库。"""
    async with async_session() as session:
        libraries = (await session.execute(select(DocumentLibrary))).scalars().all()
        for library in libraries:
            try:
                await _sync_library(session, library)
            except Exception:
                logger.exception("sync chunks failed: %s", library.name)
        await session.commit()


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO, format="%(levelname)s %(name)s: %(message)s"
    )
    logger.info("docker via %s", "WSL" if _USE_WSL else "native")
    asyncio.run(run_chunk_sync())
    sys.exit(0)
