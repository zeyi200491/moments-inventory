from datetime import datetime

from moments_inventory.models import InventoryRecord
from moments_inventory.product_identity import build_product_key, normalize_listing_text


def record(content: str, price: int, images=None, model="IXUS 100"):
    return InventoryRecord(
        record_key=f"rk-{content}",
        remark_name="卖家A",
        wxid="wxid_a",
        published_at=datetime.fromisoformat("2026-08-01T10:00:00+08:00"),
        model=model,
        price=price,
        serial_no=None,
        status="未售卖",
        image_urls=images if images is not None else ["https://img/a.jpg", "https://img/b.jpg"],
        video_urls=[],
        content_text=content,
        source_moment_ids=["m1"],
    )


def test_normalize_listing_text_removes_price_but_keeps_product_words():
    assert normalize_listing_text("980💰佳能ixus100 香槟色 成色不错") == "佳能ixus100 香槟色 成色不错"
    assert normalize_listing_text("880💰佳能ixus100 香槟色 成色不错") == "佳能ixus100 香槟色 成色不错"


def test_normalize_listing_text_removes_prefix_price_but_keeps_model_digits():
    assert normalize_listing_text("💰980佳能ixus100 香槟色") == "佳能ixus100 香槟色"


def test_normalize_listing_text_removes_rmb_price_but_keeps_model_digits():
    assert normalize_listing_text("RMB980佳能ixus100 香槟色") == "佳能ixus100 香槟色"
    assert normalize_listing_text("rmb980佳能ixus100 香槟色") == "佳能ixus100 香槟色"


def test_normalize_listing_text_removes_yuan_symbol_suffix_but_keeps_model_digits():
    assert normalize_listing_text("980￥佳能ixus100 香槟色") == "佳能ixus100 香槟色"
    assert normalize_listing_text("980¥佳能ixus100 香槟色") == "佳能ixus100 香槟色"


def test_build_product_key_uses_same_key_for_same_media_price_drop():
    old = record("980💰佳能ixus100 香槟色 成色不错", 980)
    new = record("880💰佳能ixus100 香槟色 成色不错", 880)

    assert build_product_key(old).key == build_product_key(new).key
    assert build_product_key(old).reason == "wxid+media"


def test_build_product_key_ignores_media_url_order_and_duplicates():
    old = record(
        "980💰佳能ixus100 香槟色 成色不错",
        980,
        images=["https://img/b.jpg", "https://img/a.jpg", "https://img/a.jpg"],
    )
    new = record(
        "880💰佳能ixus100 香槟色 成色不错",
        880,
        images=["https://img/a.jpg", "https://img/b.jpg"],
    )

    assert build_product_key(old).key == build_product_key(new).key
    assert build_product_key(old).reason == "wxid+media"


def test_build_product_key_uses_model_and_price_free_text_without_media():
    old = record("980💰佳能ixus100 香槟色 成色不错", 980, images=[])
    new = record("880💰佳能ixus100 香槟色 成色不错", 880, images=[])

    assert build_product_key(old).key == build_product_key(new).key
    assert build_product_key(old).reason == "wxid+model+text_without_price"


def test_build_product_key_falls_back_when_model_or_text_missing_without_media():
    missing_model = record("980💰佳能ixus100 香槟色 成色不错", 980, images=[], model="")
    missing_text = record("", 980, images=[])

    assert build_product_key(missing_model).reason == "record_fallback"
    assert build_product_key(missing_text).reason == "record_fallback"
