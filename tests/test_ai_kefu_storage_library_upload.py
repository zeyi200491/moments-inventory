from __future__ import annotations

from pathlib import Path

import pytest

from moments_inventory.ai_kefu.models import LibraryStateRecord, ProductRecord
from moments_inventory.ai_kefu.storage import SQLiteKefuRepository


def test_sqlite_kefu_repository_apply_library_upload_rolls_back_on_failure(tmp_path: Path):
    class FailingLibraryUploadRepository(SQLiteKefuRepository):
        def _before_commit_library_upload(self) -> None:
            raise RuntimeError("boom")

    repository = FailingLibraryUploadRepository(tmp_path / "ai-kefu.db")
    old_product = ProductRecord(
        product_id="legacy-1",
        source_record_id="legacy-1",
        brand="Canon",
        model_std="IXUS 95",
        sale_status="在售",
        is_functional=True,
        has_inspection_video=False,
        has_sample_output=False,
        cost_price=500,
        sale_price=650,
        profit_amount=150,
        source_name="legacy",
        source_wxid="wxid-legacy",
        published_at="2026-05-15T10:00:00+08:00",
        image_path="",
        video_path="",
        raw_copy="legacy",
        manual_review_needed=False,
    )
    old_state = LibraryStateRecord(
        library_type="product_inventory_excel",
        source_name="library:product_inventory_excel",
        original_filename="legacy.xlsx",
        imported_count=1,
        skipped_count=0,
        status="active",
        uploaded_at="2026-05-15T10:00:00+08:00",
    )
    repository.save_products([old_product])
    repository.save_library_state(old_state)

    with pytest.raises(RuntimeError, match="boom"):
        repository.apply_library_upload(
            source_name="library:product_inventory_excel",
            knowledge_chunks=[],
            product_records=[],
            library_state=LibraryStateRecord(
                library_type="product_inventory_excel",
                source_name="library:product_inventory_excel",
                original_filename="new.xlsx",
                imported_count=0,
                skipped_count=0,
                status="active",
                uploaded_at="2026-05-15T12:00:00+08:00",
            ),
        )

    assert repository.list_products() == [old_product]
    assert repository.get_library_state("product_inventory_excel") == old_state
