from __future__ import annotations

import csv
from dataclasses import replace
from pathlib import Path
from io import BytesIO, StringIO
from zipfile import ZipFile

import pytest
from fastapi.testclient import TestClient

from moments_inventory.showcase_web.app import create_showcase_app
from moments_inventory.showcase_web.auth import hash_password
from moments_inventory.showcase_web.models import ShowcaseProduct, ShowcaseSection
from moments_inventory.showcase_web.repository import SQLiteShowcaseRepository
from PIL import Image


def _valid_png_bytes() -> bytes:
    target = BytesIO()
    Image.new("RGB", (2, 2), "white").save(target, format="PNG")
    return target.getvalue()


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


def _product_with(
    product_id: str,
    *,
    model: str,
    brand: str,
    price: int,
    visible: bool = True,
    sold: bool = False,
    copy: str = "展示文案",
    tags: str = "",
    import_id: str = "import-1",
) -> ShowcaseProduct:
    product = _product(product_id, visible=visible, display_price=price, brand=brand)
    product.model = model
    product.sold = sold
    product.display_copy = copy
    product.raw_copy = copy
    product.recommend_tags = tags
    product.last_seen_import_id = import_id
    return product


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


def test_admin_product_listing_rejects_deep_offset_before_repository_query(
    authenticated_client: TestClient,
    repo: SQLiteShowcaseRepository,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        repo,
        "search_admin_products",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("不应执行深分页查询")),
    )
    response = authenticated_client.get("/api/admin/products", params={"offset": 10_001})

    assert response.status_code == 400
    assert response.json()["detail"] == "offset 查询参数超出最大值 10000"


def test_admin_can_update_single_product_price(
    authenticated_client: TestClient,
    repo: SQLiteShowcaseRepository,
) -> None:
    repo.upsert_product(_product("p1", visible=True, display_price=558))

    response = authenticated_client.patch("/api/admin/products/p1", json={"displayPrice": 688, "expectedVersion": repo.get_product("p1").row_version})

    assert response.status_code == 200
    product = repo.get_product("p1")
    assert product is not None
    assert product.display_price == 688


