from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from moments_inventory.showcase_web.app import create_showcase_app
from moments_inventory.showcase_web.models import ShowcaseProduct
from moments_inventory.showcase_web.repository import SQLiteShowcaseRepository


def _product(
    product_id: str,
    *,
    visible: bool,
    display_price: int,
    brand: str = "佳能",
    sold: bool = False,
) -> ShowcaseProduct:
    return ShowcaseProduct(
        product_id=product_id,
        model=f"{brand}测试型号",
        brand=brand,
        cost_price=300,
        display_price=display_price,
        visible=visible,
        sold=sold,
        published_at="2026-08-10T10:00:00+08:00",
        raw_copy="原文",
        display_copy="展示文案",
        cover_image_path="",
        created_at="2026-08-10T10:01:00+08:00",
        updated_at="2026-08-10T10:01:00+08:00",
        last_seen_import_id="import-1",
    )


def test_public_products_api_returns_only_visible_products(tmp_path: Path) -> None:
    repo = SQLiteShowcaseRepository(tmp_path / "showcase.db")
    repo.initialize()
    repo.upsert_product(_product("visible", visible=True, display_price=558))
    repo.upsert_product(_product("hidden", visible=False, display_price=588))
    repo.upsert_product(_product("sold", visible=True, sold=True, display_price=688))
    client = TestClient(create_showcase_app(repository=repo))

    response = client.get("/api/public/products")

    assert response.status_code == 200
    assert [item["productId"] for item in response.json()["products"]] == ["visible"]
    assert response.json()["products"][0]["displayPrice"] == 558


def test_public_product_detail_returns_up_to_nine_images(tmp_path: Path) -> None:
    repo = SQLiteShowcaseRepository(tmp_path / "showcase.db")
    repo.initialize()
    repo.upsert_product(_product("p1", visible=True, display_price=558))
    for index in range(12):
        repo.add_product_image(
            f"img-{index}",
            "p1",
            f"storage/showcase_images/p1/{index}.jpg",
            "detail",
            index,
            index == 0,
        )
    client = TestClient(create_showcase_app(repository=repo))

    response = client.get("/api/public/products/p1")

    assert response.status_code == 200
    assert response.json()["productId"] == "p1"
    assert len(response.json()["images"]) == 9
