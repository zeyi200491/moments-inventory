from __future__ import annotations

from pathlib import Path

from moments_inventory.exporter import _write_workbook
from moments_inventory.showcase import SHOWCASE_HEADERS
from moments_inventory.showcase_web.importer import import_showcase_workbook
from moments_inventory.showcase_web.repository import SQLiteShowcaseRepository


def test_import_showcase_workbook_inserts_visible_product(tmp_path: Path) -> None:
    workbook = tmp_path / "客户展示库存.xlsx"
    _write_workbook(
        workbook,
        [
            SHOWCASE_HEADERS,
            [
                "p1",
                "佳能ixus80",
                "佳能",
                500,
                558,
                "是",
                "2026-08-10T10:00:00+08:00",
                "晨曦",
                "原文",
                "展示文案",
                "output/media/p1/body.jpg",
                "",
                "佳能ixus80",
                "",
            ],
        ],
    )
    repo = SQLiteShowcaseRepository(tmp_path / "showcase.db")
    repo.initialize()

    result = import_showcase_workbook(workbook, repo)

    product = repo.get_product("p1")
    assert result.inserted_count == 1
    assert product is not None
    assert product.display_price == 558
    assert product.visible is True
    assert product.cover_image_path == "output/media/p1/body.jpg"


def test_import_normalizes_known_showcase_brands(tmp_path: Path) -> None:
    workbook = tmp_path / "客户展示库存.xlsx"
    _write_workbook(
        workbook,
        [
            SHOWCASE_HEADERS,
            [
                "p1",
                "Canon ixus80",
                "",
                500,
                558,
                "是",
                "2026-08-10T10:00:00+08:00",
                "晨曦",
                "原文",
                "展示文案",
                "",
                "",
                "Canon ixus80",
                "",
            ],
            [
                "p2",
                "HP m527",
                "hp",
                300,
                388,
                "是",
                "2026-08-10T10:00:00+08:00",
                "晨曦",
                "原文",
                "展示文案",
                "",
                "",
                "HP m527",
                "",
            ],
            [
                "p3",
                "未知小相机",
                "",
                200,
                299,
                "是",
                "2026-08-10T10:00:00+08:00",
                "晨曦",
                "原文",
                "展示文案",
                "",
                "",
                "",
                "",
            ],
            [
                "p4",
                "jz300",
                "",
                260,
                328,
                "是",
                "2026-08-10T10:00:00+08:00",
                "晨曦",
                "这台富士出片色彩好",
                "展示文案",
                "",
                "",
                "",
                "",
            ],
        ],
    )
    repo = SQLiteShowcaseRepository(tmp_path / "showcase.db")
    repo.initialize()

    import_showcase_workbook(workbook, repo)

    assert repo.get_product("p1").brand == "佳能"
    assert repo.get_product("p2").brand == "惠普"
    assert repo.get_product("p3").brand == "通用"
    assert repo.get_product("p4").brand == "富士"


def test_import_preserves_existing_admin_price_and_visibility(tmp_path: Path) -> None:
    workbook = tmp_path / "客户展示库存.xlsx"
    _write_workbook(
        workbook,
        [
            SHOWCASE_HEADERS,
            [
                "p1",
                "佳能ixus80",
                "佳能",
                500,
                558,
                "是",
                "",
                "晨曦",
                "原文新",
                "展示文案新",
                "",
                "",
                "佳能ixus80",
                "",
            ],
        ],
    )
    repo = SQLiteShowcaseRepository(tmp_path / "showcase.db")
    repo.initialize()
    import_showcase_workbook(workbook, repo)
    repo.update_product_price("p1", 688)
    repo.set_product_visibility("p1", False)

    import_showcase_workbook(workbook, repo)

    product = repo.get_product("p1")
    assert product is not None
    assert product.display_price == 688
    assert product.visible is False
    assert product.raw_copy == "原文新"


def test_import_preserves_existing_admin_marketing_fields(tmp_path: Path) -> None:
    workbook = tmp_path / "客户展示库存.xlsx"
    _write_workbook(
        workbook,
        [
            SHOWCASE_HEADERS,
            [
                "p1",
                "佳能ixus80",
                "佳能",
                500,
                558,
                "是",
                "",
                "晨曦",
                "原文新",
                "展示文案新",
                "",
                "",
                "佳能ixus80",
                "",
            ],
        ],
    )
    repo = SQLiteShowcaseRepository(tmp_path / "showcase.db")
    repo.initialize()
    import_showcase_workbook(workbook, repo)
    product = repo.get_product("p1")
    assert product is not None
    product.short_selling_point = "人像冷白皮，新手好上手"
    product.recommend_tags = "新手推荐,冷白皮"
    repo.upsert_product(product)

    import_showcase_workbook(workbook, repo)

    imported = repo.get_product("p1")
    assert imported is not None
    assert imported.short_selling_point == "人像冷白皮，新手好上手"
    assert imported.recommend_tags == "新手推荐,冷白皮"
