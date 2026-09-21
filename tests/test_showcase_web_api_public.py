from __future__ import annotations

from pathlib import Path
from urllib.parse import quote
import time

from fastapi.testclient import TestClient

from moments_inventory.showcase_web.app import create_showcase_app
from moments_inventory.showcase_web.auth import hash_password
from moments_inventory.showcase_web.models import (
    ShowcaseGalleryImage,
    ShowcaseProduct,
    ShowcasePurchaseStep,
    ShowcaseSection,
    ShowcaseSectionItem,
)
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


def _assert_first_page_metadata(data: dict, *, total: int) -> None:
    assert data["total"] == total
    assert data["limit"] == 80
    assert data["offset"] == 0
    assert data["hasMore"] is False


def test_public_products_api_returns_only_visible_products(tmp_path: Path) -> None:
    repo = SQLiteShowcaseRepository(tmp_path / "showcase.db")
    repo.initialize()
    repo.upsert_product(_product("visible", visible=True, display_price=558))
    repo.upsert_product(_product("hidden", visible=False, display_price=588))
    repo.upsert_product(_product("sold", visible=True, sold=True, display_price=688))
    client = TestClient(create_showcase_app(repository=repo))

    response = client.get("/api/public/products")

    assert response.status_code == 200
    data = response.json()
    _assert_first_page_metadata(data, total=1)
    assert [item["productId"] for item in data["products"]] == ["visible"]
    assert data["products"][0]["displayPrice"] == 558


def test_public_offset_page_rejects_changed_catalog_revision(tmp_path: Path) -> None:
    repo = SQLiteShowcaseRepository(tmp_path / "showcase.db")
    repo.initialize()
    repo.upsert_product(_product("a", visible=True, display_price=100))
    repo.upsert_product(_product("b", visible=True, display_price=200))
    client = TestClient(create_showcase_app(repository=repo))
    first = client.get("/api/public/products", params={"limit": 1}).json()

    repo.update_product_price("a", 999)
    stale = client.get(
        "/api/public/products",
        params={"limit": 1, "offset": 1, "expectedRevision": first["catalogRevision"]},
    )

    assert stale.status_code == 409


def test_customer_password_also_protects_original_media(tmp_path: Path) -> None:
    repo = SQLiteShowcaseRepository(tmp_path / "showcase.db")
    repo.initialize()
    repo.set_setting("customer_password_hash", hash_password("week-pass"))
    storage = tmp_path / "storage"
    samples = tmp_path / "samples"
    storage.mkdir()
    samples.mkdir()
    (storage / "body.jpg").write_bytes(b"media")
    (samples / "sample.jpg").write_bytes(b"sample")
    client = TestClient(
        create_showcase_app(repository=repo, storage_dir=storage, sample_images_dir=samples)
    )

    assert client.get("/storage/showcase_images/body.jpg").status_code == 401
    assert client.get("/sample-images/sample.jpg").status_code == 401
    assert client.post("/api/public/access", json={"password": "week-pass"}).status_code == 200
    assert client.get("/storage/showcase_images/body.jpg").content == b"media"
    assert client.get("/sample-images/sample.jpg").content == b"sample"


def test_public_products_use_sample_image_as_cover_when_body_cover_is_missing(
    tmp_path: Path,
) -> None:
    repo = SQLiteShowcaseRepository(tmp_path / "showcase.db")
    repo.initialize()
    repo.upsert_product(_product("p1", visible=True, display_price=558))
    repo.add_product_image("s1", "p1", "sample-images/佳能/a/01.jpg", "sample", 10, False)
    client = TestClient(create_showcase_app(repository=repo))

    response = client.get("/api/public/products")

    assert response.status_code == 200
    assert response.json()["products"][0]["coverImagePath"] == "sample-images/佳能/a/01.jpg"


def test_public_gallery_api_returns_visible_albums_with_visible_images(tmp_path: Path) -> None:
    repo = SQLiteShowcaseRepository(tmp_path / "showcase.db")
    repo.initialize()
    album = repo.get_gallery_album("camera-real")
    assert album is not None
    repo.add_gallery_image(
        ShowcaseGalleryImage(
            image_id="img-visible",
            album_id=album.album_id,
            image_path="storage/showcase_images/gallery/camera-real/visible.jpg",
            caption="真实库存实拍",
            sort_order=1,
            is_visible=True,
            created_at="2026-08-22T10:00:00+08:00",
            updated_at="2026-08-22T10:00:00+08:00",
        )
    )
    repo.add_gallery_image(
        ShowcaseGalleryImage(
            image_id="img-hidden",
            album_id=album.album_id,
            image_path="storage/showcase_images/gallery/camera-real/hidden.jpg",
            caption="隐藏图片",
            sort_order=2,
            is_visible=False,
            created_at="2026-08-22T10:00:00+08:00",
            updated_at="2026-08-22T10:00:00+08:00",
        )
    )
    client = TestClient(create_showcase_app(repository=repo))

    response = client.get("/api/public/gallery")

    assert response.status_code == 200
    data = response.json()
    assert [album["title"] for album in data["albums"]] == ["相机实拍"]
    assert data["albums"][0]["images"] == [
        {
            "imageId": "img-visible",
            "imagePath": "storage/showcase_images/gallery/camera-real/visible.jpg",
            "caption": "真实库存实拍",
            "sortOrder": 1,
        }
    ]


