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


def test_import_reissued_stable_key_reuses_existing_product_and_admin_identity(tmp_path: Path) -> None:
    workbook = tmp_path / "客户展示库存.xlsx"
    repo = SQLiteShowcaseRepository(tmp_path / "showcase.db")
    first_row = dict.fromkeys(SHOWCASE_HEADERS, "")
    first_row.update({
        "商品ID": "wxid_1|2026-10-01T20:25:55+08:00|8820",
        "型号": "佳能ixus80", "品牌": "佳能", "成本价": 500, "展示价": 558,
        "是否展示": "是", "发布时间": "2026-10-01T20:25:55+08:00",
        "原文文案": "原文", "展示文案": "展示文案", "机身图路径": "media/old.jpg",
        "来源商品键": "media:stable-8820",
    })
    _write_workbook(workbook, [SHOWCASE_HEADERS, [first_row[key] for key in SHOWCASE_HEADERS]])
    import_showcase_workbook(workbook, repo)
    original = repo.get_product(first_row["商品ID"])
    assert original is not None
    with repo._get_connection() as conn:
        conn.execute(
            "update showcase_products set display_price=888,price_override=888,visible=0,visibility_override=0 where product_id=?",
            (original.product_id,),
        )

    reposted_row = dict(first_row)
    reposted_row.update({
        "商品ID": "stable:media:stable-8820",
        "发布时间": "2026-10-08T20:25:55+08:00",
        "展示价": 599,
        "机身图路径": "",
    })
    _write_workbook(workbook, [SHOWCASE_HEADERS, [reposted_row[key] for key in SHOWCASE_HEADERS]])
    result = import_showcase_workbook(workbook, repo)

    product = repo.get_product(original.product_id)
    with repo._get_connection() as conn:
        stored_key = conn.execute(
            "select source_product_key from showcase_products where product_id=?",
            (original.product_id,),
        ).fetchone()[0]
    assert result.inserted_count == 0
    assert result.updated_count == 1
    assert repo.list_product_ids() == {original.product_id}
    assert product is not None
    assert product.public_id == original.public_id
    assert product.display_price == 888
    assert product.visible is False
    assert product.published_at == "2026-10-08T20:25:55+08:00"
    assert product.cover_image_path == "media/old.jpg"
    assert stored_key == "media:stable-8820"


def test_legacy_import_without_stable_key_does_not_clear_existing_key(tmp_path: Path) -> None:
    workbook = tmp_path / "客户展示库存.xlsx"
    repo = SQLiteShowcaseRepository(tmp_path / "showcase.db")
    row = dict.fromkeys(SHOWCASE_HEADERS, "")
    row.update({
        "商品ID": "p1", "型号": "佳能ixus80", "品牌": "佳能", "成本价": 500,
        "展示价": 558, "是否展示": "是", "发布时间": "2026-08-10T10:00:00+08:00",
        "原文文案": "原文", "展示文案": "展示文案", "来源商品键": "media:keep-me",
    })
    _write_workbook(workbook, [SHOWCASE_HEADERS, [row[key] for key in SHOWCASE_HEADERS]])
    import_showcase_workbook(workbook, repo)
    row["来源商品键"] = ""
    _write_workbook(workbook, [SHOWCASE_HEADERS, [row[key] for key in SHOWCASE_HEADERS]])

    import_showcase_workbook(workbook, repo)

    with repo._get_connection() as conn:
        stored_key = conn.execute(
            "select source_product_key from showcase_products where product_id='p1'",
        ).fetchone()[0]
    assert stored_key == "media:keep-me"


def test_import_splits_deduplicates_body_images_and_preserves_manual_uploads(tmp_path: Path) -> None:
    workbook = tmp_path / "客户展示库存.xlsx"
    repo = SQLiteShowcaseRepository(tmp_path / "showcase.db")
    row = dict.fromkeys(SHOWCASE_HEADERS, "")
    row.update({
        "商品ID": "p1", "型号": "佳能ixus80", "品牌": "佳能", "成本价": 500,
        "展示价": 558, "是否展示": "是", "发布时间": "2026-08-10T10:00:00+08:00",
        "原文文案": "原文", "展示文案": "展示文案",
        "机身图路径": "media/a.jpg\r\nmedia/b.jpg\nmedia/a.jpg",
    })
    _write_workbook(workbook, [SHOWCASE_HEADERS, [row[key] for key in SHOWCASE_HEADERS]])

    import_showcase_workbook(workbook, repo)
    repo.add_product_image("manual-image", "p1", "media/manual.jpg", "body", 8, False)
    row["展示价"] = 559
    _write_workbook(workbook, [SHOWCASE_HEADERS, [row[key] for key in SHOWCASE_HEADERS]])
    import_showcase_workbook(workbook, repo)

    images = repo.list_product_images("p1")
    assert [image.image_path for image in images if image.source == "inventory_import"] == [
        "media/a.jpg", "media/b.jpg",
    ]
    assert any(image.image_id == "manual-image" for image in images)
    assert repo.get_product("p1").cover_image_path == "media/a.jpg"
