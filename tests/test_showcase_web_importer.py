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