def test_public_purchase_steps_api_returns_visible_steps(tmp_path: Path) -> None:
    repo = SQLiteShowcaseRepository(tmp_path / "showcase.db")
    repo.initialize()
    hidden_step = ShowcasePurchaseStep(
        step_id="hidden-step",
        title="隐藏步骤",
        description="客户不应该看到",
        sort_order=0,
        is_visible=False,
        created_at="2026-08-22T10:00:00+08:00",
        updated_at="2026-08-22T10:00:00+08:00",
    )
    repo.upsert_purchase_step(hidden_step)
    client = TestClient(create_showcase_app(repository=repo))

    response = client.get("/api/public/purchase-steps")

    assert response.status_code == 200
    data = response.json()
    assert [step["title"] for step in data["steps"]][:2] == ["挑选型号", "复制咨询文案"]
    assert "隐藏步骤" not in [step["title"] for step in data["steps"]]
    assert data["steps"][0]["description"] == "按品牌、预算、关键词筛选喜欢的 CCD。"


def test_public_products_include_marketing_fields(tmp_path: Path) -> None:
    repo = SQLiteShowcaseRepository(tmp_path / "showcase.db")
    repo.initialize()
    product = _product("p1", visible=True, display_price=558)
    product.short_selling_point = "小巧复古，适合新手"
    product.recommend_tags = "新手推荐,氛围感"
    repo.upsert_product(product)
    client = TestClient(create_showcase_app(repository=repo))

    response = client.get("/api/public/products")

    assert response.status_code == 200
    item = response.json()["products"][0]
    assert item["shortSellingPoint"] == "小巧复古，适合新手"
    assert item["recommendTags"] == ["新手推荐", "氛围感", "小巧"]


def test_public_products_api_supports_pagination_and_filters(tmp_path: Path) -> None:
    repo = SQLiteShowcaseRepository(tmp_path / "showcase.db")
    repo.initialize()
    for index, brand in enumerate(["Canon", "Canon", "Sony"], start=1):
        product = _product(
            f"p{index}",
            visible=True,
            display_price=300 + index * 100,
            brand=brand,
        )
        product.display_copy = "white recommended"
        product.published_at = f"2026-08-10T10:0{index}:00+08:00"
        repo.upsert_product(product)
    client = TestClient(create_showcase_app(repository=repo))

    response = client.get(
        "/api/public/products",
        params={
            "brand": "Canon",
            "priceMin": 300,
            "priceMax": 600,
            "query": "white",
            "limit": 1,
            "offset": 0,
        },
    )

    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 2
    assert data["limit"] == 1
    assert data["offset"] == 0
    assert data["hasMore"] is True
    assert len(data["products"]) == 1


