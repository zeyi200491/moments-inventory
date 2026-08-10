from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from moments_inventory.showcase_web.app import create_showcase_app
from moments_inventory.showcase_web.auth import hash_password
from moments_inventory.showcase_web.models import ShowcaseProduct
from moments_inventory.showcase_web.repository import SQLiteShowcaseRepository


def _product(
    product_id: str,
    *,
    visible: bool,
    display_price: int,
    brand: str = "佳能",
) -> ShowcaseProduct:
    return ShowcaseProduct(
        product_id=product_id,
        model=f"{brand}测试型号",
        brand=brand,
        cost_price=300,
        display_price=display_price,
        visible=visible,
        sold=False,
        published_at="2026-08-10T10:00:00+08:00",
        raw_copy="原文",
        display_copy="展示文案",
        cover_image_path="",
        created_at="2026-08-10T10:01:00+08:00",
        updated_at="2026-08-10T10:01:00+08:00",
        last_seen_import_id="import-1",
    )


@pytest.fixture
def repo(tmp_path: Path) -> SQLiteShowcaseRepository:
    repository = SQLiteShowcaseRepository(tmp_path / "showcase.db")
    repository.initialize()
    repository.set_setting("admin_password_hash", hash_password("admin-pass"))
    return repository


@pytest.fixture
def authenticated_client(repo: SQLiteShowcaseRepository) -> TestClient:
    client = TestClient(create_showcase_app(repository=repo))
    response = client.post("/api/admin/login", json={"password": "admin-pass"})
    assert response.status_code == 200
    return client


def test_admin_login_sets_session_cookie(tmp_path: Path) -> None:
    repo = SQLiteShowcaseRepository(tmp_path / "showcase.db")
    repo.initialize()
    repo.set_setting("admin_password_hash", hash_password("admin-pass"))
    client = TestClient(create_showcase_app(repository=repo))

    response = client.post("/api/admin/login", json={"password": "admin-pass"})

    assert response.status_code == 200
    assert "showcase_admin_session" in response.cookies


def test_admin_can_update_single_product_price(
    authenticated_client: TestClient,
    repo: SQLiteShowcaseRepository,
) -> None:
    repo.upsert_product(_product("p1", visible=True, display_price=558))

    response = authenticated_client.patch("/api/admin/products/p1", json={"displayPrice": 688})

    assert response.status_code == 200
    product = repo.get_product("p1")
    assert product is not None
    assert product.display_price == 688


def test_admin_can_batch_adjust_prices_by_brand(
    authenticated_client: TestClient,
    repo: SQLiteShowcaseRepository,
) -> None:
    repo.upsert_product(_product("canon", visible=True, display_price=500, brand="佳能"))
    repo.upsert_product(_product("sony", visible=True, display_price=500, brand="索尼"))

    response = authenticated_client.post(
        "/api/admin/products/batch-price",
        json={"mode": "increment", "amount": 30, "brand": "佳能"},
    )

    assert response.status_code == 200
    assert response.json()["updatedCount"] == 1
    canon = repo.get_product("canon")
    sony = repo.get_product("sony")
    assert canon is not None
    assert sony is not None
    assert canon.display_price == 530
    assert sony.display_price == 500


def test_admin_can_create_and_delete_product(
    authenticated_client: TestClient,
    repo: SQLiteShowcaseRepository,
) -> None:
    create_response = authenticated_client.post(
        "/api/admin/products",
        json={
            "productId": "manual-1",
            "model": "理光rr30",
            "brand": "理光",
            "displayPrice": 399,
            "displayCopy": "手动新增",
        },
    )
    assert create_response.status_code == 201
    assert repo.get_product("manual-1") is not None

    delete_response = authenticated_client.delete("/api/admin/products/manual-1")
    assert delete_response.status_code == 200
    assert repo.get_product("manual-1") is None
