"""写操作幂等中间件。

按配置路径前缀匹配写接口（POST/PUT/DELETE/PATCH），取 Idempotency-Key 头做幂等：
- 无头 → 放行（不强制）。
- 同 key + 同 request_hash → 重放首次响应（status + body）。
- 同 key + 不同 request_hash → 409（疑似客户端误用）。
- 同 key 首次 → 转发并缓存响应。

Redis 短锁（60s）贯穿 lookup→reserve→forward→save，串行同 key 并发请求；
DB idempotency_records 持久化（24h），Redis 重启不丢幂等性。
multipart（文件上传）跳过——版本创建有 UniqueConstraint 自然去重。
"""

import hashlib
import json
import logging
import secrets

from redis.asyncio import Redis

from core.config import settings
from core.database import async_session
from core.redis_client import get_redis
from repositories import idempotency_repo

logger = logging.getLogger(__name__)

WRITE_METHODS = {"POST", "PUT", "DELETE", "PATCH"}
PROCESSING_LOCK_TTL = 60  # 同 key 串行处理窗口（秒）

_RELEASE_SCRIPT = """
if redis.call('get', KEYS[1]) == ARGV[1] then
    return redis.call('del', KEYS[1])
else
    return 0
end
"""

_CONFLICT_BODY = {
    "code": 409,
    "message": "幂等键冲突：请求体与首次请求不一致",
    "data": None,
}
_PROCESSING_BODY = {
    "code": 409,
    "message": "首次请求尚未完成，请稍后重试",
    "data": None,
}
_BUSY_BODY = {"code": 409, "message": "重复请求正在处理中，请稍后重试", "data": None}


class IdempotencyMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        method = scope.get("method", "")
        path = scope.get("path", "")

        if (
            method not in WRITE_METHODS
            or not _matches_prefix(path)
            or _is_multipart(scope)
        ):
            await self.app(scope, receive, send)
            return

        headers = {
            k.decode("latin-1"): v.decode("latin-1", errors="replace")
            for k, v in scope.get("headers", [])
        }
        key = headers.get("idempotency-key", "").strip()[:128]
        if not key:
            await self.app(scope, receive, send)
            return

        body_bytes = await _read_body(receive)
        request_hash = hashlib.sha256(
            (method + "\n" + path).encode() + b"\n" + body_bytes
        ).hexdigest()

        client: Redis = get_redis()
        token = secrets.token_hex(16)
        lock_key = f"aihelms:idem:proc:{key}"
        acquired = await client.set(lock_key, token, nx=True, ex=PROCESSING_LOCK_TTL)
        if not acquired:
            await _send_json(send, 409, _BUSY_BODY)
            return

        try:
            async with async_session() as session:
                record = await idempotency_repo.find_by_key(session, key)

            if record is not None:
                if record.request_hash != request_hash:
                    await _send_json(send, 409, _CONFLICT_BODY)
                    return
                if record.response_code is None:
                    await _send_json(send, 409, _PROCESSING_BODY)
                    return
                await _send_json(send, record.response_code, record.response_body or {})
                return

            # 未命中 → 预约（ON CONFLICT 兜底极端并发）→ 转发 → 缓存
            async with async_session() as session:
                record, created = await idempotency_repo.upsert_record(
                    session,
                    key=key,
                    entity_type="write",
                    request_hash=request_hash,
                    ttl_hours=settings.idempotency_ttl_hours,
                )
            if not created:
                # 并发抢注：按既有记录判定
                if record.request_hash != request_hash:
                    await _send_json(send, 409, _CONFLICT_BODY)
                    return
                if record.response_code is not None:
                    await _send_json(
                        send, record.response_code, record.response_body or {}
                    )
                    return
                await _send_json(send, 409, _PROCESSING_BODY)
                return

            status_code, payload = await _forward(
                self.app, scope, receive, send, body_bytes
            )
            await _save_response(record.id, status_code, payload)
        finally:
            try:
                await client.eval(_RELEASE_SCRIPT, 1, lock_key, token)
            except Exception:  # noqa: BLE001
                logger.warning(
                    "release idempotency lock failed: %s", lock_key, exc_info=True
                )


async def _save_response(
    record_id: int, status_code: int, payload: dict | None
) -> None:
    try:
        async with async_session() as session:
            await idempotency_repo.save_response(
                session, record_id, status_code, payload
            )
    except Exception:  # noqa: BLE001
        logger.warning("save idempotency response failed: %s", record_id, exc_info=True)


async def _forward(
    app, scope, receive, send, body_bytes: bytes
) -> tuple[int, dict | None]:
    """转发请求到下游，捕获 status + JSON body。"""
    sent = False

    async def wrapped_receive():
        nonlocal sent
        if not sent:
            sent = True
            return {"type": "http.request", "body": body_bytes, "more_body": False}
        return await receive()

    status_code = 0
    body_chunks: list[bytes] = []

    async def wrapped_send(message):
        nonlocal status_code
        if message["type"] == "http.response.start":
            status_code = message.get("status", 0)
        elif message["type"] == "http.response.body":
            body_chunks.append(message.get("body", b"") or b"")
        await send(message)

    await app(scope, wrapped_receive, wrapped_send)
    raw = b"".join(body_chunks)
    payload: dict | None = None
    if raw:
        try:
            payload = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            payload = None
    return status_code, payload


async def _read_body(receive) -> bytes:
    chunks: list[bytes] = []
    more_body = True
    while more_body:
        msg = await receive()
        if msg["type"] == "http.request":
            chunks.append(msg.get("body", b"") or b"")
            more_body = msg.get("more_body", False)
        elif msg["type"] == "http.disconnect":
            more_body = False
    return b"".join(chunks)


async def _send_json(send, status: int, payload: dict) -> None:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    await send(
        {
            "type": "http.response.start",
            "status": status,
            "headers": [
                [b"content-type", b"application/json"],
                [b"content-length", str(len(body)).encode()],
            ],
        }
    )
    await send({"type": "http.response.body", "body": body})


def _matches_prefix(path: str) -> bool:
    prefixes = [
        p.strip() for p in settings.idempotency_path_prefixes.split(",") if p.strip()
    ]
    return any(path.startswith(p) for p in prefixes)


def _is_multipart(scope) -> bool:
    for name, value in scope.get("headers", []):
        if name == b"content-type":
            decoded = value.decode("latin-1", errors="replace")
            return decoded.startswith("multipart/form-data")
    return False
