from __future__ import annotations

from pathlib import Path

from moments_inventory.showcase_web.models import ShowcaseProduct
from moments_inventory.showcase_web.repository import SQLiteShowcaseRepository


def test_initialize_creates_showcase_tables(tmp_path: Path) -> None:
    repo = SQLiteShowcaseRepository(tmp_path / "showcase.db")
    repo.initialize()

    tables = repo.list_table_names()

    assert "showcase_products" in tables
    assert "showcase_product_images" in tables
    assert "showcase_settings" in tables
    assert "showcase_authorized_partners" in tables
    assert "showcase_import_logs" in tables


def test_upsert_product_preserves_and_lists_product(tmp_path: Path) -> None:
    repo = SQLiteShowcaseRepository(tmp_path / "showcase.db")
    repo.initialize()
    product = ShowcaseProduct(
        product_id="p1",
        model="佳能ixus80",
        brand="佳能",
        cost_price=500,
        display_price=558,
        visible=True,
        sold=False,
        published_at="2026-08-10T10:00:00+08:00",
        raw_copy="原文",
        display_copy="展示文案",
        cover_image_path="storage/showcase_images/p1/body.jpg",
        created_at="2026-08-10T10:01:00+08:00",
        updated_at="2026-08-10T10:01:00+08:00",
        last_seen_import_id="import-1",
    )

    repo.upsert_product(product)

    assert repo.get_product("p1") == product
    assert repo.list_products(include_hidden=True)[0] == product
