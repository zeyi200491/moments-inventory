from datetime import datetime, timedelta

from moments_inventory.lifecycle import classify_lifecycle, merge_product_lifecycle
from moments_inventory.models import InventoryRecord
from moments_inventory.product_identity import build_product_key


def record(key: str, content: str, price: int | None, minutes: int = 0, images=None, wxid: str = "wxid_a"):
    return InventoryRecord(
        record_key=key,
        remark_name="卖家A",
        wxid=wxid,
        published_at=datetime.fromisoformat("2026-08-01T10:00:00+08:00") + timedelta(minutes=minutes),
        model="IXUS 100",
        price=price,
        serial_no=None,
        status="未售卖",
        image_urls=images if images is not None else ["https://img/a.jpg"],
        video_urls=[],
        content_text=content,
        source_moment_ids=[key],
    )


def test_classify_lifecycle_detects_sold_words():
    result = classify_lifecycle(record("m1", "佳能ixus100 980💰 已出", 980))

    assert result.status == "已售"
    assert "sold_keyword" in result.risk_flags


def test_classify_lifecycle_ignores_negated_or_non_status_sold_words():
    contents = [
        "不是已售 佳能ixus100 980💰",
        "未售出 佳能ixus100 980💰",
        "not sold, available 980💰 ixus100",
        "可下架包邮 佳能ixus100 980💰",
    ]

    for index, content in enumerate(contents):
        result = classify_lifecycle(record(f"m-neg-{index}", content, 980))

        assert result.status == "未售卖"
        assert result.lifecycle_status == "current"
        assert "sold_keyword" not in result.risk_flags


def test_merge_product_lifecycle_keeps_latest_price_for_price_drop():
    old = record("m1", "980💰佳能ixus100 香槟色", 980, minutes=0)
    new = record("m2", "880💰佳能ixus100 香槟色", 880, minutes=60 * 24 * 14)

    merged = merge_product_lifecycle([old, new])

    assert len(merged.current_records) == 1
    assert merged.current_records[0].price == 880
    assert merged.current_records[0].source_moment_ids == ["m1", "m2"]
    assert "price_drop_repost" in merged.current_records[0].risk_flags


def test_merge_product_lifecycle_routes_sold_record_to_review_not_current():
    sold = record("m1", "佳能ixus100 980💰 已售", 980)

    merged = merge_product_lifecycle([sold])

    assert merged.current_records == []
    assert merged.review_records[0].lifecycle_status == "sold"


def test_sold_or_unavailable_keywords_route_to_review_only():
    for keyword in ["下架", "没了", "卖掉", "sold"]:
        merged = merge_product_lifecycle([record(f"m-{keyword}", f"佳能ixus100 980💰 {keyword}", 980)])

        assert merged.current_records == []
        assert len(merged.review_records) == 1
        assert merged.review_records[0].status == "已售"
        assert "sold_keyword" in merged.review_records[0].risk_flags


def test_later_sold_repost_removes_whole_product_group_from_current():
    current = record("m1", "980💰佳能ixus100 香槟色", 980, minutes=0)
    sold = record("m2", "佳能ixus100 香槟色 已出", 980, minutes=60 * 24 * 7)

    merged = merge_product_lifecycle([current, sold])

    assert merged.current_records == []
    assert len(merged.review_records) == 1
    assert merged.review_records[0].record_key == "m2"
    assert merged.review_records[0].source_moment_ids == ["m1", "m2"]
    assert merged.review_records[0].lifecycle_status == "sold"


def test_no_media_sold_repost_uses_stable_text_identity_and_removes_current():
    current = record("m1", "980元 佳能ixus100 香槟色", 980, minutes=0, images=[])
    sold = record("m2", "佳能ixus100 香槟色 已出", 980, minutes=60 * 24 * 7, images=[])

    merged = merge_product_lifecycle([current, sold])

    assert merged.current_records == []
    assert len(merged.review_records) == 1
    assert merged.review_records[0].record_key == "m2"
    assert merged.review_records[0].source_moment_ids == ["m1", "m2"]
    assert current.product_key == sold.product_key
    assert current.fingerprint_reason == "wxid+model+text_without_price_lifecycle"
    assert sold.fingerprint_reason == "wxid+model+text_without_price_lifecycle"


def test_merge_uses_existing_product_key_before_building_product_key():
    old = record("m1", "980💰佳能ixus100 香槟色", 980, minutes=0, images=["https://img/a.jpg"])
    new = record("m2", "880💰另一台相机 黑色", 880, minutes=30, images=["https://img/b.jpg"])
    old.product_key = "manual:ixus100-a"
    new.product_key = "manual:ixus100-a"
    old.fingerprint_reason = "manual"
    new.fingerprint_reason = "manual"

    merged = merge_product_lifecycle([old, new])

    assert len(merged.current_records) == 1
    assert merged.current_records[0].product_key == "manual:ixus100-a"
    assert merged.current_records[0].fingerprint_reason == "manual"
    assert merged.current_records[0].source_moment_ids == ["m1", "m2"]


def test_merge_builds_product_key_when_missing():
    old = record("m1", "980💰佳能ixus100 香槟色", 980, minutes=0)
    new = record("m2", "880💰佳能ixus100 香槟色", 880, minutes=30)
    expected = build_product_key(old)

    merged = merge_product_lifecycle([old, new])

    assert len(merged.current_records) == 1
    assert old.product_key == expected.key
    assert old.fingerprint_reason == expected.reason
    assert new.product_key == expected.key
    assert new.fingerprint_reason == expected.reason


def test_price_increase_repost_uses_price_changed_risk_flag():
    old = record("m1", "880💰佳能ixus100 香槟色", 880, minutes=0)
    new = record("m2", "980💰佳能ixus100 香槟色", 980, minutes=60)

    merged = merge_product_lifecycle([old, new])

    assert len(merged.current_records) == 1
    assert merged.current_records[0].price == 980
    assert "price_changed_repost" in merged.current_records[0].risk_flags
    assert "price_drop_repost" not in merged.current_records[0].risk_flags


def test_same_image_from_different_wxid_does_not_merge():
    seller_a = record("m1", "980💰佳能ixus100 香槟色", 980, images=["https://img/shared.jpg"], wxid="wxid_a")
    seller_b = record("m2", "980💰佳能ixus100 香槟色", 980, images=["https://img/shared.jpg"], wxid="wxid_b")

    merged = merge_product_lifecycle([seller_a, seller_b])

    assert len(merged.current_records) == 2
    assert {item.wxid for item in merged.current_records} == {"wxid_a", "wxid_b"}


def test_merge_deduplicates_media_and_records_price_history_in_time_order():
    old = record("m1", "980💰佳能ixus100 香槟色", 980, minutes=0, images=["b.jpg", "a.jpg"])
    old.video_urls = ["v2.mp4", "v1.mp4"]
    new = record("m2", "880💰佳能ixus100 香槟色", 880, minutes=60, images=["a.jpg", "c.jpg"])
    new.video_urls = ["v1.mp4"]
    old.product_key = "manual:merge-media"
    new.product_key = "manual:merge-media"

    merged = merge_product_lifecycle([new, old], observed_at="2026-08-28T10:00:00+08:00")

    current = merged.current_records[0]
    assert current.image_urls == ["a.jpg", "b.jpg", "c.jpg"]
    assert current.video_urls == ["v1.mp4", "v2.mp4"]
    assert current.price_history == [
        "2026-08-01T10:00:00+08:00|980",
        "2026-08-01T11:00:00+08:00|880",
    ]
    assert current.last_seen_at == "2026-08-28T10:00:00+08:00"
    assert current.lifecycle_status == "current"
