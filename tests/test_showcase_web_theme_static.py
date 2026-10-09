from __future__ import annotations

from pathlib import Path


STATIC_DIR = Path("src/moments_inventory/showcase_web/static")


def test_customer_page_uses_pink_camera_shop_title() -> None:
    html = (STATIC_DIR / "index.html").read_text(encoding="utf-8")

    assert "<title>星星CCD相机小铺商品展示</title>" in html
    assert "<h1>星星✨|CCD📷库存查看</h1>" in html
    assert "<p class=\"eyebrow\">Xingxing CCD Stock</p>" in html
    assert "星星✨|CCD📷库存查看" in html


def test_pink_cat_theme_assets_and_styles_are_present() -> None:
    css = (STATIC_DIR / "showcase.css").read_text(encoding="utf-8")

    assert "kitty-real/shop-header-guide.jpg" in css
    assert "kitty-real/pink-character.jpg" in css
    assert "--sticker-image" in css
    assert ".filter-sticker" in css
    assert ".shop-intro-panel" in css
    assert "--kitty-pink" in css
    assert "YouYuan" in css
    assert "white-space: nowrap" in css
    assert "grid-template-columns: repeat(5, minmax(0, 1fr))" in css
    assert "background-size: contain" in css
    assert "filter: none" in css


def test_filter_buttons_render_sticker_icon_markup() -> None:
    js = (STATIC_DIR / "showcase.js").read_text(encoding="utf-8")
    html = (STATIC_DIR / "index.html").read_text(encoding="utf-8")

    assert "filter-sticker" in js
    assert "FILTER_STICKER_SEQUENCE" in js
    assert "filter-stickers" in js
    assert "filter-001.png" in js
    assert "filter-025.png" in js
    assert "shop-intro-panel" in js
    # 发布新版交互时必须更新缓存版本，避免浏览器继续执行旧脚本。
    assert "showcase.js?v=20261009-copy-fallback" in html
    assert "showcase.css?v=20260921-optimization2" in html


def test_quick_filters_are_split_into_customer_friendly_sections() -> None:
    css = (STATIC_DIR / "showcase.css").read_text(encoding="utf-8")
    html = (STATIC_DIR / "index.html").read_text(encoding="utf-8")

    assert 'class="quick-filter-groups"' in html
    assert '<details class="quick-filter-panel"' in html
    assert 'class="quick-filter-group-title">品牌</h3>' in html
    assert 'class="quick-filter-group-title">特点</h3>' in html
    assert 'class="quick-filter-group-title">价位</h3>' in html
    assert html.index('class="quick-filter-group-title">品牌</h3>') < html.index('id="brandFilterButtons"')
    assert html.index('class="quick-filter-group-title">特点</h3>') < html.index('id="tagFilterButtons"')
    assert html.index('class="quick-filter-group-title">价位</h3>') < html.index('id="pricePresetButtons"')
    assert ".quick-filter-groups" in css
    assert ".quick-filter-group-title" in css


def test_store_gallery_markup_and_script_are_present() -> None:
    js = (STATIC_DIR / "showcase.js").read_text(encoding="utf-8")
    html = (STATIC_DIR / "index.html").read_text(encoding="utf-8")

    assert 'id="storeGallery"' in html
    assert "/api/public/gallery" in js
    assert "renderStoreGallery" in js
    assert "store-gallery-thumbnails" in js
    assert "store-gallery-thumb" in js


def test_purchase_steps_markup_and_script_are_present() -> None:
    js = (STATIC_DIR / "showcase.js").read_text(encoding="utf-8")
    css = (STATIC_DIR / "showcase.css").read_text(encoding="utf-8")
    html = (STATIC_DIR / "index.html").read_text(encoding="utf-8")

    assert 'id="purchaseSteps"' in html
    assert html.index('id="statementPanel"') < html.index('id="purchaseSteps"')
    assert html.index('id="purchaseSteps"') < html.index('id="storeGallery"')
    assert "/api/public/purchase-steps" in js
    assert "renderPurchaseSteps" in js
    assert "purchase-step-card" in js
    assert ".purchase-steps-panel" in css


def test_store_gallery_defaults_to_thumbnail_display() -> None:
    css = (STATIC_DIR / "showcase.css").read_text(encoding="utf-8")

    assert ".store-gallery-thumbnails" in css
    assert "grid-template-columns: repeat(auto-fill, minmax(150px, 1fr))" in css
    assert ".store-gallery-thumb img" in css
    assert "object-fit: cover" in css


def test_admin_store_gallery_management_markup_and_script_are_present() -> None:
    js = (STATIC_DIR / "admin.js").read_text(encoding="utf-8")
    html = (STATIC_DIR / "admin.html").read_text(encoding="utf-8")

    assert 'id="galleryForm"' in html
    assert 'id="galleryAlbumList"' in html
    assert "/api/admin/gallery/albums" in js
    assert "renderGalleryAlbums" in js
    assert "gallery-image-file" in js


def test_admin_purchase_steps_management_markup_and_script_are_present() -> None:
    js = (STATIC_DIR / "admin.js").read_text(encoding="utf-8")
    html = (STATIC_DIR / "admin.html").read_text(encoding="utf-8")

    assert 'id="purchaseStepForm"' in html
    assert 'id="purchaseStepList"' in html
    assert "/api/admin/purchase-steps" in js
    assert "renderPurchaseStepsAdmin" in js


def test_admin_sections_can_search_products_and_create_product_into_sections() -> None:
    js = (STATIC_DIR / "admin.js").read_text(encoding="utf-8")
    html = (STATIC_DIR / "admin.html").read_text(encoding="utf-8")

    assert "section-product-search-input" in js
    assert "section-product-search-results" in js
    assert "searchSectionProducts" in js
    assert "section-product-select" not in js
    assert 'id="createSectionPicker"' in html
    assert "createSectionPicker" in js
    assert "sectionIds" in js
    assert "sectionRecommendNote" in js
    assert "sectionSortOrder" in js


def test_filter_sticker_assets_are_complete() -> None:
    sticker_dir = STATIC_DIR / "assets/theme/filter-stickers"
    files = sorted(sticker_dir.glob("filter-*.png"))

    assert len(files) == 25
    assert files[0].name == "filter-001.png"
    assert files[-1].name == "filter-025.png"
    assert all(path.stat().st_size > 0 for path in files)
