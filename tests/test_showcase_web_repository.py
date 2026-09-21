from __future__ import annotations

from pathlib import Path

from moments_inventory.showcase_web.models import (
    ShowcaseGalleryAlbum,
    ShowcaseGalleryImage,
    ShowcaseProduct,
    ShowcasePurchaseStep,
    ShowcaseProductSearch,
    ShowcaseSection,
    ShowcaseSectionItem,
)
from moments_inventory.showcase_web.repository import SQLiteShowcaseRepository


def _product(product_id: str, display_price: int) -> ShowcaseProduct:
    return ShowcaseProduct(
        product_id=product_id,
        model="佳能ixus80",
        brand="佳能",
        cost_price=500,
        display_price=display_price,
        visible=True,
        sold=False,
        published_at="2026-08-10T10:00:00+08:00",
        raw_copy="原文",
        display_copy="展示文案",
        cover_image_path=f"storage/showcase_images/{product_id}/body.jpg",
        created_at="2026-08-10T10:01:00+08:00",
        updated_at="2026-08-10T10:01:00+08:00",
        last_seen_import_id="import-1",
    )


def test_initialize_creates_showcase_tables(tmp_path: Path) -> None:
    repo = SQLiteShowcaseRepository(tmp_path / "showcase.db")
    repo.initialize()

    tables = repo.list_table_names()

    assert "showcase_products" in tables
    assert "showcase_product_images" in tables
    assert "showcase_settings" in tables
    assert "showcase_authorized_partners" in tables
    assert "showcase_import_logs" in tables
    assert "showcase_sections" in tables
    assert "showcase_section_items" in tables
    assert "showcase_gallery_albums" in tables
    assert "showcase_gallery_images" in tables
    assert "showcase_purchase_steps" in tables


def test_initialize_seeds_four_default_gallery_albums(tmp_path: Path) -> None:
    repo = SQLiteShowcaseRepository(tmp_path / "showcase.db")
    repo.initialize()

    albums = repo.list_gallery_albums(include_hidden=True)

    assert [album.title for album in albums] == [
        "相机实拍",
        "礼盒装展示",
        "工作室日常",
        "买家反馈",
    ]
    assert "出片氛围" not in [album.title for album in albums]


def test_initialize_seeds_default_purchase_steps(tmp_path: Path) -> None:
    repo = SQLiteShowcaseRepository(tmp_path / "showcase.db")
    repo.initialize()

    steps = repo.list_purchase_steps(include_hidden=True)

    assert [step.title for step in steps] == [
        "挑选型号",
        "复制咨询文案",
        "微信咨询客服",
        "核对验机视频",
        "确认售后规则",
        "付款锁单",
        "安排发货",
    ]
    assert steps[0].description == "按品牌、预算、关键词筛选喜欢的 CCD。"


def test_repository_can_manage_purchase_steps(tmp_path: Path) -> None:
    repo = SQLiteShowcaseRepository(tmp_path / "showcase.db")
    repo.initialize()
    step = ShowcasePurchaseStep(
        step_id="custom-step",
        title="确认预算",
        description="先确认预算范围，筛选更省时间。",
        sort_order=20,
        is_visible=True,
        created_at="2026-08-22T10:00:00+08:00",
        updated_at="2026-08-22T10:00:00+08:00",
    )

    repo.upsert_purchase_step(step)

    assert repo.get_purchase_step("custom-step") == step
    assert [item.step_id for item in repo.list_purchase_steps()][-1] == "custom-step"
    step.is_visible = False
    repo.upsert_purchase_step(step)
    assert "custom-step" not in [item.step_id for item in repo.list_purchase_steps()]
    assert repo.delete_purchase_step("custom-step") is True
    assert repo.get_purchase_step("custom-step") is None


