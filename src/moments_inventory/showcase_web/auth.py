from __future__ import annotations

import base64
import hashlib
import hmac
import os
import threading
import time
from collections import OrderedDict
from math import ceil


_HASH_NAME = "pbkdf2_sha256"
_ITERATIONS = 200_000


class LoginAttemptLimiter:
    """本地服务使用的有界、进程内登录节流器。"""

    def __init__(
        self,
        *,
        max_attempts: int = 20,
        window_seconds: int = 60,
        max_clients: int = 4096,
        clock=time.monotonic,
    ) -> None:
        if max_attempts < 1 or window_seconds < 1 or max_clients < 1:
            raise ValueError("登录限流参数必须为正数")
        self.max_attempts = max_attempts
        self.window_seconds = window_seconds
        self.max_clients = max_clients
        self._clock = clock
        self._lock = threading.Lock()
        self._attempts: OrderedDict[str, tuple[float, int]] = OrderedDict()

    @staticmethod
    def _key(scope: str, client: str) -> str:
        return hashlib.sha256(f"{scope}\0{client}".encode("utf-8")).hexdigest()

    def check(self, scope: str, client: str) -> tuple[bool, int]:
        key = self._key(scope, client)
        now = self._clock()
        with self._lock:
            expired = [
                old_key for old_key, (started_at, _) in self._attempts.items()
                if now - started_at >= self.window_seconds
            ]
            for old_key in expired:
                self._attempts.pop(old_key, None)
            current = self._attempts.get(key)
            if current is not None:
                started_at, count = current
                if count >= self.max_attempts:
                    return False, max(1, ceil(self.window_seconds - (now - started_at)))
                self._attempts[key] = (started_at, count + 1)
                self._attempts.move_to_end(key)
            else:
                # 客户端表满时拒绝新来源，避免淘汰活跃计数后绕过限流。
                if len(self._attempts) >= self.max_clients:
                    earliest = min(started_at for started_at, _ in self._attempts.values())
                    return False, max(1, ceil(self.window_seconds - (now - earliest)))
                self._attempts[key] = (now, 1)
        return True, 0

    def clear(self, scope: str, client: str) -> None:
        with self._lock:
            self._attempts.pop(self._key(scope, client), None)


def hash_password(password: str) -> str:
    salt = os.urandom(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt,
        _ITERATIONS,
        dklen=32,
    )
    return "$".join(
        [
            _HASH_NAME,
            str(_ITERATIONS),
            _b64(salt),
            _b64(digest),
        ]
    )


def verify_password(password: str, password_hash: str) -> bool:
    try:
        name, iterations_raw, salt_raw, digest_raw = password_hash.split("$", 3)
        if name != _HASH_NAME:
            return False
        iterations = int(iterations_raw)
        salt = _unb64(salt_raw)
        expected = _unb64(digest_raw)
    except (ValueError, TypeError):
        return False

    actual = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt,
        iterations,
        dklen=len(expected),
    )
    return hmac.compare_digest(actual, expected)


def _b64(value: bytes) -> str:
    return base64.b64encode(value).decode("ascii")


def _unb64(value: str) -> bytes:
    return base64.b64decode(value.encode("ascii"), validate=True)
