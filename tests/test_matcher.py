from datetime import datetime, timedelta

from moments_inventory.matcher import deduplicate_and_merge
from moments_inventory.models import RawMoment


def test_deduplicate_same_content_keeps_one_record():
    published_at = datetime.fromisoformat("2026-04-20T10:00:00+08:00")
    moments = [
        RawMoment("1", "user", "wxid_123", published_at, "ixus 95 850 A12", ["a.jpg"], []),
        RawMoment(
            "2",
            "user",
            "wxid_123",
            published_at + timedelta(minutes=3),
            "ixus 95 850 A12",
            ["b.jpg"],
            [],
        ),
    ]

    records = deduplicate_and_merge(moments, ["ixus 95"])

    assert len(records) == 1
    assert sorted(records[0].image_urls) == ["a.jpg", "b.jpg"]


def test_merge_adjacent_complementary_moments():
    published_at = datetime.fromisoformat("2026-04-20T10:00:00+08:00")
    moments = [
        RawMoment("1", "user", "wxid_123", published_at, "ixus 95 850", ["a.jpg"], []),
        RawMoment(
            "2",
            "user",
            "wxid_123",
            published_at + timedelta(minutes=10),
            "A12 video",
            [],
            ["video.mp4"],
        ),
    ]

    records = deduplicate_and_merge(moments, ["ixus 95"])

    assert len(records) == 1
    assert records[0].serial_no == "A12"
    assert records[0].video_urls == ["video.mp4"]
    assert records[0].needs_manual is False


def test_merge_model_only_post_with_followup_detail_post():
    published_at = datetime.fromisoformat("2026-04-20T10:00:00+08:00")
    moments = [
        RawMoment("1", "user", "wxid_123", published_at, "z57", ["a.jpg"], []),
        RawMoment(
            "2",
            "user",
            "wxid_123",
            published_at + timedelta(seconds=20),
            "338 z57 detail",
            ["b.jpg"],
            [],
        ),
    ]

    records = deduplicate_and_merge(moments, ["z57"])

    assert len(records) == 1
    assert records[0].model == "z57"
    assert records[0].price == 338
    assert sorted(records[0].image_urls) == ["a.jpg", "b.jpg"]


def test_same_model_posts_merge_when_within_one_hour():
    published_at = datetime.fromisoformat("2026-04-20T10:00:00+08:00")
    moments = [
        RawMoment("1", "user", "wxid_123", published_at, "x31", ["a.jpg"], []),
        RawMoment(
            "2",
            "user",
            "wxid_123",
            published_at + timedelta(minutes=45),
            "228 x31 detail",
            ["b.jpg"],
            [],
        ),
    ]

    records = deduplicate_and_merge(moments, ["x31"])

    assert len(records) == 1
    assert records[0].model == "x31"
    assert records[0].price == 228
    assert sorted(records[0].image_urls) == ["a.jpg", "b.jpg"]


def test_same_model_stub_and_detail_merge_within_extended_window():
    published_at = datetime.fromisoformat("2026-04-27T20:19:24+08:00")
    moments = [
        RawMoment(
            "1",
            "user",
            "wxid_demo",
            published_at,
            "858 wx300 detail",
            ["a.jpg"],
            [],
        ),
        RawMoment(
            "2",
            "user",
            "wxid_demo",
            published_at + timedelta(minutes=17, seconds=27),
            "wx300",
            [],
            ["video.mp4"],
        ),
    ]

    records = deduplicate_and_merge(moments, ["wx300"])

    assert len(records) == 1
    assert records[0].model == "wx300"
    assert records[0].price == 858
    assert records[0].video_urls == ["video.mp4"]


def test_same_model_stub_and_detail_do_not_merge_when_over_one_hour():
    published_at = datetime.fromisoformat("2026-04-20T10:00:00+08:00")
    moments = [
        RawMoment("1", "user", "wxid_123", published_at, "x31", ["a.jpg"], []),
        RawMoment(
            "2",
            "user",
            "wxid_123",
            published_at + timedelta(minutes=61),
            "228 x31 detail",
            ["b.jpg"],
            [],
        ),
    ]

    records = deduplicate_and_merge(moments, ["x31"])

    assert len(records) == 2