def test_repository_can_manage_gallery_albums_and_images(tmp_path: Path) -> None:
    repo = SQLiteShowcaseRepository(tmp_path / "showcase.db")
    repo.initialize()
    repo.upsert_gallery_album(
        ShowcaseGalleryAlbum(
            album_id="camera-real",
            title="相机实拍",
            description="真实库存外观",
            sort_order=1,
            is_visible=True,
            created_at="2026-08-22T10:00:00+08:00",
            updated_at="2026-08-22T10:00:00+08:00",
        )
    )
    repo.add_gallery_image(
        ShowcaseGalleryImage(
            image_id="img-2",
            album_id="camera-real",
            image_path="storage/showcase_images/gallery/camera-real/img-2.jpg",
            caption="第二张",
            sort_order=2,
            is_visible=True,
            created_at="2026-08-22T10:00:00+08:00",
            updated_at="2026-08-22T10:00:00+08:00",
        )
    )
    repo.add_gallery_image(
        ShowcaseGalleryImage(
            image_id="img-1",
            album_id="camera-real",
            image_path="storage/showcase_images/gallery/camera-real/img-1.jpg",
            caption="第一张",
            sort_order=1,
            is_visible=True,
            created_at="2026-08-22T10:00:00+08:00",
            updated_at="2026-08-22T10:00:00+08:00",
        )
    )

    images = repo.list_gallery_images("camera-real")
    repo.reorder_gallery_images("camera-real", ["img-2", "img-1"])

    assert [image.image_id for image in images] == ["img-1", "img-2"]
    assert [image.image_id for image in repo.list_gallery_images("camera-real")] == [
        "img-2",
        "img-1",
    ]


def test_repository_lists_only_visible_gallery_for_public_page(tmp_path: Path) -> None:
    repo = SQLiteShowcaseRepository(tmp_path / "showcase.db")
    repo.initialize()
    visible_album = repo.get_gallery_album("camera-real")
    assert visible_album is not None
    repo.add_gallery_image(
        ShowcaseGalleryImage(
            image_id="visible-img",
            album_id=visible_album.album_id,
            image_path="storage/showcase_images/gallery/camera-real/visible.jpg",
            caption="展示",
            sort_order=1,
            is_visible=True,
            created_at="2026-08-22T10:00:00+08:00",
            updated_at="2026-08-22T10:00:00+08:00",
        )
    )
    repo.add_gallery_image(
        ShowcaseGalleryImage(
            image_id="hidden-img",
            album_id=visible_album.album_id,
            image_path="storage/showcase_images/gallery/camera-real/hidden.jpg",
            caption="隐藏",
            sort_order=2,
            is_visible=False,
            created_at="2026-08-22T10:00:00+08:00",
            updated_at="2026-08-22T10:00:00+08:00",
        )
    )
    hidden_album = repo.get_gallery_album("buyer-feedback")
    assert hidden_album is not None
    hidden_album.is_visible = False
    repo.upsert_gallery_album(hidden_album)

    public_albums = repo.list_gallery_albums(include_hidden=False)

    assert "买家反馈" not in [album.title for album in public_albums]
    assert [image.image_id for image in repo.list_gallery_images(visible_album.album_id)] == [
        "visible-img",
    ]


def test_upsert_product_preserves_and_lists_product(tmp_path: Path) -> None:
    repo = SQLiteShowcaseRepository(tmp_path / "showcase.db")
    repo.initialize()
    product = _product("p1", 558)

    repo.upsert_product(product)

    assert repo.get_product("p1") == product
    assert repo.list_products(include_hidden=True)[0] == product


def test_upsert_product_preserves_marketing_fields(tmp_path: Path) -> None:
    repo = SQLiteShowcaseRepository(tmp_path / "showcase.db")
    product = _product("p1", 558)
    product.short_selling_point = "小巧复古，适合新手"
    product.recommend_tags = "新手推荐,氛围感"

    repo.upsert_product(product)

    saved = repo.get_product("p1")
    assert saved is not None
    assert saved.short_selling_point == "小巧复古，适合新手"
    assert saved.recommend_tags == "新手推荐,氛围感"


def test_bulk_upsert_products_with_body_images(tmp_path: Path) -> None:
    repo = SQLiteShowcaseRepository(tmp_path / "showcase.db")
    product_a = _product("a", 300)
    product_b = _product("b", 400)

    repo.bulk_upsert_products_with_body_images(
        [product_a, product_b],
        {
            "a": "storage/showcase_images/a/body.jpg",
            "b": "storage/showcase_images/b/body.jpg",
        },
    )

    assert repo.get_product("a") == product_a
    assert repo.get_product("b") == product_b
    assert repo.list_product_images("a")[0].is_cover is True