def test_public_products_api_supports_multiple_brands_and_sorting(tmp_path: Path) -> None:
    repo = SQLiteShowcaseRepository(tmp_path / "showcase.db")
    repo.initialize()
    for product_id, brand, price in [
        ("canon", "佳能", 558),
        ("sony", "索尼", 398),
        ("fuji", "富士", 688),
    ]:
        repo.upsert_product(
            _product(product_id, visible=True, display_price=price, brand=brand)
        )
    client = TestClient(create_showcase_app(repository=repo))

    response = client.get(
        "/api/public/products",
        params={"brands": "佳能,索尼", "sort": "price_asc"},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 2
    assert [item["productId"] for item in data["products"]] == ["sony", "canon"]


def test_public_filters_api_returns_brands_tags_and_price_presets(tmp_path: Path) -> None:
    repo = SQLiteShowcaseRepository(tmp_path / "showcase.db")
    repo.initialize()
    canon = _product("canon", visible=True, display_price=558)
    canon.brand = "佳能"
    sony = _product("sony", visible=True, display_price=688)
    sony.brand = "索尼"
    hidden = _product("hidden", visible=False, display_price=499)
    hidden.brand = "隐藏品牌"
    sold = _product("sold", visible=True, display_price=499, sold=True)
    sold.brand = "售出品牌"
    repo.upsert_product(canon)
    repo.upsert_product(sony)
    repo.upsert_product(hidden)
    repo.upsert_product(sold)
    client = TestClient(create_showcase_app(repository=repo))

    response = client.get("/api/public/filters")

    assert response.status_code == 200
    data = response.json()
    assert data["brands"] == ["佳能", "索尼"]
    assert data["tags"] == ["长焦", "自拍", "小巧", "冷白皮", "氛围感"]
    assert "新手推荐" not in data["tags"]
    assert "礼盒装" not in data["tags"]
    assert {"label": "300以内", "priceMin": 0, "priceMax": 300} in data["pricePresets"]
    assert {"label": "500以内", "priceMin": 0, "priceMax": 500} in data["pricePresets"]


def test_public_sections_return_visible_sections_with_visible_products_only(
    tmp_path: Path,
) -> None:
    repo = SQLiteShowcaseRepository(tmp_path / "showcase.db")
    repo.initialize()
    visible_product = _product("visible", visible=True, display_price=558)
    visible_product.short_selling_point = "主推短卖点"
    visible_product.recommend_tags = "礼盒装,热门款"
    repo.upsert_product(visible_product)
    repo.upsert_product(_product("hidden", visible=False, display_price=588))
    repo.upsert_product(_product("sold", visible=True, sold=True, display_price=688))
    repo.add_product_image("s1", "visible", "sample-images/佳能/a/01.jpg", "sample", 10, False)
    repo.upsert_section(
        ShowcaseSection(
            section_id="gift",
            title="礼盒装专区",
            subtitle="适合送礼",
            active=True,
            sort_order=1,
            created_at="2026-08-13T10:00:00+08:00",
            updated_at="2026-08-13T10:00:00+08:00",
        )
    )
    repo.upsert_section(
        ShowcaseSection(
            section_id="hidden-section",
            title="隐藏专区",
            subtitle="不展示",
            active=False,
            sort_order=2,
            created_at="2026-08-13T10:00:00+08:00",
            updated_at="2026-08-13T10:00:00+08:00",
        )
    )
    for index, product_id in enumerate(["hidden", "visible", "sold"], start=1):
        repo.upsert_section_item(
            ShowcaseSectionItem(
                item_id=f"item-{product_id}",
                section_id="gift",
                product_id=product_id,
                sort_order=index,
                recommend_note=f"{product_id} 推荐理由",
                created_at="2026-08-13T10:00:00+08:00",
                updated_at="2026-08-13T10:00:00+08:00",
            )
        )
    client = TestClient(create_showcase_app(repository=repo))

    response = client.get("/api/public/sections")

    assert response.status_code == 200
    data = response.json()
    assert [section["sectionId"] for section in data["sections"]] == ["gift"]
    section = data["sections"][0]
    assert section["title"] == "礼盒装专区"
    assert [item["productId"] for item in section["products"]] == ["visible"]
    assert section["products"][0]["recommendNote"] == "visible 推荐理由"
    assert section["products"][0]["coverImagePath"] == "sample-images/佳能/a/01.jpg"
    assert section["products"][0]["shortSellingPoint"] == "主推短卖点"
    assert section["products"][0]["recommendTags"] == ["礼盒装", "热门款"]


def test_public_sections_fallback_to_rule_products_when_section_has_no_items(
    tmp_path: Path,
) -> None:
    repo = SQLiteShowcaseRepository(tmp_path / "showcase.db")
    repo.initialize()
    gift_product = _product("gift", visible=True, display_price=399)
    gift_product.recommend_tags = "礼盒装"
    other_product = _product("other", visible=True, display_price=899)
    other_product.recommend_tags = "氛围感"
    repo.upsert_product(gift_product)
    repo.upsert_product(other_product)
    repo.upsert_section(
        ShowcaseSection(
            section_id="gift-box",
            title="礼盒装专区",
            subtitle="适合送礼",
            active=True,
            sort_order=1,
            created_at="2026-08-13T10:00:00+08:00",
            updated_at="2026-08-13T10:00:00+08:00",
        )
    )
    client = TestClient(create_showcase_app(repository=repo))

    response = client.get("/api/public/sections")

    assert response.status_code == 200
    data = response.json()
    assert [section["sectionId"] for section in data["sections"]] == ["gift-box"]
    assert [item["productId"] for item in data["sections"][0]["products"]] == ["gift"]


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


def test_public_settings_returns_statement_and_partners(tmp_path: Path) -> None:
    repo = SQLiteShowcaseRepository(tmp_path / "showcase.db")
    repo.initialize()
    repo.set_setting("statement_text", "自定义声明")
    repo.set_setting("shop_intro_text", "自定义店铺简介")
    repo.add_authorized_partner("partner-1", "星星CCD直营", "主账号", 0, True)
    client = TestClient(create_showcase_app(repository=repo))

    response = client.get("/api/public/settings")

    assert response.status_code == 200
    assert response.json()["statementText"] == "自定义声明"
    assert response.json()["shopIntroText"] == "自定义店铺简介"
    assert response.json()["partners"][0]["name"] == "星星CCD直营"


def test_public_products_require_customer_password_when_configured(tmp_path: Path) -> None:
    repo = SQLiteShowcaseRepository(tmp_path / "showcase.db")
    repo.initialize()
    repo.set_setting("customer_password_hash", hash_password("week-pass"))
    repo.upsert_product(_product("p1", visible=True, display_price=558))
    client = TestClient(create_showcase_app(repository=repo))

    blocked = client.get("/api/public/products")
    wrong = client.post("/api/public/access", json={"password": "wrong-pass"})
    allowed = client.post("/api/public/access", json={"password": "week-pass"})
    products = client.get("/api/public/products")

    assert blocked.status_code == 401
    assert wrong.status_code == 401
    assert allowed.status_code == 200
    assert "showcase_customer_access" in allowed.cookies
    assert products.status_code == 200
    assert products.json()["products"][0]["productId"] == "p1"


def test_public_filters_require_customer_password_when_configured(tmp_path: Path) -> None:
    repo = SQLiteShowcaseRepository(tmp_path / "showcase.db")
    repo.initialize()
    repo.set_setting("customer_password_hash", hash_password("week-pass"))
    repo.upsert_product(_product("p1", visible=True, display_price=558))
    client = TestClient(create_showcase_app(repository=repo))

    blocked = client.get("/api/public/filters")
    client.post("/api/public/access", json={"password": "week-pass"})
    allowed = client.get("/api/public/filters")

    assert blocked.status_code == 401
    assert allowed.status_code == 200
    assert allowed.json()["brands"] == ["佳能"]


def test_public_access_status_reports_customer_access_state(tmp_path: Path) -> None:
    repo = SQLiteShowcaseRepository(tmp_path / "showcase.db")
    repo.initialize()
    repo.set_setting("customer_password_hash", hash_password("week-pass"))
    client = TestClient(create_showcase_app(repository=repo))

    locked = client.get("/api/public/access-status")
    client.post("/api/public/access", json={"password": "week-pass"})
    unlocked = client.get("/api/public/access-status")

    assert locked.status_code == 200
    assert locked.json() == {"requiresPassword": True, "authorized": False}
    assert unlocked.status_code == 200
    assert unlocked.json() == {"requiresPassword": True, "authorized": True}


def test_public_product_detail_requires_customer_password_when_configured(
    tmp_path: Path,
) -> None:
    repo = SQLiteShowcaseRepository(tmp_path / "showcase.db")
    repo.initialize()
    repo.set_setting("customer_password_hash", hash_password("week-pass"))
    repo.upsert_product(_product("p1", visible=True, display_price=558))
    client = TestClient(create_showcase_app(repository=repo))

    blocked = client.get("/api/public/products/p1")
    client.post("/api/public/access", json={"password": "week-pass"})
    allowed = client.get("/api/public/products/p1")

    assert blocked.status_code == 401
    assert allowed.status_code == 200
    assert allowed.json()["productId"] == "p1"


def test_app_serves_sample_images_directory(tmp_path: Path) -> None:
    sample_dir = tmp_path / "ccdcpt"
    image_dir = sample_dir / "索尼" / "索尼DSC-T10"
    image_dir.mkdir(parents=True)
    (image_dir / "01.jpg").write_bytes(b"sample-image")
    repo = SQLiteShowcaseRepository(tmp_path / "showcase.db")
    repo.initialize()
    client = TestClient(create_showcase_app(repository=repo, sample_images_dir=sample_dir))

    response = client.get("/sample-images/" + quote("索尼/索尼DSC-T10/01.jpg"))

    assert response.status_code == 200
    assert response.content == b"sample-image"


def test_public_response_cache_hits_and_catalog_change_invalidates(tmp_path: Path) -> None:
    repo = SQLiteShowcaseRepository(tmp_path / "showcase.db")
    repo.upsert_product(_product("p1", visible=True, display_price=558))
    client = TestClient(create_showcase_app(repository=repo))

    assert client.get("/api/public/products").headers["x-showcase-cache"] == "MISS"
    assert client.get("/api/public/products").headers["x-showcase-cache"] == "HIT"
    repo.upsert_product(_product("p2", visible=True, display_price=688))
    time.sleep(0.3)
    refreshed = client.get("/api/public/products")

    assert refreshed.headers["x-showcase-cache"] == "MISS"
    assert refreshed.json()["total"] == 2
