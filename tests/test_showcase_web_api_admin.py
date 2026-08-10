from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from moments_inventory.showcase_web.app import create_showcase_app
from moments_inventory.showcase_web.auth import hash_password
from moments_inventory.showcase_web.repository import SQLiteShowcaseRepository


def test_admin_login_sets_session_cookie(tmp_path: Path) -> None:
    repo = SQLiteShowcaseRepository(tmp_path / "showcase.db")
    repo.initialize()
    repo.set_setting("admin_password_hash", hash_password("admin-pass"))
    client = TestClient(create_showcase_app(repository=repo))

    response = client.post("/api/admin/login", json={"password": "admin-pass"})

    assert response.status_code == 200
    assert "showcase_admin_session" in response.cookies