def test_repository_returns_first_image_path_by_type(tmp_path: Path) -> None:
    repo = SQLiteShowcaseRepository(tmp_path / "showcase.db")
    repo.upsert_product(_product("p1", 300))
    repo.add_product_image("s2", "p1", "sample-images/p1/02.jpg", "sample", 11, False)
    repo.add_product_image("s1", "p1", "sample-images/p1/01.jpg", "sample", 10, False)

    paths = repo.list_first_image_paths_by_type("sample")

    assert paths == {"p1": "sample-images/p1/01.jpg"}


def test_repository_returns_first_image_path_by_type_for_selected_products(
    tmp_path: Path,
) -> None:
    repo = SQLiteShowcaseRepository(tmp_path / "showcase.db")
    repo.upsert_product(_product("p1", 300))
    repo.upsert_product(_product("p2", 400))
    repo.add_product_image("p1-s2", "p1", "sample-images/p1/02.jpg", "sample", 11, False)
    repo.add_product_image("p1-s1", "p1", "sample-images/p1/01.jpg", "sample", 10, False)
    repo.add_product_image("p2-s1", "p2", "sample-images/p2/01.jpg", "sample", 10, False)

    paths = repo.list_first_image_paths_by_type_for_products("sample", ["p1"])

    assert paths == {"p1": "sample-images/p1/01.jpg"}


def test_repository_search_products_returns_paginated_public_products(tmp_path: Path) -> None:
    repo = SQLiteShowcaseRepository(tmp_path / "showcase.db")
    for index in range(5):
        product = _product(f"p{index}", 300 + index)
        product.published_at = f"2026-08-10T10:0{index}:00+08:00"
        repo.upsert_product(product)
    hidden = _product("hidden", 399)
    hidden.visible = False
    sold = _product("sold", 399)
    sold.sold = True
    repo.upsert_product(hidden)
    repo.upsert_product(sold)

    result = repo.search_products(limit=2, offset=1)

    assert result.total == 5
    assert result.limit == 2
    assert result.offset == 1
    assert result.has_more is True
    assert [product.product_id for product in result.products] == ["p3", "p2"]


def test_repository_search_products_filters_by_brand_price_and_query(tmp_path: Path) -> None:
    repo = SQLiteShowcaseRepository(tmp_path / "showcase.db")
    canon = _product("canon", 558)
    canon.brand = "Canon"
    canon.model = "Canon ixus80"
    canon.display_copy = "cool white easy operation"
    different_brand = _product("different-brand", 558)
    different_brand.brand = "Sony"
    different_brand.model = "Sony t77"
    different_brand.display_copy = "cool white easy operation"
    price_out_of_range = _product("price-out-of-range", 650)
    price_out_of_range.brand = "Canon"
    price_out_of_range.model = "Canon ixus80"
    price_out_of_range.display_copy = "cool white easy operation"
    query_mismatch = _product("query-mismatch", 558)
    query_mismatch.brand = "Canon"
    query_mismatch.model = "Canon autoboy"
    query_mismatch.display_copy = "ultra slim street mood"
    repo.upsert_product(canon)
    repo.upsert_product(different_brand)
    repo.upsert_product(price_out_of_range)
    repo.upsert_product(query_mismatch)

    result = repo.search_products(
        ShowcaseProductSearch(query="cool white", brand="Canon", price_min=500, price_max=600)
    )

    assert result.total == 1
    assert [product.product_id for product in result.products] == ["canon"]


def test_repository_search_products_filters_by_multiple_brands_and_sorts_price(
    tmp_path: Path,
) -> None:
    repo = SQLiteShowcaseRepository(tmp_path / "showcase.db")
    canon = _product("canon", 558)
    canon.brand = "佳能"
    sony = _product("sony", 398)
    sony.brand = "索尼"
    fuji = _product("fuji", 688)
    fuji.brand = "富士"
    repo.upsert_product(canon)
    repo.upsert_product(sony)
    repo.upsert_product(fuji)

    ascending = repo.search_products(
        ShowcaseProductSearch(brands=("佳能", "索尼"), sort="price_asc")
    )
    descending = repo.search_products(
        ShowcaseProductSearch(brands=("佳能", "索尼"), sort="price_desc")
    )

    assert ascending.total == 2
    assert [product.product_id for product in ascending.products] == ["sony", "canon"]
    assert [product.product_id for product in descending.products] == ["canon", "sony"]


