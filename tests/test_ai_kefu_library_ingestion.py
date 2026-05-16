from __future__ import annotations

from pathlib import Path

from moments_inventory.ai_kefu.library_ingestion import ingest_library_bytes
from moments_inventory.ai_kefu.models import ProductRecord
from moments_inventory.exporter import HEADERS, _write_workbook


def _build_workbook_bytes(tmp_path: Path, filename: str, rows: list[list[str | int | None]]) -> bytes:
    workbook_path = tmp_path / filename
    _write_workbook(workbook_path, rows)
    return workbook_path.read_bytes()


def test_ingest_master_rule_bundle_splits_markdown_into_master_rule_and_faq_chunks():
    markdown_bytes = (
        "# 售前总规则\n\n"
        "客服先确认商品成色，再报价。\n\n"
        "## 常见问题\n\n"
        "Q：支持退货吗？\n"
        "A：按售后规则执行。\n"
    ).encode("utf-8")

    result = ingest_library_bytes(
        library_type="master_rule_bundle",
        filename="master-rule.md",
        payload=markdown_bytes,
        chunk_size=200,
        chunk_overlap=20,
    )

    assert [chunk.source_name for chunk in result.knowledge_chunks] == [
        "library:master_rule_bundle:faq",
        "library:master_rule_bundle:master_rule",
    ]
    assert [chunk.knowledge_tier for chunk in result.knowledge_chunks] == [
        "faq",
        "master_rule",
    ]
    assert result.imported_count == 2
    assert result.skipped_count == 0


def test_ingest_product_material_excel_builds_product_material_chunk(tmp_path: Path):
    workbook_bytes = _build_workbook_bytes(
        tmp_path,
        "product-material.xlsx",
        [
            ["型号", "素材类型", "素材链接", "备注"],
            ["佳能 IXUS 95", "视频", "https://cdn.example.com/video.mp4", "需先审片"],
        ],
    )

    result = ingest_library_bytes(
        library_type="product_material_excel",
        filename="product-material.xlsx",
        payload=workbook_bytes,
        chunk_size=200,
        chunk_overlap=20,
    )

    assert len(result.knowledge_chunks) == 1
    assert result.knowledge_chunks[0].knowledge_tier == "product_material"
    assert result.knowledge_chunks[0].tags == [
        "material:inspection_video",
        "佳能 IXUS 95",
        "视频",
    ]
    assert "素材类型：视频" in result.knowledge_chunks[0].text
    assert "文件线索：https://cdn.example.com/video.mp4" in result.knowledge_chunks[0].text
    assert result.imported_count == 1
    assert result.skipped_count == 0


def test_ingest_product_inventory_excel_parses_products_from_bytes(tmp_path: Path):
    workbook_bytes = _build_workbook_bytes(
        tmp_path,
        "inventory.xlsx",
        [
            HEADERS,
            [
                "佳能 ixus 95",
                850,
                "未售出",
                "老王",
                "wxid_supplier_a",
                "2026-05-01T10:00:00+08:00",
                "A12",
                "media/record-a/image-1.jpg",
                "media/record-a/video-1.mp4",
                "功能正常，成色不错，直接拍",
                "",
                "否",
            ],
        ],
    )

    result = ingest_library_bytes(
        library_type="product_inventory_excel",
        filename="inventory.xlsx",
        payload=workbook_bytes,
        chunk_size=200,
        chunk_overlap=20,
    )

    assert result.product_records == [
        ProductRecord(
            product_id="A12",
            source_record_id="A12",
            brand="佳能",
            model_std="ixus 95",
            sale_status="未售出",
            is_functional=True,
            has_inspection_video=True,
            has_sample_output=True,
            cost_price=850,
            sale_price=1030,
            profit_amount=180,
            source_name="老王",
            source_wxid="wxid_supplier_a",
            published_at="2026-05-01T10:00:00+08:00",
            image_path="media/record-a/image-1.jpg",
            video_path="media/record-a/video-1.mp4",
            raw_copy="功能正常，成色不错，直接拍",
            manual_review_needed=False,
        )
    ]
    assert len(result.knowledge_chunks) == 1
    assert result.knowledge_chunks[0].knowledge_tier == "product_material"
    assert result.knowledge_chunks[0].category == "商品素材"
    assert "验机视频" in result.knowledge_chunks[0].text
    assert "media/record-a/video-1.mp4" in result.knowledge_chunks[0].text
    assert result.imported_count == 1
    assert result.skipped_count == 0


def test_ingest_style_sample_markdown_builds_style_sample_chunk():
    markdown_bytes = "语气自然一点，像真人聊天。多用短句，别太像客服模板。".encode("utf-8")

    result = ingest_library_bytes(
        library_type="style_sample_md",
        filename="style.md",
        payload=markdown_bytes,
        chunk_size=80,
        chunk_overlap=10,
    )

    assert len(result.knowledge_chunks) == 1
    assert result.knowledge_chunks[0].knowledge_tier == "style_sample"
    assert result.knowledge_chunks[0].category == "回复风格"
    assert result.imported_count == 1
    assert result.skipped_count == 0
