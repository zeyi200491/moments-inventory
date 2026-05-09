from __future__ import annotations

from pathlib import Path

import yaml

import moments_inventory.cli as cli_module
from moments_inventory.ai_kefu.products import (
    ProductRecord,
    import_products_from_xlsx,
)
from moments_inventory.ai_kefu.indexing import split_document_to_chunks
from moments_inventory.ai_kefu.storage import SQLiteKefuRepository
from moments_inventory.exporter import HEADERS, _write_workbook


def _build_products_workbook(workbook_path: Path) -> Path:
    rows = [
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
        [
            "索尼 W530",
            520,
            "未售卖",
            "老李",
            "wxid_supplier_b",
            "2026-05-02T12:30:00+08:00",
            "B08",
            "",
            "",
            "成色一般，需自测",
            "",
            "是",
        ],
    ]
    _write_workbook(workbook_path, rows)
    return workbook_path


def test_import_products_from_xlsx_extracts_minimum_structured_fields(tmp_path: Path):
    workbook_path = _build_products_workbook(tmp_path / "当前在售库.xlsx")

    products = import_products_from_xlsx(workbook_path)

    assert products == [
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
        ),
        ProductRecord(
            product_id="B08",
            source_record_id="B08",
            brand="索尼",
            model_std="W530",
            sale_status="未售卖",
            is_functional=False,
            has_inspection_video=False,
            has_sample_output=False,
            cost_price=520,
            sale_price=670,
            profit_amount=150,
            source_name="老李",
            source_wxid="wxid_supplier_b",
            published_at="2026-05-02T12:30:00+08:00",
            image_path="",
            video_path="",
            raw_copy="成色一般，需自测",
            manual_review_needed=True,
        ),
    ]


def test_import_products_from_xlsx_keeps_duplicate_models_as_separate_products(tmp_path: Path):
    workbook_path = tmp_path / "当前在售库.xlsx"
    _write_workbook(
        workbook_path,
        [
            HEADERS,
            [
                "富士 201",
                300,
                "未售卖",
                "老王",
                "wxid_supplier_a",
                "2026-05-01T10:00:00+08:00",
                "",
                "",
                "",
                "功能正常",
                "",
                "否",
            ],
            [
                "富士 201",
                320,
                "未售卖",
                "老王",
                "wxid_supplier_a",
                "2026-05-01T11:00:00+08:00",
                "",
                "",
                "",
                "功能正常",
                "",
                "否",
            ],
        ],
    )

    products = import_products_from_xlsx(workbook_path)

    assert len(products) == 2
    assert products[0].source_record_id == "富士 201"
    assert products[1].source_record_id == "富士 201"
    assert products[0].product_id != products[1].product_id


def test_sqlite_kefu_repository_can_persist_products(tmp_path: Path):
    repository = SQLiteKefuRepository(tmp_path / "ai-kefu.db")
    repository.save_products(
        [
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
    )

    assert repository.list_products() == [
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


def test_build_parser_supports_import_products_command():
    parser = cli_module.build_parser()

    args = parser.parse_args(
        [
            "import-products",
            "--xlsx",
            "config/output/当前在售库.xlsx",
            "--ai-kefu-config",
            "config/ai_kefu.yaml",
        ]
    )

    assert args.command == "import-products"
    assert args.xlsx == "config/output/当前在售库.xlsx"
    assert args.ai_kefu_config == "config/ai_kefu.yaml"


def test_build_parser_supports_import_knowledge_command():
    parser = cli_module.build_parser()

    args = parser.parse_args(
        [
            "import-knowledge",
            "--file",
            "data/shipping_rules.md",
            "--category",
            "供应链发货",
            "--tier",
            "shipping_info",
            "--tags",
            "supplier:老王,深圳仓",
            "--ai-kefu-config",
            "config/ai_kefu.yaml",
        ]
    )

    assert args.command == "import-knowledge"
    assert args.file == "data/shipping_rules.md"
    assert args.category == "供应链发货"
    assert args.tier == "shipping_info"
    assert args.tags == "supplier:老王,深圳仓"
    assert args.ai_kefu_config == "config/ai_kefu.yaml"


def test_cli_import_products_loads_xlsx_into_ai_kefu_database(tmp_path: Path):
    workbook_path = _build_products_workbook(tmp_path / "当前在售库.xlsx")
    config_path = tmp_path / "ai_kefu.yaml"
    config_path.write_text(
        yaml.safe_dump(
            {
                "workspace_dir": "./workspace",
                "database_path": "./data/ai-kefu.db",
                "embedding_provider": "openai",
                "chat_provider": "openai_compatible",
                "chat_model": "gpt-4.1-mini",
                "chat_provider_options": {
                    "api_base": "https://example.com/v1",
                    "api_key_env": "AI_KEFU_OPENAI_API_KEY",
                },
                "retrieval": {
                    "chunk_size": 300,
                    "chunk_overlap": 30,
                },
            },
            allow_unicode=True,
        ),
        encoding="utf-8",
    )

    result = cli_module.main(
        [
            "import-products",
            "--xlsx",
            str(workbook_path),
            "--ai-kefu-config",
            str(config_path),
        ]
    )

    repository = SQLiteKefuRepository(tmp_path / "data" / "ai-kefu.db")

    assert result == 0
    assert [product.product_id for product in repository.list_products()] == ["A12", "B08"]


def test_cli_import_knowledge_loads_text_into_ai_kefu_database(tmp_path: Path):
    knowledge_file = tmp_path / "shipping_rules.md"
    knowledge_file.write_text("深圳仓现货通常 24 小时内发出。", encoding="utf-8")
    config_path = tmp_path / "ai_kefu.yaml"
    config_path.write_text(
        yaml.safe_dump(
            {
                "workspace_dir": "./workspace",
                "database_path": "./data/ai-kefu.db",
                "embedding_provider": "openai",
                "chat_provider": "openai_compatible",
                "chat_model": "gpt-4.1-mini",
                "chat_provider_options": {
                    "api_base": "https://example.com/v1",
                    "api_key_env": "AI_KEFU_OPENAI_API_KEY",
                },
                "retrieval": {
                    "chunk_size": 300,
                    "chunk_overlap": 30,
                },
            },
            allow_unicode=True,
        ),
        encoding="utf-8",
    )

    result = cli_module.main(
        [
            "import-knowledge",
            "--file",
            str(knowledge_file),
            "--category",
            "供应链发货",
            "--tier",
            "shipping_info",
            "--tags",
            "supplier:老王,深圳仓",
            "--ai-kefu-config",
            str(config_path),
        ]
    )

    repository = SQLiteKefuRepository(tmp_path / "data" / "ai-kefu.db")
    chunks = repository.list_knowledge_chunks()
    expected_chunks = split_document_to_chunks(
        source_name=knowledge_file.name,
        category="供应链发货",
        text="深圳仓现货通常 24 小时内发出。",
        chunk_size=300,
        chunk_overlap=30,
    )

    assert result == 0
    assert len(chunks) == len(expected_chunks)
    assert [chunk.knowledge_tier for chunk in chunks] == ["shipping_info"]
    assert [chunk.tags for chunk in chunks] == [["supplier:老王", "深圳仓"]]