def test_repository_search_products_filters_by_manual_and_auto_sales_tags(tmp_path: Path) -> None:
    repo = SQLiteShowcaseRepository(tmp_path / "showcase.db")
    manual = _product("manual", 500)
    manual.recommend_tags = "新手推荐"
    manual.display_copy = "操作简单适合入门"
    auto = _product("auto", 600)
    auto.display_copy = "30倍光学变焦 演唱会 长焦"
    mixed = _product("mixed", 650)
    mixed.recommend_tags = "新手推荐"
    mixed.display_copy = "30倍光学变焦 演唱会 长焦"
    mixed.published_at = "2026-08-10T10:02:00+08:00"
    mixed.created_at = "2026-08-10T10:02:00+08:00"
    miss = _product("miss", 700)
    miss.display_copy = "普通复古小相机"
    repo.upsert_product(manual)
    repo.upsert_product(auto)
    repo.upsert_product(mixed)
    repo.upsert_product(miss)

    manual_result = repo.search_products(ShowcaseProductSearch(tags=("新手推荐",)))
    auto_result = repo.search_products(ShowcaseProductSearch(tags=("长焦",)))
    all_tags_result = repo.search_products(ShowcaseProductSearch(tags=("新手推荐", "长焦")))

    assert [product.product_id for product in manual_result.products] == ["mixed", "manual"]
    assert [product.product_id for product in auto_result.products] == ["mixed", "auto"]
    assert [product.product_id for product in all_tags_result.products] == ["mixed"]


def test_repository_can_manage_sections_and_items(tmp_path: Path) -> None:
    repo = SQLiteShowcaseRepository(tmp_path / "showcase.db")
    repo.upsert_product(_product("p1", 300))
    repo.upsert_product(_product("p2", 400))
    section = ShowcaseSection(
        section_id="gift",
        title="礼盒装专区",
        subtitle="适合送礼的套装",
        active=True,
        sort_order=2,
        created_at="2026-08-13T10:00:00+08:00",
        updated_at="2026-08-13T10:00:00+08:00",
    )

    repo.upsert_section(section)
    repo.upsert_section_item(
        ShowcaseSectionItem(
            item_id="i2",
            section_id="gift",
            product_id="p2",
            sort_order=2,
            recommend_note="预算友好",
            created_at="2026-08-13T10:00:00+08:00",
            updated_at="2026-08-13T10:00:00+08:00",
        )
    )
    repo.upsert_section_item(
        ShowcaseSectionItem(
            item_id="i1",
            section_id="gift",
            product_id="p1",
            sort_order=1,
            recommend_note="新手送礼首选",
            created_at="2026-08-13T10:00:00+08:00",
            updated_at="2026-08-13T10:00:00+08:00",
        )
    )

    assert repo.list_sections(include_hidden=True) == [section]
    assert [item.product_id for item in repo.list_section_items("gift")] == ["p1", "p2"]
    assert repo.list_section_items("gift")[0].recommend_note == "新手送礼首选"


def test_repository_can_delete_section_item_and_section(tmp_path: Path) -> None:
    repo = SQLiteShowcaseRepository(tmp_path / "showcase.db")
    repo.upsert_product(_product("p1", 300))
    repo.upsert_section(
        ShowcaseSection(
            section_id="recommend",
            title="个人推荐专区",
            subtitle="我自己挑的",
            active=True,
            sort_order=1,
            created_at="2026-08-13T10:00:00+08:00",
            updated_at="2026-08-13T10:00:00+08:00",
        )
    )
    repo.upsert_section_item(
        ShowcaseSectionItem(
            item_id="i1",
            section_id="recommend",
            product_id="p1",
            sort_order=1,
            recommend_note="推荐理由",
            created_at="2026-08-13T10:00:00+08:00",
            updated_at="2026-08-13T10:00:00+08:00",
        )
    )

    assert repo.delete_section_item("i1") is True
    assert repo.list_section_items("recommend") == []
    assert repo.delete_section("recommend") is True
    assert repo.list_sections(include_hidden=True) == []