def test_admin_single_product_update_rejects_cross_repository_stale_write(
    authenticated_client: TestClient,
    repo: SQLiteShowcaseRepository,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo.upsert_product(_product("p1", visible=True, display_price=558))
    stale_version = repo.get_product("p1").row_version
    competing_repo = SQLiteShowcaseRepository(tmp_path / "showcase.db")
    original_compare_and_swap = repo.update_admin_product_if_version

    def interleave_competing_write(
        product: ShowcaseProduct,
        expected_version: int,
    ) -> bool:
        competing = competing_repo.get_product("p1")
        assert competing is not None
        competing.display_price = 777
        competing.display_copy = "另一个管理进程刚保存的文案"
        competing_repo.upsert_product(competing)
        return original_compare_and_swap(product, expected_version)

    monkeypatch.setattr(repo, "update_admin_product_if_version", interleave_competing_write)

    response = authenticated_client.patch(
        "/api/admin/products/p1",
        json={"displayPrice": 688, "expectedVersion": stale_version},
    )

    saved = repo.get_product("p1")
    competing_repo.close()
    assert response.status_code == 409
    assert saved is not None
    assert saved.display_price == 777
    assert saved.display_copy == "另一个管理进程刚保存的文案"


def test_admin_can_update_product_marketing_fields(
    authenticated_client: TestClient,
    repo: SQLiteShowcaseRepository,
) -> None:
    repo.upsert_product(_product("p1", visible=True, display_price=558))

    response = authenticated_client.patch(
        "/api/admin/products/p1",
        json={
            "expectedVersion": repo.get_product("p1").row_version,
            "shortSellingPoint": "小巧复古，适合新手",
            "recommendTags": ["新手推荐", "氛围感"],
        },
    )

    assert response.status_code == 200
    product = repo.get_product("p1")
    assert product is not None
    assert product.short_selling_point == "小巧复古，适合新手"
    assert product.recommend_tags == "新手推荐,氛围感"


def test_admin_settings_database_failure_rolls_back_all_fields(tmp_path: Path) -> None:
    repo = SQLiteShowcaseRepository(tmp_path / "showcase.db")
    repo.set_setting("admin_password_hash", hash_password("admin-pass"))
    repo.set_setting("statement_text", "旧声明")
    repo.set_setting("watermark_text", "旧水印")
    with repo._get_connection() as conn:
        conn.execute("""create trigger reject_watermark_update before insert on showcase_settings
            when new.setting_key='watermark_text'
            begin select raise(abort, 'test failure'); end""")
    client = TestClient(create_showcase_app(repository=repo), raise_server_exceptions=False)
    assert client.post("/api/admin/login", json={"password": "admin-pass"}).status_code == 200

    response = client.patch(
        "/api/admin/settings",
        json={"statementText": "新声明", "watermarkText": "新水印"},
    )

    assert response.status_code == 500
    assert repo.get_setting("statement_text") == "旧声明"
    assert repo.get_setting("watermark_text") == "旧水印"


def test_admin_can_manage_gallery_albums(authenticated_client: TestClient) -> None:
    list_response = authenticated_client.get("/api/admin/gallery/albums")
    assert list_response.status_code == 200
    assert [album["title"] for album in list_response.json()["albums"]] == [
        "相机实拍",
        "礼盒装展示",
        "工作室日常",
        "买家反馈",
    ]

    create_response = authenticated_client.post(
        "/api/admin/gallery/albums",
        json={
            "title": "发货前检查",
            "description": "每台相机发货前检测记录",
            "sortOrder": 9,
            "isVisible": True,
        },
    )

    assert create_response.status_code == 201
    album_id = create_response.json()["albumId"]
    update_response = authenticated_client.patch(
        f"/api/admin/gallery/albums/{album_id}",
        json={"title": "发货前检测", "isVisible": False},
    )
    assert update_response.status_code == 200
    assert update_response.json()["title"] == "发货前检测"
    assert update_response.json()["isVisible"] is False


def test_admin_can_manage_purchase_steps(authenticated_client: TestClient) -> None:
    list_response = authenticated_client.get("/api/admin/purchase-steps")
    assert list_response.status_code == 200
    assert [step["title"] for step in list_response.json()["steps"]][:3] == [
        "挑选型号",
        "复制咨询文案",
        "微信咨询客服",
    ]

    create_response = authenticated_client.post(
        "/api/admin/purchase-steps",
        json={
            "title": "补充需求",
            "description": "有特殊预算或颜色要求可以直接说明。",
            "sortOrder": 99,
            "isVisible": True,
        },
    )

    assert create_response.status_code == 201
    step_id = create_response.json()["stepId"]
    update_response = authenticated_client.patch(
        f"/api/admin/purchase-steps/{step_id}",
        json={"title": "补充偏好", "isVisible": False},
    )
    assert update_response.status_code == 200
    assert update_response.json()["title"] == "补充偏好"
    assert update_response.json()["isVisible"] is False

    delete_response = authenticated_client.delete(f"/api/admin/purchase-steps/{step_id}")
    assert delete_response.status_code == 200
    assert step_id not in [
        item["stepId"]
        for item in authenticated_client.get("/api/admin/purchase-steps").json()["steps"]
    ]


def test_admin_can_upload_gallery_image(
    authenticated_client: TestClient,
    tmp_path: Path,
) -> None:
    album_id = "camera-real"
    response = authenticated_client.post(
        f"/api/admin/gallery/albums/{album_id}/images",
        data={"caption": "真实库存实拍", "isVisible": "true"},
        files={"file": ("camera.jpg", _valid_png_bytes(), "image/jpeg")},
    )

    assert response.status_code == 201
    data = response.json()
    assert data["caption"] == "真实库存实拍"
    assert data["imagePath"].startswith("storage/showcase_images/gallery/camera-real/")
    assert Path(tmp_path).exists()

    list_response = authenticated_client.get("/api/admin/gallery/albums")
    album = next(item for item in list_response.json()["albums"] if item["albumId"] == album_id)
    assert album["images"][0]["imageId"] == data["imageId"]


def test_admin_old_batch_endpoint_cannot_bypass_confirmation(authenticated_client, repo):
    repo.upsert_product(_product("canon", visible=True, display_price=500))
    response = authenticated_client.post("/api/admin/products/batch-price",
        json={"mode": "increment", "amount": 30, "brand": "佳能"})
    assert response.status_code == 410
    assert repo.get_product("canon").display_price == 500


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


def test_admin_can_create_product_and_add_it_to_sections(
    authenticated_client: TestClient,
    repo: SQLiteShowcaseRepository,
) -> None:
    repo.upsert_section(
        ShowcaseSection(
            section_id="new-arrivals",
            title="最近上新",
            subtitle="近期新增",
            active=True,
            sort_order=1,
            created_at="2026-08-10T10:01:00+08:00",
            updated_at="2026-08-10T10:01:00+08:00",
        )
    )
    repo.upsert_section(
        ShowcaseSection(
            section_id="recommend",
            title="个人推荐专区",
            subtitle="重点推荐",
            active=True,
            sort_order=2,
            created_at="2026-08-10T10:01:00+08:00",
            updated_at="2026-08-10T10:01:00+08:00",
        )
    )

    response = authenticated_client.post(
        "/api/admin/products",
        json={
            "productId": "manual-section-1",
            "model": "佳能ixus860",
            "brand": "佳能",
            "displayPrice": 1088,
            "displayCopy": "手动新增并加入专栏",
            "sectionIds": ["new-arrivals", "recommend"],
            "sectionRecommendNote": "适合重点推",
            "sectionSortOrder": 6,
        },
    )

    assert response.status_code == 201
    assert repo.get_product("manual-section-1") is not None
    new_items = repo.list_section_items("new-arrivals")
    recommend_items = repo.list_section_items("recommend")
    assert [item.product_id for item in new_items] == ["manual-section-1"]
    assert [item.product_id for item in recommend_items] == ["manual-section-1"]
    assert new_items[0].recommend_note == "适合重点推"
    assert recommend_items[0].sort_order == 6


def test_admin_can_upload_product_image(
    tmp_path: Path,
    repo: SQLiteShowcaseRepository,
) -> None:
    repo.upsert_product(_product("p1", visible=True, display_price=558))
    client = TestClient(
        create_showcase_app(
            repository=repo,
            storage_dir=tmp_path / "storage" / "showcase_images",
        )
    )
    login = client.post("/api/admin/login", json={"password": "admin-pass"})
    assert login.status_code == 200

    response = client.post(
        "/api/admin/products/p1/images",
        files={"file": ("body.jpg", _valid_png_bytes(), "image/jpeg")},
        data={"imageType": "detail"},
    )

    assert response.status_code == 201
    image = repo.list_product_images("p1")[0]
    assert image.image_type == "detail"
    assert (tmp_path / image.image_path).read_bytes() == _valid_png_bytes()


def test_admin_rejects_fake_image_without_leaving_file(
    authenticated_client: TestClient,
    repo: SQLiteShowcaseRepository,
    tmp_path: Path,
) -> None:
    repo.upsert_product(_product("fake", visible=True, display_price=558))
    response = authenticated_client.post(
        "/api/admin/products/fake/images",
        files={"file": ("fake.jpg", b"not-an-image", "image/jpeg")},
        data={"imageType": "detail"},
    )

    assert response.status_code == 400
    assert repo.list_product_images("fake") == []
    assert not list(tmp_path.rglob("*.upload"))


def test_admin_can_reorder_set_cover_and_delete_images(
    authenticated_client: TestClient,
    repo: SQLiteShowcaseRepository,
) -> None:
    repo.upsert_product(_product("p1", visible=True, display_price=558))
    repo.add_product_image("a", "p1", "storage/showcase_images/p1/a.jpg", "detail", 0, True)
    repo.add_product_image("b", "p1", "storage/showcase_images/p1/b.jpg", "detail", 1, False)

    reorder = authenticated_client.post(
        "/api/admin/products/p1/images/reorder",
        json={"imageIds": ["b", "a"]},
    )
    assert reorder.status_code == 200
    assert [image.image_id for image in repo.list_product_images("p1")] == ["b", "a"]

    cover = authenticated_client.post("/api/admin/products/p1/images/b/cover")
    assert cover.status_code == 200
    images = repo.list_product_images("p1")
    assert [image.is_cover for image in images] == [True, False]

    delete = authenticated_client.delete("/api/admin/products/p1/images/a")
    assert delete.status_code == 200
    assert [image.image_id for image in repo.list_product_images("p1")] == ["b"]


def test_admin_can_update_statement_and_customer_password(
    authenticated_client: TestClient,
    repo: SQLiteShowcaseRepository,
) -> None:
    response = authenticated_client.patch(
        "/api/admin/settings",
        json={
            "statementText": "新声明",
            "shopIntroText": "这里是星星CCD相机小铺简介",
            "customerPassword": "week-pass",
        },
    )

    assert response.status_code == 200
    assert repo.get_setting("statement_text") == "新声明"
    assert repo.get_setting("shop_intro_text") == "这里是星星CCD相机小铺简介"
    assert repo.get_setting("customer_password_hash") != "week-pass"


def test_admin_can_read_settings(authenticated_client: TestClient, repo: SQLiteShowcaseRepository) -> None:
    repo.set_setting("statement_text", "当前声明")
    repo.set_setting("shop_intro_text", "当前店铺简介")
    repo.set_setting("watermark_text", "星星CCD")
    repo.set_setting("inventory_updated_at", "2026-08-10")

    response = authenticated_client.get("/api/admin/settings")

    assert response.status_code == 200
    assert response.json()["statementText"] == "当前声明"
    assert response.json()["shopIntroText"] == "当前店铺简介"
    assert response.json()["watermarkText"] == "星星CCD"
    assert response.json()["inventoryUpdatedAt"] == "2026-08-10"


def test_admin_can_add_update_and_delete_authorized_partner(
    authenticated_client: TestClient,
    repo: SQLiteShowcaseRepository,
) -> None:
    create = authenticated_client.post(
        "/api/admin/partners",
        json={"name": "A代理", "note": "允许转发"},
    )
    assert create.status_code == 201
    partner_id = create.json()["partnerId"]

    update = authenticated_client.patch(
        f"/api/admin/partners/{partner_id}",
        json={"name": "A代理更新", "active": False},
    )
    delete = authenticated_client.delete(f"/api/admin/partners/{partner_id}")

    assert update.status_code == 200
    assert delete.status_code == 200
    assert repo.list_authorized_partners(active_only=False) == []


def test_admin_partners_include_active_and_sort_order(
    authenticated_client: TestClient,
    repo: SQLiteShowcaseRepository,
) -> None:
    repo.add_authorized_partner("p1", "A代理", "允许", 7, False)

    response = authenticated_client.get("/api/admin/partners")

    assert response.status_code == 200
    assert response.json()[0]["active"] is False
    assert response.json()[0]["sortOrder"] == 7


def test_admin_can_create_update_and_delete_section(
    authenticated_client: TestClient,
    repo: SQLiteShowcaseRepository,
) -> None:
    create = authenticated_client.post(
        "/api/admin/sections",
        json={
            "title": "礼盒装专区",
            "subtitle": "适合送礼",
            "active": True,
            "sortOrder": 1,
        },
    )
    assert create.status_code == 201
    section_id = create.json()["sectionId"]

    update = authenticated_client.patch(
        f"/api/admin/sections/{section_id}",
        json={"title": "礼盒装专区更新", "active": False, "sortOrder": 3},
    )
    list_response = authenticated_client.get("/api/admin/sections")
    delete = authenticated_client.delete(f"/api/admin/sections/{section_id}")

    assert update.status_code == 200
    assert update.json()["title"] == "礼盒装专区更新"
    assert update.json()["active"] is False
    assert list_response.status_code == 200
    assert list_response.json()["sections"][0]["sortOrder"] == 3
    assert delete.status_code == 200
    assert repo.list_sections(include_hidden=True) == []


def test_admin_can_manage_section_items(
    authenticated_client: TestClient,
    repo: SQLiteShowcaseRepository,
) -> None:
    repo.upsert_product(_product("p1", visible=True, display_price=558))
    repo.upsert_product(_product("p2", visible=True, display_price=588))
    create_section = authenticated_client.post(
        "/api/admin/sections",
        json={
            "title": "个人推荐专区",
            "subtitle": "我自己挑的",
            "active": True,
            "sortOrder": 1,
        },
    )
    section_id = create_section.json()["sectionId"]

    add_p2 = authenticated_client.post(
        f"/api/admin/sections/{section_id}/items",
        json={"productId": "p2", "sortOrder": 2, "recommendNote": "预算友好"},
    )
    add_p1 = authenticated_client.post(
        f"/api/admin/sections/{section_id}/items",
        json={"productId": "p1", "sortOrder": 1, "recommendNote": "新手首选"},
    )
    item_id = add_p1.json()["itemId"]
    update = authenticated_client.patch(
        f"/api/admin/sections/{section_id}/items/{item_id}",
        json={"sortOrder": 3, "recommendNote": "更新理由"},
    )
    section = authenticated_client.get("/api/admin/sections")
    delete = authenticated_client.delete(f"/api/admin/sections/{section_id}/items/{item_id}")

    assert add_p2.status_code == 201
    assert add_p1.status_code == 201
    assert update.status_code == 200
    assert update.json()["recommendNote"] == "更新理由"
    assert [item["productId"] for item in section.json()["sections"][0]["items"]] == ["p2", "p1"]
    assert delete.status_code == 200
    assert [item.product_id for item in repo.list_section_items(section_id)] == ["p2"]


def test_admin_products_support_server_side_filters(
    authenticated_client: TestClient,
    repo: SQLiteShowcaseRepository,
) -> None:
    repo.upsert_product(
        replace(_product_with(
            "canon",
            model="佳能ixus80",
            brand="佳能",
            price=488,
            copy="冷白皮 新手推荐",
            tags="新手推荐",
        ), price_override=488, source_display_price=450)
    )
    hidden = _product_with("hidden", model="索尼t77", brand="索尼", price=688, visible=False)
    sold = _product_with("sold", model="富士f50", brand="富士", price=788, sold=True)
    no_copy = _product_with("empty-copy", model="尼康s01", brand="尼康", price=0, copy="")
    repo.upsert_product(hidden)
    repo.upsert_product(sold)
    repo.upsert_product(no_copy)
    repo.add_product_image("canon-body", "canon", "storage/showcase_images/canon/body.jpg", "body", 0, True)
    repo.add_product_image("canon-sample", "canon", "sample-images/佳能/ixus80/01.jpg", "sample", 10, False)

    response = authenticated_client.get(
        "/api/admin/products",
        params={
            "query": "冷白皮",
            "brands": "佳能,索尼",
            "priceMin": 300,
            "priceMax": 500,
            "visible": "true",
            "sold": "false",
            "hasBodyImage": "true",
            "hasSampleImage": "true",
            "manualPrice": "true",
            "tags": "新手推荐",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert [product["productId"] for product in body["products"]] == ["canon"]
    assert body["products"][0]["hasBodyImage"] is True
    assert body["products"][0]["hasSampleImage"] is True
    assert body["products"][0]["manualPrice"] is True


def test_admin_bulk_price_preview_requires_explicit_scope(
    authenticated_client: TestClient,
) -> None:
    response = authenticated_client.post(
        "/api/admin/products/bulk-preview",
        json={"operation": "price", "priceMode": "increment", "amount": 30},
    )

    assert response.status_code == 422


def test_admin_bulk_selected_scope_requires_product_reference(
    authenticated_client: TestClient,
) -> None:
    response = authenticated_client.post(
        "/api/admin/products/bulk-preview",
        json={
            "scope": "selected",
            "operation": "hide",
            "productIds": [],
            "publicIds": [],
        },
    )

    assert response.status_code == 422


@pytest.mark.parametrize(
    ("reference_field", "references"),
    [
        ("productIds", [""]),
        ("publicIds", ["   "]),
    ],
)
def test_admin_bulk_selected_scope_rejects_blank_product_references(
    authenticated_client: TestClient,
    repo: SQLiteShowcaseRepository,
    reference_field: str,
    references: list[str],
) -> None:
    repo.upsert_product(_product_with("existing", model="佳能a", brand="佳能", price=300))

    response = authenticated_client.post(
        "/api/admin/products/bulk-preview",
        json={
            "scope": "selected",
            "operation": "hide",
            reference_field: references,
        },
    )

    assert response.status_code == 422
    assert "items" not in response.json()


def test_admin_bulk_selected_scope_combines_and_deduplicates_product_references(
    authenticated_client: TestClient,
    repo: SQLiteShowcaseRepository,
) -> None:
    repo.upsert_product(_product_with("by-product-id", model="佳能a", brand="佳能", price=300))
    repo.upsert_product(_product_with("by-public-id", model="索尼t", brand="索尼", price=500))
    repo.upsert_product(_product_with("not-selected", model="富士f50", brand="富士", price=700))
    public_id = repo.get_product("by-public-id").public_id  # type: ignore[union-attr]

    response = authenticated_client.post(
        "/api/admin/products/bulk-preview",
        json={
            "scope": "selected",
            "operation": "hide",
            "productIds": ["by-product-id", "by-product-id", "missing"],
            "publicIds": [public_id, public_id],
        },
    )

    assert response.status_code == 200
    assert response.json()["total"] == 2
    assert {item["productId"] for item in response.json()["items"]} == {
        "by-product-id",
        "by-public-id",
    }


@pytest.mark.parametrize(
    ("reference_field", "missing_reference"),
    [
        ("productIds", "missing-only"),
        ("publicIds", "missing-public-only"),
    ],
)
def test_admin_bulk_selected_scope_with_only_missing_references_returns_empty_preview(
    authenticated_client: TestClient,
    repo: SQLiteShowcaseRepository,
    reference_field: str,
    missing_reference: str,
) -> None:
    repo.upsert_product(_product_with("existing", model="佳能a", brand="佳能", price=300))

    response = authenticated_client.post(
        "/api/admin/products/bulk-preview",
        json={
            "scope": "selected",
            "operation": "hide",
            reference_field: [missing_reference],
        },
    )

    assert response.status_code == 200
    assert response.json()["total"] == 0
    assert response.json()["items"] == []


@pytest.mark.parametrize(
    "payload",
    [
        {
            "scope": "filtered",
            "operation": "hide",
            "productIds": ["p1"],
            "filters": {"priceMax": 500},
        },
        {
            "scope": "all",
            "operation": "hide",
            "publicIds": ["public-p1"],
        },
    ],
)
def test_admin_bulk_non_selected_scope_rejects_product_references(
    authenticated_client: TestClient,
    payload: dict[str, object],
) -> None:
    response = authenticated_client.post("/api/admin/products/bulk-preview", json=payload)

    assert response.status_code == 422


def test_admin_bulk_filtered_scope_rejects_visibility_only_filters(
    authenticated_client: TestClient,
) -> None:
    response = authenticated_client.post(
        "/api/admin/products/bulk-preview",
        json={
            "scope": "filtered",
            "operation": "hide",
            "filters": {"visible": True, "sold": False},
        },
    )

    assert response.status_code == 422


@pytest.mark.parametrize("price_mode", ["set", "tiered_increment"])
def test_admin_bulk_rejects_removed_price_modes(
    authenticated_client: TestClient,
    price_mode: str,
) -> None:
    response = authenticated_client.post(
        "/api/admin/products/bulk-preview",
        json={
            "scope": "all",
            "operation": "price",
            "priceMode": price_mode,
            "amount": 30,
        },
    )

    assert response.status_code == 422


def test_admin_bulk_all_scope_accepts_visibility_filters(
    authenticated_client: TestClient,
    repo: SQLiteShowcaseRepository,
) -> None:
    repo.upsert_product(_product_with("visible", model="佳能a", brand="佳能", price=300))
    repo.upsert_product(_product_with("hidden", model="索尼t", brand="索尼", price=500, visible=False))
    repo.upsert_product(_product_with("sold", model="富士f50", brand="富士", price=700, sold=True))

    response = authenticated_client.post(
        "/api/admin/products/bulk-preview",
        json={
            "scope": "all",
            "operation": "price",
            "priceMode": "increment",
            "amount": 30,
            "filters": {"visible": True, "sold": False},
        },
    )

    assert response.status_code == 200
    assert response.json()["total"] == 3
    assert response.json()["matchedCount"] == 3
    assert response.json()["changedCount"] == 1
    assert response.json()["skippedCount"] == 2


@pytest.mark.parametrize(
    ("filters", "expected_prices"),
    [
        ({"priceMax": 200}, [200]),
        ({"priceMin": 201, "priceMax": 300}, [201, 300]),
        ({"priceMin": 301, "priceMax": 600}, [301, 600]),
        ({"priceMin": 601, "priceMax": 800}, [601, 800]),
        ({"priceMin": 801}, [801]),
    ],
)
def test_admin_bulk_price_ranges_include_each_boundary(
    authenticated_client: TestClient,
    repo: SQLiteShowcaseRepository,
    filters: dict[str, int],
    expected_prices: list[int],
) -> None:
    for price in (200, 201, 300, 301, 600, 601, 800, 801):
        repo.upsert_product(_product_with(
            f"price-{price}",
            model=f"边界型号{price}",
            brand="边界品牌",
            price=price,
        ))

    response = authenticated_client.post(
        "/api/admin/products/bulk-preview",
        json={
            "scope": "filtered",
            "operation": "price",
            "priceMode": "increment",
            "amount": 30,
            "filters": {**filters, "visible": True, "sold": False},
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["matchedCount"] == len(expected_prices)
    assert sorted(item["oldPrice"] for item in body["items"]) == expected_prices


def test_admin_bulk_preview_distinguishes_source_and_display_price_filters(
    authenticated_client: TestClient,
    repo: SQLiteShowcaseRepository,
) -> None:
    repo.upsert_product(replace(
        _product_with("source-low-display-high", model="来源低", brand="佳能", price=230),
        source_display_price=180,
    ))
    repo.upsert_product(replace(
        _product_with("source-high-display-low", model="来源高", brand="佳能", price=180),
        source_display_price=230,
    ))
    repo.upsert_product(replace(
        _product_with("zero-price", model="零价", brand="佳能", price=0),
        source_display_price=0,
    ))

    source_response = authenticated_client.post(
        "/api/admin/products/bulk-preview",
        json={
            "scope": "all", "operation": "price", "amount": 1,
            "filters": {"sourcePriceMax": 200, "visible": True, "sold": False},
        },
    )
    display_response = authenticated_client.post(
        "/api/admin/products/bulk-preview",
        json={
            "scope": "all", "operation": "price", "amount": 1,
            "filters": {"displayPriceMax": 200, "visible": True, "sold": False},
        },
    )
    intersection_response = authenticated_client.post(
        "/api/admin/products/bulk-preview",
        json={
            "scope": "all", "operation": "price", "amount": 1,
            "filters": {
                "sourcePriceMax": 200, "displayPriceMax": 200,
                "visible": True, "sold": False,
            },
        },
    )
    zero_response = authenticated_client.post(
        "/api/admin/products/bulk-preview",
        json={
            "scope": "all", "operation": "price", "amount": 1,
            "filters": {"sourcePriceMax": 0, "displayPriceMax": 0, "visible": True, "sold": False},
        },
    )
    invalid_range_response = authenticated_client.post(
        "/api/admin/products/bulk-preview",
        json={
            "scope": "all", "operation": "price", "amount": 1,
            "filters": {"sourcePriceMin": 201, "sourcePriceMax": 200},
        },
    )
    invalid_display_range_response = authenticated_client.post(
        "/api/admin/products/bulk-preview",
        json={
            "scope": "all", "operation": "price", "amount": 1,
            "filters": {"displayPriceMin": 201, "displayPriceMax": 200},
        },
    )

    assert source_response.status_code == 200, source_response.text
    assert display_response.status_code == 200, display_response.text
    assert intersection_response.status_code == 200, intersection_response.text
    assert zero_response.status_code == 200, zero_response.text
    assert invalid_range_response.status_code == 422
    assert invalid_display_range_response.status_code == 422
    assert {item["productId"] for item in source_response.json()["items"]} == {"source-low-display-high", "zero-price"}
    assert {item["productId"] for item in display_response.json()["items"]} == {"source-high-display-low", "zero-price"}
    assert {item["productId"] for item in intersection_response.json()["items"]} == {"zero-price"}
    assert {item["productId"] for item in zero_response.json()["items"]} == {"zero-price"}


def test_admin_bulk_preview_reports_changed_unchanged_and_skipped_statistics(
    authenticated_client: TestClient,
    repo: SQLiteShowcaseRepository,
) -> None:
    repo.upsert_product(replace(
        _product_with("changed", model="变化商品", brand="佳能", price=200),
        source_display_price=180,
    ))
    repo.upsert_product(_product_with("unchanged", model="未变化商品", brand="佳能", price=230))
    repo.upsert_product(_product_with(
        "hidden", model="隐藏商品", brand="佳能", price=200, visible=False,
    ))
    repo.upsert_product(_product_with(
        "sold", model="已售商品", brand="佳能", price=200, sold=True,
    ))

    response = authenticated_client.post(
        "/api/admin/products/bulk-preview",
        json={
            "scope": "all",
            "operation": "price",
            "priceMode": "fixed_final",
            "amount": 230,
            "filters": {"priceMax": 300, "visible": True, "sold": False},
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["matchedCount"] == 4
    assert body["total"] == 4
    assert body["changedCount"] == 1
    assert body["unchangedCount"] == 1
    assert body["skippedCount"] == 2
    assert body["skipReasons"] == {"已隐藏": 1, "已售": 1}
    assert body["priceStats"] == {"minimum": 230, "maximum": 230, "totalDelta": 30}
    items = {item["productId"]: item for item in body["items"]}
    assert items["changed"]["sourcePrice"] == 180
    assert items["changed"]["changed"] is True
    assert items["unchanged"]["changed"] is False
    assert items["hidden"]["skippedReason"] == "已隐藏"
    assert items["hidden"]["newPrice"] == 200
    assert items["sold"]["skippedReason"] == "已售"
    assert items["sold"]["newPrice"] == 200


def test_admin_bulk_price_omitted_status_filters_default_to_visible_unsold(
    authenticated_client: TestClient,
    repo: SQLiteShowcaseRepository,
) -> None:
    repo.upsert_product(_product_with(
        "visible-unsold", model="正常商品", brand="佳能", price=200,
    ))
    repo.upsert_product(_product_with(
        "hidden-unsold", model="隐藏商品", brand="佳能", price=200, visible=False,
    ))
    repo.upsert_product(_product_with(
        "visible-sold", model="已售商品", brand="佳能", price=200, sold=True,
    ))

    response = authenticated_client.post(
        "/api/admin/products/bulk-preview",
        json={
            "scope": "all",
            "operation": "price",
            "priceMode": "increment",
            "amount": 30,
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["changedCount"] == 1
    assert body["skippedCount"] == 2
    items = {item["productId"]: item for item in body["items"]}
    assert items["visible-unsold"]["newPrice"] == 230
    assert items["hidden-unsold"]["skippedReason"] == "已隐藏"
    assert items["visible-sold"]["skippedReason"] == "已售"

    applied = authenticated_client.post(
        "/api/admin/products/bulk-apply",
        json={
            "previewId": body["previewId"],
            "idempotencyKey": "safe-default-statuses",
        },
    )
    assert applied.status_code == 200
    assert applied.json()["updatedCount"] == 1
    assert repo.get_product("visible-unsold").display_price == 230
    assert repo.get_product("hidden-unsold").display_price == 200
    assert repo.get_product("visible-sold").display_price == 200


def test_admin_bulk_price_explicit_null_status_filters_include_all_statuses(
    authenticated_client: TestClient,
    repo: SQLiteShowcaseRepository,
) -> None:
    repo.upsert_product(_product_with(
        "visible-unsold", model="正常商品", brand="佳能", price=200,
    ))
    repo.upsert_product(_product_with(
        "hidden-unsold", model="隐藏商品", brand="佳能", price=200, visible=False,
    ))
    repo.upsert_product(_product_with(
        "visible-sold", model="已售商品", brand="佳能", price=200, sold=True,
    ))

    response = authenticated_client.post(
        "/api/admin/products/bulk-preview",
        json={
            "scope": "all",
            "operation": "price",
            "priceMode": "increment",
            "amount": 30,
            "filters": {"visible": None, "sold": None},
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["changedCount"] == 3
    assert body["skippedCount"] == 0


def test_admin_bulk_hide_does_not_apply_price_status_defaults(
    authenticated_client: TestClient,
    repo: SQLiteShowcaseRepository,
) -> None:
    repo.upsert_product(_product_with(
        "visible-unsold", model="正常商品", brand="佳能", price=200,
    ))
    repo.upsert_product(_product_with(
        "visible-sold", model="已售商品", brand="佳能", price=200, sold=True,
    ))

    response = authenticated_client.post(
        "/api/admin/products/bulk-preview",
        json={"scope": "all", "operation": "hide"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["changedCount"] == 2
    assert body["skippedCount"] == 0


def test_admin_bulk_filtered_scope_rejects_inverted_price_range(
    authenticated_client: TestClient,
) -> None:
    response = authenticated_client.post(
        "/api/admin/products/bulk-preview",
        json={
            "scope": "filtered",
            "operation": "price",
            "priceMode": "increment",
            "amount": 30,
            "filters": {"priceMin": 301, "priceMax": 300},
        },
    )

    assert response.status_code == 422


def test_admin_bulk_filtered_price_increment_requires_positive_amount(
    authenticated_client: TestClient,
) -> None:
    response = authenticated_client.post(
        "/api/admin/products/bulk-preview",
        json={
            "scope": "filtered",
            "operation": "price",
            "priceMode": "increment",
            "amount": 0,
            "filters": {"priceMax": 200},
        },
    )

    assert response.status_code == 422


def test_admin_bulk_price_decrement_preview(
    authenticated_client: TestClient,
    repo: SQLiteShowcaseRepository,
) -> None:
    repo.upsert_product(_product_with("p1", model="佳能a", brand="佳能", price=300))

    response = authenticated_client.post(
        "/api/admin/products/bulk-preview",
        json={
            "scope": "selected",
            "operation": "price",
            "priceMode": "decrement",
            "amount": 30,
            "productIds": ["p1"],
        },
    )

    assert response.status_code == 200
    assert response.json()["items"][0]["newPrice"] == 270
    assert response.json()["items"][0]["delta"] == -30


def test_admin_bulk_price_decrement_below_zero_is_skipped(
    authenticated_client: TestClient,
    repo: SQLiteShowcaseRepository,
) -> None:
    repo.upsert_product(_product_with("p1", model="佳能a", brand="佳能", price=20))

    response = authenticated_client.post(
        "/api/admin/products/bulk-preview",
        json={
            "scope": "selected",
            "operation": "price",
            "priceMode": "decrement",
            "amount": 30,
            "productIds": ["p1"],
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["matchedCount"] == 1
    assert body["changedCount"] == 0
    assert body["unchangedCount"] == 0
    assert body["skippedCount"] == 1
    assert body["skipReasons"] == {"减价后低于 0 元": 1}
    assert body["priceStats"] == {"minimum": None, "maximum": None, "totalDelta": 0}
    assert body["items"][0]["newPrice"] == 20
    assert body["items"][0]["delta"] == 0
    assert body["items"][0]["changed"] is False
    assert body["items"][0]["skippedReason"] == "减价后低于 0 元"


def test_admin_bulk_price_preview_apply_and_undo(
    authenticated_client: TestClient,
    repo: SQLiteShowcaseRepository,
) -> None:
    repo.upsert_product(_product_with("low", model="佳能a", brand="佳能", price=280))
    repo.upsert_product(_product_with("mid", model="佳能ixus", brand="佳能", price=450))
    repo.upsert_product(_product_with("high", model="索尼t", brand="索尼", price=900))

    preview = authenticated_client.post(
        "/api/admin/products/bulk-preview",
        json={
            "scope": "filtered",
            "operation": "price",
            "priceMode": "increment",
            "amount": 30,
            "filters": {"priceMin": 300, "priceMax": 800, "visible": True},
        },
    )

    assert preview.status_code == 200
    preview_body = preview.json()
    assert preview_body["total"] == 1
    assert [
        (item["productId"], item["oldPrice"], item["newPrice"], item["delta"])
        for item in preview_body["items"]
    ] == [
        ("mid", 450, 480, 30),
    ]

    apply = authenticated_client.post(
        "/api/admin/products/bulk-apply",
        json={"previewId": preview_body["previewId"], "idempotencyKey": "price-once"},
    )

    assert apply.status_code == 200
    operation_id = apply.json()["operationId"]
    assert apply.json()["updatedCount"] == 1
    assert repo.get_product("low").display_price == 280  # type: ignore[union-attr]
    assert repo.get_product("mid").display_price == 480  # type: ignore[union-attr]
    assert repo.get_product("high").display_price == 900  # type: ignore[union-attr]

    operations = authenticated_client.get("/api/admin/operations")
    assert operations.status_code == 200
    assert operations.json()["operations"][0]["operationId"] == operation_id
    assert operations.json()["operations"][0]["updatedCount"] == 1

    undo = authenticated_client.post(f"/api/admin/operations/{operation_id}/undo", json={"idempotencyKey": "undo-once"})

    assert undo.status_code == 200
    assert repo.get_product("low").display_price == 280  # type: ignore[union-attr]
    assert repo.get_product("mid").display_price == 450  # type: ignore[union-attr]
    assert repo.get_product("high").display_price == 900  # type: ignore[union-attr]


def test_admin_bulk_hide_preview_and_apply_selected_products(
    authenticated_client: TestClient,
    repo: SQLiteShowcaseRepository,
) -> None:
    repo.upsert_product(_product_with("p1", model="佳能a", brand="佳能", price=300))
    repo.upsert_product(_product_with("p2", model="索尼t", brand="索尼", price=500))

    preview = authenticated_client.post(
        "/api/admin/products/bulk-preview",
        json={"scope": "selected", "operation": "hide", "productIds": ["p1"]},
    )
    apply = authenticated_client.post(
        "/api/admin/products/bulk-apply",
        json={"previewId": preview.json()["previewId"], "idempotencyKey": "hide-once"},
    )

    assert preview.status_code == 200
    assert preview.json()["items"][0]["oldVisible"] is True
    assert preview.json()["items"][0]["newVisible"] is False
    assert apply.status_code == 200
    assert repo.get_product("p1").visible is False  # type: ignore[union-attr]
    assert repo.get_product("p2").visible is True  # type: ignore[union-attr]


def test_admin_can_export_complete_bulk_preview_csv(
    authenticated_client: TestClient,
    repo: SQLiteShowcaseRepository,
) -> None:
    for index in range(205):
        repo.upsert_product(_product_with(
            f"p-{index}",
            model=f"导出商品{index}",
            brand="佳能",
            price=200 + index,
        ))

    preview_response = authenticated_client.post(
        "/api/admin/products/bulk-preview",
        json={
            "scope": "all",
            "operation": "price",
            "priceMode": "increment",
            "amount": 30,
            "filters": {"visible": True, "sold": False},
        },
    )

    assert preview_response.status_code == 200
    preview = preview_response.json()
    assert preview["matchedCount"] == 205
    assert preview["displayedCount"] == 200
    assert preview["truncated"] is True
    assert len(preview["items"]) == 200

    response = authenticated_client.get(
        f"/api/admin/products/bulk-preview/{preview['previewId']}/export"
    )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/csv")
    assert "attachment" in response.headers["content-disposition"]
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["x-content-type-options"] == "nosniff"
    assert "content-length" not in response.headers
    assert response.content.startswith(b"\xef\xbb\xbf")
    assert response.text.count("\n") == 206
    assert "p-204" in response.text
    assert (
        "商品ID,型号,品牌,导入原价,当前展示价,新展示价,变化金额,是否修改,"
        "跳过原因,展示状态,已售状态"
    ) in response.text


def test_bulk_preview_snapshot_is_private_to_its_owner(
    authenticated_client: TestClient,
    repo: SQLiteShowcaseRepository,
) -> None:
    repo.upsert_product(_product_with("p1", model="佳能a", brand="佳能", price=200))
    preview = authenticated_client.post(
        "/api/admin/products/bulk-preview",
        json={
            "scope": "selected",
            "operation": "price",
            "priceMode": "increment",
            "amount": 30,
            "productIds": ["p1"],
        },
    ).json()
    other_client = TestClient(create_showcase_app(repository=repo))
    login = other_client.post("/api/admin/login", json={"password": "admin-pass"})
    assert login.status_code == 200

    response = other_client.get(
        f"/api/admin/products/bulk-preview/{preview['previewId']}/export"
    )

    assert response.status_code == 404


def test_bulk_preview_snapshot_rejects_expired_preview(
    authenticated_client: TestClient,
    repo: SQLiteShowcaseRepository,
) -> None:
    repo.upsert_product(_product_with("p1", model="佳能a", brand="佳能", price=200))
    preview = authenticated_client.post(
        "/api/admin/products/bulk-preview",
        json={
            "scope": "selected",
            "operation": "price",
            "priceMode": "increment",
            "amount": 30,
            "productIds": ["p1"],
        },
    ).json()
    with repo._lock, repo._get_connection() as connection:
        connection.execute(
            "UPDATE showcase_bulk_previews SET expires_at=? WHERE preview_id=?",
            ("2000-01-01T00:00:00+00:00", preview["previewId"]),
        )

    response = authenticated_client.get(
        f"/api/admin/products/bulk-preview/{preview['previewId']}/export"
    )

    assert response.status_code == 409
    assert "过期" in response.json()["detail"]


def test_bulk_preview_export_requires_admin_login(
    repo: SQLiteShowcaseRepository,
) -> None:
    client = TestClient(create_showcase_app(repository=repo))

    response = client.get("/api/admin/products/bulk-preview/missing/export")

    assert response.status_code == 401


def test_bulk_preview_export_uses_saved_snapshot_after_inventory_changes(
    authenticated_client: TestClient,
    repo: SQLiteShowcaseRepository,
) -> None:
    repo.upsert_product(_product_with("p1", model="快照型号", brand="佳能", price=200))
    preview = authenticated_client.post(
        "/api/admin/products/bulk-preview",
        json={
            "scope": "selected",
            "operation": "price",
            "priceMode": "increment",
            "amount": 30,
            "productIds": ["p1"],
        },
    ).json()
    assert repo.update_product_price("p1", 999) is True

    response = authenticated_client.get(
        f"/api/admin/products/bulk-preview/{preview['previewId']}/export"
    )
    rows = list(csv.reader(StringIO(response.content.decode("utf-8-sig"), newline="")))

    assert response.status_code == 200
    assert rows[1][0] == "p1"
    assert rows[1][4:7] == ["200", "230", "30"]


def test_bulk_preview_export_escapes_formula_prefixes_and_preserves_csv_text(
    authenticated_client: TestClient,
    repo: SQLiteShowcaseRepository,
) -> None:
    dangerous_prefixes = ("=", "+", "-", "@", "\t", "\r", "\n")
    for index, prefix in enumerate(dangerous_prefixes):
        repo.upsert_product(_product_with(
            f"{prefix}id-{index}",
            model=f"{prefix}型号-{index}",
            brand=f"{prefix}品牌-{index}",
            price=200 + index,
        ))
    special_model = '机型,"旗舰"\n第二行'
    special_brand = '品,牌"甲"'
    repo.upsert_product(_product_with(
        "quoted", model=special_model, brand=special_brand, price=300,
    ))
    preview = authenticated_client.post(
        "/api/admin/products/bulk-preview",
        json={
            "scope": "all",
            "operation": "price",
            "priceMode": "decrement",
            "amount": 30,
            "filters": {"visible": True, "sold": False},
        },
    ).json()

    response = authenticated_client.get(
        f"/api/admin/products/bulk-preview/{preview['previewId']}/export"
    )
    rows = list(csv.reader(StringIO(response.content.decode("utf-8-sig"), newline="")))

    assert response.status_code == 200
    assert len(rows[0]) == 11
    data_rows = {row[0]: row for row in rows[1:]}
    for index, prefix in enumerate(dangerous_prefixes):
        row = data_rows[f"'{prefix}id-{index}"]
        assert row[1] == f"'{prefix}型号-{index}"
        assert row[2] == f"'{prefix}品牌-{index}"
        assert row[6] == "-30"
    quoted_row = data_rows["quoted"]
    assert quoted_row[1] == special_model
    assert quoted_row[2] == special_brand


def test_admin_diagnostics_reports_abnormal_products(
    authenticated_client: TestClient,
    repo: SQLiteShowcaseRepository,
) -> None:
    repo.upsert_product(_product_with("zero", model="通用x1", brand="通用", price=0, copy=""))
    repo.upsert_product(_product_with("dup-a", model="佳能ixus80", brand="佳能", price=500))
    repo.upsert_product(_product_with("dup-b", model="佳能ixus80", brand="佳能", price=520))
    repo.add_product_image("dup-body", "dup-a", "storage/showcase_images/dup-a/body.jpg", "body", 0, True)

    response = authenticated_client.get("/api/admin/diagnostics")

    assert response.status_code == 200
    body = response.json()
    assert body["counts"]["priceZero"] == 1
    assert body["counts"]["genericBrand"] == 1
    assert body["counts"]["missingCopy"] == 1
    assert body["counts"]["duplicateModel"] == 2
    assert "zero" in [item["productId"] for item in body["abnormalProducts"]]


def test_admin_rejects_incomplete_database_only_backup(
    authenticated_client: TestClient,
    repo: SQLiteShowcaseRepository,
) -> None:
    repo.upsert_product(_product_with("p1", model="佳能a", brand="佳能", price=300))

    response = authenticated_client.post("/api/admin/backups")

    assert response.status_code == 410
    assert "backup_showcase_db.bat" in response.json()["detail"]


def test_admin_can_create_sample_folder_binding(
    tmp_path: Path,
    repo: SQLiteShowcaseRepository,
) -> None:
    repo.upsert_product(_product("p1", visible=True, display_price=500))
    sample_root = tmp_path / "samples"
    folder = sample_root / "佳能" / "ixus 80"
    folder.mkdir(parents=True)
    (folder / "01.jpg").write_bytes(b"sample")
    authenticated_client = TestClient(create_showcase_app(repository=repo, sample_images_dir=sample_root))
    authenticated_client.post("/api/admin/login", json={"password": "admin-pass"})
    response = authenticated_client.post(
        "/api/admin/sample-bindings",
        json={
            "productId": "p1",
            "brand": "佳能",
            "modelKey": "ixus80",
            "folderPath": "佳能/ixus 80",
        },
    )

    assert response.status_code == 200
    assert repo.list_sample_folder_bindings()["product:p1"] == "佳能/ixus 80"


def test_admin_sample_matching_center_reports_summary_and_searches_assets(
    tmp_path: Path,
    repo: SQLiteShowcaseRepository,
) -> None:
    sample_root = tmp_path / "ccdcpt"
    model_dir = sample_root / "佳能" / "Canon 佳能DIGITAL IXUS 860 IS"
    model_dir.mkdir(parents=True)
    (model_dir / "01.jpg").write_bytes(b"sample-1")
    repo.upsert_product(_product_with("canon", model="佳能 IXY 910 IS", brand="佳能", price=688))
    repo.upsert_product(_product_with("nikon", model="尼康 s01", brand="尼康", price=588))
    client = TestClient(create_showcase_app(repository=repo, sample_images_dir=sample_root))
    assert client.post("/api/admin/login", json={"password": "admin-pass"}).status_code == 200

    rebuild = client.post("/api/admin/sample-matching/rebuild")
    summary = client.get("/api/admin/sample-matching/summary")
    missing = client.get("/api/admin/sample-matching/products", params={"status": "missing"})
    assets = client.get("/api/admin/sample-matching/assets", params={"query": "ixus"})

    assert rebuild.status_code == 200
    assert rebuild.json()["importResult"]["matchedProductCount"] == 1
    assert summary.status_code == 200
    assert summary.json()["totalProducts"] == 2
    assert summary.json()["assetModelCount"] == 1
    assert summary.json()["matchedProductCount"] == 1
    assert summary.json()["missingProductCount"] == 1
    assert summary.json()["coverageRate"] == 50.0
    assert missing.status_code == 200
    assert [item["productId"] for item in missing.json()["products"]] == ["nikon"]
    assert assets.status_code == 200
    assert assets.json()["assets"][0]["folderPath"] == "佳能/Canon 佳能DIGITAL IXUS 860 IS"


def test_admin_sample_matching_lists_support_offsets_and_report_remaining_pages(
    tmp_path: Path,
    repo: SQLiteShowcaseRepository,
) -> None:
    sample_root = tmp_path / "ccdcpt"
    for brand, model in (("佳能", "IXUS 80"), ("尼康", "S01")):
        model_dir = sample_root / brand / model
        model_dir.mkdir(parents=True)
        (model_dir / "01.jpg").write_bytes(f"{brand}-{model}".encode())
    repo.upsert_product(_product_with("first", model="IXUS 80", brand="佳能", price=200))
    repo.upsert_product(_product_with("second", model="S01", brand="尼康", price=300))
    client = TestClient(create_showcase_app(repository=repo, sample_images_dir=sample_root))
    assert client.post("/api/admin/login", json={"password": "admin-pass"}).status_code == 200

    product_first = client.get("/api/admin/sample-matching/products", params={"status": "all", "limit": 1, "offset": 0}).json()
    product_second = client.get("/api/admin/sample-matching/products", params={"status": "all", "limit": 1, "offset": 1}).json()
    asset_second = client.get("/api/admin/sample-matching/assets", params={"limit": 1, "offset": 1}).json()

    assert product_first["hasMore"] is True
    assert product_first["total"] is None
    assert product_second["hasMore"] is False
    assert product_second["total"] == 2
    assert product_first["products"][0]["productId"] != product_second["products"][0]["productId"]
    assert asset_second["total"] == 2
    assert asset_second["hasMore"] is False
    assert client.get("/api/admin/sample-matching/products", params={"offset": -1}).status_code == 400


def test_admin_sample_matching_bind_refreshes_product_sample_images(
    tmp_path: Path,
    repo: SQLiteShowcaseRepository,
) -> None:
    sample_root = tmp_path / "ccdcpt"
    model_dir = sample_root / "索尼" / "索尼DSC-W530"
    model_dir.mkdir(parents=True)
    (model_dir / "01.jpg").write_bytes(b"sony-sample")
    repo.upsert_product(_product_with("p1", model="索尼 w550", brand="索尼", price=488))
    client = TestClient(create_showcase_app(repository=repo, sample_images_dir=sample_root))
    assert client.post("/api/admin/login", json={"password": "admin-pass"}).status_code == 200

    response = client.post(
        "/api/admin/sample-matching/bind",
        json={"productId": "p1", "folderPath": "索尼/索尼DSC-W530"},
    )

    assert response.status_code == 200
    assert response.json()["bindingKey"] == "product:p1"
    assert response.json()["importResult"]["matchedProductCount"] == 1
    assert repo.list_product_images("p1")[0].image_path == "sample-images/索尼/索尼DSC-W530/01.jpg"


def test_admin_sample_matching_groups_can_bulk_bind_candidate_products(
    tmp_path: Path,
    repo: SQLiteShowcaseRepository,
) -> None:
    sample_root = tmp_path / "ccdcpt"
    model_dir = sample_root / "卡西欧" / "卡西欧EX-Z500"
    model_dir.mkdir(parents=True)
    (model_dir / "01.jpg").write_bytes(b"casio-sample")
    repo.upsert_product(_product_with("p1", model="卡西欧z500", brand="卡西欧", price=488))
    repo.upsert_product(_product_with("p2", model="卡西欧z500", brand="卡西欧", price=498))
    client = TestClient(create_showcase_app(repository=repo, sample_images_dir=sample_root))
    assert client.post("/api/admin/login", json={"password": "admin-pass"}).status_code == 200

    groups = client.get("/api/admin/sample-matching/groups")

    assert groups.status_code == 200
    group = groups.json()["groups"][0]
    assert group["model"] == "卡西欧z500"
    assert group["folderPath"] == "卡西欧/卡西欧EX-Z500"
    assert group["productCount"] == 2
    assert set(group["productIds"]) == {"p1", "p2"}

    bind = client.post(
        "/api/admin/sample-matching/groups/bind",
        json={"productIds": group["productIds"], "folderPath": group["folderPath"]},
    )

    assert bind.status_code == 200
    assert bind.json()["boundProductCount"] == 2
    assert repo.list_product_images("p1")[0].image_path == "sample-images/卡西欧/卡西欧EX-Z500/01.jpg"
    assert repo.list_product_images("p2")[0].image_path == "sample-images/卡西欧/卡西欧EX-Z500/01.jpg"


def test_admin_can_read_import_reports(
    authenticated_client: TestClient,
    repo: SQLiteShowcaseRepository,
) -> None:
    repo.save_import_log(
        import_id="import-1",
        source_path="manual/客户展示库存.xlsx",
        imported_at="2026-08-15T10:00:00+08:00",
        inserted_count=3,
        updated_count=5,
        missing_count=2,
    )

    response = authenticated_client.get("/api/admin/import-reports")

    assert response.status_code == 200
    assert response.json()["reports"][0] == {
        "importId": "import-1",
        "sourcePath": "manual/客户展示库存.xlsx",
        "importedAt": "2026-08-15T10:00:00+08:00",
        "insertedCount": 3,
        "updatedCount": 5,
        "missingCount": 2,
        "unmatchedCount": 0,
        "missingImageCount": 0,
    }
from moments_inventory.exporter import _write_workbook
from moments_inventory.showcase import SHOWCASE_HEADERS


def _review_workbook_bytes(tmp_path: Path, rows: list[dict[str, str]]) -> bytes:
    path = tmp_path / "review-upload.xlsx"
    sheet = [SHOWCASE_HEADERS]
    for values in rows:
        row = dict.fromkeys(SHOWCASE_HEADERS, "")
        row.update(values)
        sheet.append([row[name] for name in SHOWCASE_HEADERS])
    _write_workbook(path, sheet)
    return path.read_bytes()


def test_import_review_admin_endpoints_require_admin_for_every_operation(repo: SQLiteShowcaseRepository) -> None:
    client = TestClient(create_showcase_app(repository=repo))
    paths = [
        ("post", "/api/admin/import-review/batches"),
        ("get", "/api/admin/import-review/batches"),
        ("get", "/api/admin/import-review/batches/missing"),
        ("put", "/api/admin/import-review/batches/missing/rows/2"),
        ("post", "/api/admin/import-review/batches/missing/commit"),
        ("delete", "/api/admin/import-review/batches/missing"),
    ]

    for method, path in paths:
        response = getattr(client, method)(path)
        assert response.status_code == 401, (method, path, response.status_code)


def test_admin_can_upload_review_decide_commit_retry_and_discard(
    tmp_path: Path,
    authenticated_client: TestClient,
    repo: SQLiteShowcaseRepository,
) -> None:
    values = dict(zip(SHOWCASE_HEADERS, [
        "new-product", "ixus80", "Canon", "100", "200", "\u662f", "", "", "review-raw", "", "", "", "", "", "source-key-1",
    ]))
    content = _review_workbook_bytes(tmp_path, [values])

    uploaded = authenticated_client.post(
        "/api/admin/import-review/batches",
        data={"sourceScope": "source-a", "mode": "incremental", "complete": "false"},
        files={"file": (r"C:\\private\\review.xlsx", content, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
    )

    assert uploaded.status_code == 200, uploaded.text
    batch = uploaded.json()
    batch_id = batch["batchId"]
    assert batch["status"] == "pending"
    assert batch["sourceLabel"] == "review.xlsx"
    assert batch["sourcePath"] == "review.xlsx"
    assert "source_key" not in batch
    assert authenticated_client.get("/api/admin/import-review/batches").json()[0]["batchId"] == batch_id
    detail = authenticated_client.get(f"/api/admin/import-review/batches/{batch_id}")
    assert detail.status_code == 200
    row = detail.json()["rows"][0]
    assert row["rowNumber"] == 2
    assert row["sourceKey"] == "source-key-1"
    assert row["snapshot"]["raw_copy"] == "review-raw"

    decided = authenticated_client.put(
        f"/api/admin/import-review/batches/{batch_id}/rows/2",
        json={"decision": "create"},
    )
    assert decided.status_code == 200, decided.text
    assert decided.json()["decision"] == "create"
    committed = authenticated_client.post(
        f"/api/admin/import-review/batches/{batch_id}/commit",
        json={"idempotencyKey": "review-commit-1"},
    )
    assert committed.status_code == 200, committed.text
    assert committed.json()["inserted_count"] == 1
    retry = authenticated_client.post(
        f"/api/admin/import-review/batches/{batch_id}/commit",
        json={"idempotencyKey": "review-commit-1"},
    )
    assert retry.status_code == 200
    assert retry.json() == committed.json()
    conflict = authenticated_client.post(
        f"/api/admin/import-review/batches/{batch_id}/commit",
        json={"idempotencyKey": "different-key"},
    )
    assert conflict.status_code == 409

    another = authenticated_client.post(
        "/api/admin/import-review/batches",
        data={"sourceScope": "source-a", "mode": "incremental", "complete": "false"},
        files={"file": ("discard.xlsx", content, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
    )
    discarded = authenticated_client.delete(f"/api/admin/import-review/batches/{another.json()['batchId']}")
    assert discarded.status_code == 200
    assert discarded.json()["status"] == "discarded"


def test_invalid_import_review_upload_returns_400_without_creating_batch(
    authenticated_client: TestClient,
    repo: SQLiteShowcaseRepository,
) -> None:
    before = repo._get_connection().execute("select count(*) from showcase_import_review_batches").fetchone()[0]

    response = authenticated_client.post(
        "/api/admin/import-review/batches",
        data={"sourceScope": "source-a", "mode": "incremental", "complete": "false"},
        files={"file": ("invalid.xlsx", b"not an xlsx", "application/octet-stream")},
    )

    after = repo._get_connection().execute("select count(*) from showcase_import_review_batches").fetchone()[0]
    assert response.status_code == 400
    assert after == before


def test_import_review_upload_rejects_workbook_over_10_mib(
    authenticated_client: TestClient,
    repo: SQLiteShowcaseRepository,
) -> None:
    before = repo._get_connection().execute("select count(*) from showcase_import_review_batches").fetchone()[0]

    response = authenticated_client.post(
        "/api/admin/import-review/batches",
        data={"sourceScope": "source-a", "mode": "incremental", "complete": "false"},
        files={"file": ("large.xlsx", b"x" * (10 * 1024 * 1024 + 1), "application/octet-stream")},
    )

    after = repo._get_connection().execute("select count(*) from showcase_import_review_batches").fetchone()[0]
    assert response.status_code == 413
    assert after == before


def test_import_review_upload_maps_invalid_workbook_xml_to_400(
    authenticated_client: TestClient,
    repo: SQLiteShowcaseRepository,
) -> None:
    invalid_workbook = BytesIO()
    with ZipFile(invalid_workbook, "w") as archive:
        archive.writestr("xl/workbook.xml", b"<workbook><sheets>")
    before = repo._get_connection().execute("select count(*) from showcase_import_review_batches").fetchone()[0]

    response = authenticated_client.post(
        "/api/admin/import-review/batches",
        data={"sourceScope": "source-a", "mode": "incremental", "complete": "false"},
        files={"file": ("invalid-workbook.xlsx", invalid_workbook.getvalue(), "application/octet-stream")},
    )

    after = repo._get_connection().execute("select count(*) from showcase_import_review_batches").fetchone()[0]
    assert response.status_code == 400
    assert after == before


def test_import_review_upload_maps_shared_string_index_error_to_400(
    authenticated_client: TestClient,
    repo: SQLiteShowcaseRepository,
) -> None:
    invalid_workbook = BytesIO()
    with ZipFile(invalid_workbook, "w") as archive:
        archive.writestr(
            "xl/sharedStrings.xml",
            '<sst xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><si><t>only-value</t></si></sst>',
        )
        archive.writestr(
            "xl/workbook.xml",
            '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
            'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
            '<sheets><sheet name="Sheet1" sheetId="1" r:id="rId1"/></sheets></workbook>',
        )
        archive.writestr(
            "xl/_rels/workbook.xml.rels",
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Target="worksheets/sheet1.xml"/></Relationships>',
        )
        archive.writestr(
            "xl/worksheets/sheet1.xml",
            '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
            '<sheetData><row r="1"><c r="A1" t="s"><v>1</v></c></row></sheetData></worksheet>',
        )
    before = repo._get_connection().execute("select count(*) from showcase_import_review_batches").fetchone()[0]

    response = authenticated_client.post(
        "/api/admin/import-review/batches",
        data={"sourceScope": "source-a", "mode": "incremental", "complete": "false"},
        files={"file": ("invalid-shared-string.xlsx", invalid_workbook.getvalue(), "application/octet-stream")},
    )

    after = repo._get_connection().execute("select count(*) from showcase_import_review_batches").fetchone()[0]
    assert response.status_code == 400
    assert after == before


def test_import_review_upload_keeps_service_index_errors_as_server_errors(
    tmp_path: Path,
    authenticated_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def raise_index_error(*args: object, **kwargs: object) -> None:
        raise IndexError("service bug")

    monkeypatch.setattr(
        "moments_inventory.showcase_web.api.import_review_service.create_import_review_batch",
        raise_index_error,
    )
    content = _review_workbook_bytes(tmp_path, [{
        "商品ID": "new-product", "型号": "ixus80", "品牌": "佳能", "成本价": "100",
        "展示价": "200", "是否展示": "是",
    }])

    response = authenticated_client.post(
        "/api/admin/import-review/batches",
        data={"sourceScope": "source-a", "mode": "incremental", "complete": "false"},
        files={"file": ("valid.xlsx", content, "application/octet-stream")},
    )

    assert response.status_code == 500


def test_stale_import_review_target_returns_conflict_and_keeps_batch_pending(
    tmp_path: Path,
    authenticated_client: TestClient,
    repo: SQLiteShowcaseRepository,
) -> None:
    repo.upsert_product(_product("existing", visible=True, display_price=100))
    path = tmp_path / "stale-review.xlsx"
    _write_workbook(path, [SHOWCASE_HEADERS, [
        "new-product", "ixus80", "Canon", "100", "200", "\u662f", "", "", "", "", "", "", "", "", "",
    ]])
    content = path.read_bytes()
    uploaded = authenticated_client.post(
        "/api/admin/import-review/batches",
        data={"sourceScope": "default", "mode": "incremental", "complete": "false"},
        files={"file": ("review.xlsx", content, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
    )
    assert uploaded.status_code == 200, uploaded.text
    batch_id = uploaded.json()["batchId"]
    assert authenticated_client.put(
        f"/api/admin/import-review/batches/{batch_id}/rows/2", json={"decision": "link", "productId": "existing"}
    ).status_code == 200
    changed = repo.get_product("existing")
    changed.display_price += 1
    repo.upsert_product(changed)

    response = authenticated_client.post(
        f"/api/admin/import-review/batches/{batch_id}/commit", json={"idempotencyKey": "stale-key"}
    )

    assert response.status_code == 409
    assert repo.get_import_review_batch(batch_id)["status"] == "pending"
