"""公开只读接口的版本感知响应缓存。"""
from __future__ import annotations

from dataclasses import dataclass
from threading import RLock
import asyncio
import time

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from moments_inventory.showcase_web.api import _has_valid_customer_session


@dataclass(frozen=True)
class _CachedResponse:
    body: bytes
    status_code: int
    headers: dict[str, str]
    expires_at: float


class PublicResponseCacheMiddleware(BaseHTTPMiddleware):
    """缓存公开 GET 的最终 JSON；后台写入后立即清空，外部写入最长陈旧30秒。"""

    _EXCLUDED = {"/api/public/access-status", "/api/public/image-variant"}
    _CACHEABLE_PATHS = {
        "/api/public/filters",
        "/api/public/gallery",
        "/api/public/product-lookup",
        "/api/public/products",
        "/api/public/purchase-steps",
        "/api/public/sections",
        "/api/public/settings",
    }
    _LOCK_SHARDS = 64

    def __init__(self, app, repository, ttl_seconds: int = 30):
        super().__init__(app)
        self.repository = repository
        self.ttl_seconds = ttl_seconds
        self._cache: dict[tuple[str, str], _CachedResponse] = {}
        self._build_locks = [asyncio.Lock() for _ in range(self._LOCK_SHARDS)]
        self._lock = RLock()
        self._generation = 0
        self._state_checked_at = 0.0
        self._password_hash = ""
        self._revision = "0"

    def _state_snapshot(self, now: float) -> tuple[str, str]:
        # 合并高频设置读取；外部进程提交后最多250ms即可感知。
        with self._lock:
            if now - self._state_checked_at >= 0.25:
                self._password_hash = self.repository.get_setting("customer_password_hash") or ""
                self._revision = self.repository.get_setting("catalog_revision") or "0"
                self._state_checked_at = now
            return self._password_hash, self._revision

    async def dispatch(self, request: Request, call_next):
        path = request.url.path
        is_public_read = (
            request.method == "GET"
            and path in self._CACHEABLE_PATHS
            and path not in self._EXCLUDED
        )
        if not is_public_read:
            response = await call_next(request)
            if request.method != "GET" and path.startswith("/api/admin/") and response.status_code < 400:
                with self._lock:
                    self._cache.clear()
                    self._state_checked_at = 0.0
                    self._generation += 1
            return response

        now = time.monotonic()
        password_hash, revision = self._state_snapshot(now)
        # 口令开启时先验证会话，不能让缓存绕过路由的访问控制。
        if path != "/api/public/settings" and password_hash:
            session_id = request.cookies.get("showcase_customer_access")
            if not _has_valid_customer_session(self.repository, session_id):
                return await call_next(request)

        key = (revision, request.url.path + ("?" + request.url.query if request.url.query else ""))
        with self._lock:
            cached = self._cache.get(key)
            if cached is not None and cached.expires_at > now:
                headers = dict(cached.headers)
                headers["x-showcase-cache"] = "HIT"
                return Response(cached.body, status_code=cached.status_code, headers=headers)
            build_lock = self._build_locks[hash(key) % len(self._build_locks)]
            generation = self._generation

        # 相同冷键只允许一个请求构建，避免缓存过期瞬间同时压垮单进程。
        async with build_lock:
            now = time.monotonic()
            with self._lock:
                cached = self._cache.get(key)
                if cached is not None and cached.expires_at > now:
                    headers = dict(cached.headers)
                    headers["x-showcase-cache"] = "HIT"
                    return Response(cached.body, status_code=cached.status_code, headers=headers)
            response = await call_next(request)
            if response.status_code != 200:
                return response
            body = b"".join([chunk async for chunk in response.body_iterator])
            headers = dict(response.headers)
            # 浏览器每次向服务端确认；服务端命中内存缓存，因此后台更新可立即生效。
            headers["cache-control"] = "private, no-cache"
            headers["x-showcase-cache"] = "MISS"
            cached = _CachedResponse(
                body, response.status_code, headers, time.monotonic() + self.ttl_seconds
            )
            with self._lock:
                if len(self._cache) >= 512:
                    self._cache.clear()
                if self._generation == generation:
                    self._cache[key] = cached
            return Response(body, status_code=response.status_code, headers=headers)
