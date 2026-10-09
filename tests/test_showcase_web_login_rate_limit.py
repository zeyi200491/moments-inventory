from __future__ import annotations

from fastapi.testclient import TestClient

from moments_inventory.showcase_web.app import create_showcase_app
from moments_inventory.showcase_web.auth import LoginAttemptLimiter
from moments_inventory.showcase_web.repository import SQLiteShowcaseRepository


def test_login_limiter_bounds_attempts_by_scope_and_client() -> None:
    now = [10.0]
    limiter = LoginAttemptLimiter(max_attempts=2, window_seconds=30, clock=lambda: now[0])

    assert limiter.check("admin", "client-a") == (True, 0)
    assert limiter.check("admin", "client-a") == (True, 0)
    assert limiter.check("admin", "client-a") == (False, 30)
    assert limiter.check("customer", "client-a") == (True, 0)
    assert limiter.check("admin", "client-b") == (True, 0)

    now[0] = 41.0
    assert limiter.check("admin", "client-a") == (True, 0)


def test_local_admin_and_customer_login_return_429_before_password_verification(tmp_path) -> None:
    repository = SQLiteShowcaseRepository(tmp_path / "showcase.db")
    app = create_showcase_app(
        repository=repository,
        storage_dir=tmp_path / "storage",
        sample_images_dir=tmp_path / "samples",
        login_limiter=LoginAttemptLimiter(max_attempts=1),
    )

    with TestClient(app) as client:
        first_admin = client.post("/api/admin/login", json={"password": "wrong"})
        second_admin = client.post("/api/admin/login", json={"password": "wrong"})
        first_customer = client.post("/api/public/access", json={"password": "wrong"})
        second_customer = client.post("/api/public/access", json={"password": "wrong"})

    assert first_admin.status_code == 401
    assert second_admin.status_code == 429
    assert second_admin.headers["retry-after"] == "60"
    assert first_customer.status_code == 401
    assert second_customer.status_code == 429
    assert second_customer.headers["retry-after"] == "60"
