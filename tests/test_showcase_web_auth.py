from __future__ import annotations

from moments_inventory.showcase_web.auth import hash_password, verify_password


def test_hash_password_does_not_store_plaintext_and_verifies() -> None:
    hashed = hash_password("admin-pass")

    assert hashed != "admin-pass"
    assert verify_password("admin-pass", hashed) is True
    assert verify_password("wrong", hashed) is False
