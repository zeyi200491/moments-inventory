from __future__ import annotations

import base64
import hashlib
import hmac
import os


_HASH_NAME = "pbkdf2_sha256"
_ITERATIONS = 200_000


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
