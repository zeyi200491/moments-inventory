from datetime import datetime, timedelta

from moments_inventory.model_catalog import ModelCatalogAlias, ModelCatalogIndex
from moments_inventory.model_matcher import ModelMatcher
from moments_inventory.matcher import deduplicate_and_merge
from moments_inventory.models import RawMoment
from moments_inventory.product_identity import build_product_key


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


def test_deduplicate_and_merge_uses_catalog_model_matcher():
    published_at = datetime.fromisoformat("2026-04-20T10:00:00+08:00")
    matcher = ModelMatcher(
        ModelCatalogIndex(
            version=1,
            models=[],
            aliases_by_key={
                "索尼wx300": [
                    ModelCatalogAlias(
                        alias="索尼WX300",
                        normalized_key="索尼wx300",
                        brand="索尼",
                        brand_en="Sony",
                        canonical_model="DSC-WX300",
                        safe=True,
                        ambiguous=False,
                        source_row=4,
                    )
                ]
            },
        )
    )
    moments = [
        RawMoment(
            "1",
            "user",
            "wxid_123",
            published_at,
            "索尼wx300 858💰 编号H12",
            ["a.jpg"],
            [],
        )
    ]

    records = deduplicate_and_merge(moments, [], model_matcher=matcher)

    assert len(records) == 1
    assert records[0].model == "DSC-WX300"
    assert records[0].price == 858
    assert records[0].serial_no == "H12"


def test_deduplicate_and_merge_sets_product_key_for_price_drop_identity():
    published_at = datetime.fromisoformat("2026-08-01T10:00:00+08:00")
    records = deduplicate_and_merge(
        [
            RawMoment(
                "m1",
                "user",
                "wxid_123",
                published_at,
                "980💰佳能ixus100 香槟色",
                ["a.jpg"],
                [],
            ),
            RawMoment(
                "m2",
                "user",
                "wxid_123",
                published_at + timedelta(days=14),
                "880💰佳能ixus100 香槟色",
                ["a.jpg"],
                [],
            ),
        ],
        ["佳能ixus100"],
    )

    assert len(records) == 2
    assert records[0].product_key == records[1].product_key
    assert records[0].fingerprint_reason == "wxid+media"


def test_deduplicate_and_merge_sets_product_key_for_price_drop_without_media():
    published_at = datetime.fromisoformat("2026-08-01T10:00:00+08:00")
    records = deduplicate_and_merge(
        [
            RawMoment(
                "m1",
                "user",
                "wxid_123",
                published_at,
                "980💰佳能ixus100 香槟色",
                [],
                [],
            ),
            RawMoment(
                "m2",
                "user",
                "wxid_123",
                published_at + timedelta(days=14),
                "880💰佳能ixus100 香槟色",
                [],
                [],
            ),
        ],
        ["佳能ixus100"],
    )

    assert len(records) == 2
    assert records[0].product_key == records[1].product_key
    assert records[0].fingerprint_reason == "wxid+model+text_without_price"


def test_adjacent_merge_refreshes_product_key_after_adding_video_media():
    published_at = datetime.fromisoformat("2026-04-20T10:00:00+08:00")
    records = deduplicate_and_merge(
        [
            RawMoment(
                "1",
                "user",
                "wxid_123",
                published_at,
                "ixus 95 850",
                ["a.jpg"],
                [],
            ),
            RawMoment(
                "2",
                "user",
                "wxid_123",
                published_at + timedelta(minutes=10),
                "A12 video",
                [],
                ["video.mp4"],
            ),
        ],
        ["ixus 95"],
    )

    assert len(records) == 1
    identity = build_product_key(records[0])
    assert records[0].product_key == identity.key
    assert records[0].fingerprint_reason == "wxid+media"


def test_adjacent_merge_refreshes_product_key_after_content_text_changes_without_media():
    published_at = datetime.fromisoformat("2026-04-20T10:00:00+08:00")
    records = deduplicate_and_merge(
        [
            RawMoment(
                "1",
                "user",
                "wxid_123",
                published_at,
                "ixus 95 850",
                [],
                [],
            ),
            RawMoment(
                "2",
                "user",
                "wxid_123",
                published_at + timedelta(minutes=10),
                "A12 detail",
                [],
                [],
            ),
        ],
        ["ixus 95"],
    )

    assert len(records) == 1
    identity = build_product_key(records[0])
    assert records[0].product_key == identity.key
    assert records[0].fingerprint_reason == "wxid+model+text_without_price"


def test_deduplicate_and_merge_drops_multi_model_sale_listing():
    published_at = datetime.fromisoformat("2026-08-01T10:00:00+08:00")
    records = deduplicate_and_merge(
        [
            RawMoment(
                "m1",
                "user",
                "wxid_123",
                published_at,
                "ixus100 980💰，wx300 880💰，z57 520💰",
                ["multi.jpg"],
                [],
            )
        ],
        ["ixus100", "wx300", "z57"],
    )

    assert records == []


def test_deduplicate_and_merge_keeps_reference_model_listing():
    published_at = datetime.fromisoformat("2026-08-01T10:00:00+08:00")
    matcher = ModelMatcher(
        ModelCatalogIndex(
            version=1,
            models=[],
            aliases_by_key={
                "佳能ixus100": [
                    ModelCatalogAlias(
                        alias="佳能ixus100",
                        normalized_key="佳能ixus100",
                        brand="佳能",
                        brand_en="Canon",
                        canonical_model="IXUS 100",
                        safe=True,
                        ambiguous=False,
                        source_row=1,
                    )
                ],
                "佳能ixus130": [
                    ModelCatalogAlias(
                        alias="佳能ixus130",
                        normalized_key="佳能ixus130",
                        brand="佳能",
                        brand_en="Canon",
                        canonical_model="IXUS 130",
                        safe=True,
                        ambiguous=False,
                        source_row=2,
                    )
                ],
            },
        )
    )

    records = deduplicate_and_merge(
        [
            RawMoment(
                "m1",
                "user",
                "wxid_123",
                published_at,
                "980💰佳能ixus100 香槟色 平替佳能ixus130",
                ["a.jpg"],
                [],
            )
        ],
        [],
        model_matcher=matcher,
    )

    assert len(records) == 1
    assert records[0].model == "IXUS 100"
    assert "reference_model" in records[0].risk_flags
