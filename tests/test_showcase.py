import json
from pathlib import Path

from moments_inventory.ai_kefu.products import read_xlsx_rows_from_bytes
from moments_inventory.exporter import _write_workbook
from moments_inventory.showcase import build_showcase_site
from moments_inventory.showcase import SHOWCASE_HEADERS, merge_showcase_workbook
from moments_inventory.showcase import normalize_showcase_model_key


SOURCE_HEADERS = [
    "型号",
    "价格",
    "状态",
    "备注名",
    "备注名wxid",
    "发布时间",
    "序列号",
    "图片路径",
    "视频路径",
    "原文文案",
    "备注",
    "是否需要人工复核",
]


def _rows(path: Path) -> list[list[object]]:
    return read_xlsx_rows_from_bytes(path.read_bytes())


def test_normalize_showcase_model_key_collapses_spacing_and_brand_aliases() -> None:
    assert normalize_showcase_model_key("三星 A40") == "三星a40"
    assert normalize_showcase_model_key("samsung-a40") == "三星a40"
    assert normalize_showcase_model_key("佳能 IXUS 95") == "佳能ixus95"
    assert normalize_showcase_model_key("Canon_ixus95") == "佳能ixus95"


def test_merge_showcase_workbook_creates_manual_sheet(tmp_path: Path) -> None:
    source = tmp_path / "全量当前库.xlsx"
    manual = tmp_path / "客户展示库存.xlsx"
    _write_workbook(
        source,
        [
            SOURCE_HEADERS,
            [
                "三星a40",
                99,
                "未售卖",
                "晨曦",
                "wxid_1",
                "2026-07-15T20:25:55+08:00",
                "8820",
                "media/r1/image-1.jpg",
                "",
                "99💰三星A40 特价",
                "",
                "否",
            ],
        ],
    )

    result = merge_showcase_workbook(source, manual)

    rows = _rows(result)
    assert rows[0] == SHOWCASE_HEADERS
    assert rows[1][1] == "三星a40"
    assert rows[1][2] == "三星"
    assert rows[1][3] == 99
    assert rows[1][4] == 99
    assert rows[1][5] == "是"
    assert rows[1][8] == "99💰三星A40 特价"
    assert rows[1][9] == "99💰三星A40 特价"
    assert rows[1][10] == "media/r1/image-1.jpg"
    assert rows[1][12] == "三星a40"


def test_merge_showcase_workbook_preserves_manual_overrides(tmp_path: Path) -> None:
    source = tmp_path / "全量当前库.xlsx"
    manual = tmp_path / "客户展示库存.xlsx"
    _write_workbook(
        source,
        [
            SOURCE_HEADERS,
            [
                "三星a40",
                99,
                "未售卖",
                "晨曦",
                "wxid_1",
                "2026-07-15T20:25:55+08:00",
                "8820",
                "media/r1/image-1.jpg",
                "",
                "原文新版",
                "",
                "否",
            ],
        ],
    )
    _write_workbook(
        manual,
        [
            SHOWCASE_HEADERS,
            [
                "wxid_1|2026-07-15T20:25:55+08:00|8820",
                "三星a40",
                "三星",
                99,
                168,
                "否",
                "2026-07-15T20:25:55+08:00",
                "晨曦",
                "旧原文",
                "客户展示文案",
                "media/old/image.jpg",
                "media/old/video.mp4",
                "三星a40",
                "内部备注",
            ],
        ],
    )

    merge_showcase_workbook(source, manual)

    rows = _rows(manual)
    assert rows[1][3] == 99
    assert rows[1][4] == 168
    assert rows[1][5] == "否"
    assert rows[1][8] == "原文新版"
    assert rows[1][9] == "客户展示文案"
    assert rows[1][10] == "media/r1/image-1.jpg"
    assert rows[1][12] == "三星a40"
    assert rows[1][13] == "内部备注"


def test_build_showcase_site_filters_hidden_products_and_copies_assets(tmp_path: Path) -> None:
    manual = tmp_path / "manual.xlsx"
    image = tmp_path / "output" / "media" / "r1" / "image-1.jpg"
    image.parent.mkdir(parents=True)
    image.write_bytes(b"body")
    sample = tmp_path / "sample_assets" / "三星a40" / "sample-1.jpg"
    sample.parent.mkdir(parents=True)
    sample.write_bytes(b"sample")
    _write_workbook(
        manual,
        [
            SHOWCASE_HEADERS,
            [
                "p1",
                "三星a40",
                "三星",
                99,
                168,
                "是",
                "2026-07-15T20:25:55+08:00",
                "晨曦",
                "原文",
                "展示文案",
                "output/media/r1/image-1.jpg",
                "",
                "三星a40",
                "",
            ],
            [
                "p2",
                "索尼t70",
                "索尼",
                99,
                188,
                "否",
                "2026-07-16T20:25:55+08:00",
                "十一",
                "原文",
                "隐藏文案",
                "",
                "",
                "索尼t70",
                "",
            ],
        ],
    )

    result = build_showcase_site(
        manual,
        tmp_path / "sample_assets",
        tmp_path / "site_dist",
        workspace_root=tmp_path,
    )

    products = json.loads((result.output_dir / "products.json").read_text(encoding="utf-8"))
    assert [item["productId"] for item in products["products"]] == ["p1"]
    assert products["products"][0]["bodyImages"] == ["assets/body/p1/image-1.jpg"]
    assert products["products"][0]["sampleImages"] == ["assets/samples/三星a40/sample-1.jpg"]
    assert (result.output_dir / "assets" / "body" / "p1" / "image-1.jpg").read_bytes() == b"body"
    assert (result.output_dir / "assets" / "samples" / "三星a40" / "sample-1.jpg").read_bytes() == b"sample"
    assert result.missing_assets_path.exists()
