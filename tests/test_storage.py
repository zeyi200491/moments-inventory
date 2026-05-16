from datetime import datetime
from pathlib import Path
import shutil
import tempfile
import uuid

import pytest

from moments_inventory.models import InventoryRecord
from moments_inventory.storage import InventoryStore


PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _make_temp_root(prefix: str) -> Path:
    return Path(tempfile.mkdtemp(prefix=prefix))


def build_record(record_key: str, status: str = "未售出"):
    return InventoryRecord(
        record_key=record_key,
        remark_name="user-a",
        wxid="wxid_123",
        published_at=datetime.fromisoformat("2026-04-20T10:00:00+08:00"),
        model="ixus 95",
        price=850,
        serial_no="A12",
        status=status,
        image_urls=["a.jpg"],
        video_urls=[],
        content_text="ixus 95 850 A12",
        source_moment_ids=["sns_001"],
    )


def test_missing_record_from_latest_sync_is_deleted():
    temp_root = _make_temp_root(f"pytest-storage-{uuid.uuid4().hex}-")

    try:
        store = InventoryStore(temp_root / "inventory.db")
        store.initialize()
        store.upsert_records(
            [build_record("record-1")],
            fetched_moment_ids={"sns_001"},
            sync_started_at="2026-04-20T12:00:00+08:00",
        )
        store.upsert_records(
            [],
            fetched_moment_ids=set(),
            sync_started_at="2026-04-21T12:00:00+08:00",
        )

        records = store.list_all_records()

        assert records == []
        assert store.list_record_keys_by_image_url("a.jpg") == []
        assert store.list_record_keys_by_source_moment_id("sns_001") == []
    finally:
        shutil.rmtree(temp_root, ignore_errors=True)


def test_incomplete_snapshot_keeps_missing_records():
    temp_root = _make_temp_root(f"pytest-storage-partial-{uuid.uuid4().hex}-")

    try:
        store = InventoryStore(temp_root / "inventory.db")
        store.initialize()
        store.upsert_records(
            [build_record("record-1")],
            fetched_moment_ids={"sns_001"},
            sync_started_at="2026-04-20T12:00:00+08:00",
        )

        newer_record = InventoryRecord(
            record_key="record-2",
            remark_name="user-b",
            wxid="wxid_456",
            published_at=datetime.fromisoformat("2026-04-21T10:00:00+08:00"),
            model="wx300",
            price=900,
            serial_no="B22",
            status="active",
            image_urls=["b.jpg"],
            video_urls=[],
            content_text="wx300 900 B22",
            source_moment_ids=["sns_002"],
        )
        store.upsert_records(
            [newer_record],
            fetched_moment_ids={"sns_002"},
            sync_started_at="2026-04-21T12:00:00+08:00",
            snapshot_complete=False,
        )

        records = {record.record_key: record for record in store.list_all_records()}

        assert set(records) == {"record-1", "record-2"}
        assert store.list_record_keys_by_image_url("a.jpg") == ["record-1"]
        assert store.list_record_keys_by_source_moment_id("sns_001") == ["record-1"]
    finally:
        shutil.rmtree(temp_root, ignore_errors=True)


def test_subsumed_old_record_is_removed_after_merge():
    temp_root = _make_temp_root(f"pytest-storage-merge-{uuid.uuid4().hex}-")

    try:
        store = InventoryStore(temp_root / "inventory.db")
        store.initialize()

        old_detail = InventoryRecord(
            record_key="detail-record",
            remark_name="user-a",
            wxid="wxid_123",
            published_at=datetime.fromisoformat("2026-04-27T20:19:24+08:00"),
            model="wx300",
            price=858,
            serial_no=None,
            status="未售出",
            image_urls=["a.jpg"],
            video_urls=[],
            content_text="858 wx300 detail",
            source_moment_ids=["sns_detail"],
        )
        old_stub = InventoryRecord(
            record_key="stub-record",
            remark_name="user-a",
            wxid="wxid_123",
            published_at=datetime.fromisoformat("2026-04-27T20:36:51+08:00"),
            model="wx300",
            price=None,
            serial_no=None,
            status="未售出",
            image_urls=[],
            video_urls=["video.mp4"],
            content_text="wx300",
            source_moment_ids=["sns_stub"],
        )
        store.upsert_records(
            [old_detail, old_stub],
            fetched_moment_ids={"sns_detail", "sns_stub"},
            sync_started_at="2026-04-27T20:40:00+08:00",
        )

        merged_record = InventoryRecord(
            record_key="merged-record",
            remark_name="user-a",
            wxid="wxid_123",
            published_at=datetime.fromisoformat("2026-04-27T20:19:24+08:00"),
            model="wx300",
            price=858,
            serial_no=None,
            status="未售出",
            image_urls=["a.jpg"],
            video_urls=["video.mp4"],
            content_text="858 wx300 detail\nwx300",
            source_moment_ids=["sns_detail", "sns_stub"],
        )
        store.upsert_records(
            [merged_record],
            fetched_moment_ids={"sns_detail", "sns_stub"},
            sync_started_at="2026-04-27T20:50:00+08:00",
        )

        records = store.list_all_records()

        assert len(records) == 1
        assert records[0].record_key == "merged-record"
        assert records[0].video_urls == ["video.mp4"]
    finally:
        shutil.rmtree(temp_root, ignore_errors=True)


def test_store_supports_querying_records_by_media_and_source_ids():
    temp_root = _make_temp_root(f"pytest-storage-query-{uuid.uuid4().hex}-")

    try:
        store = InventoryStore(temp_root / "inventory.db")
        store.initialize()
        store.upsert_records(
            [
                InventoryRecord(
                    record_key="record-1",
                    remark_name="user-a",
                    wxid="wxid_123",
                    published_at=datetime.fromisoformat("2026-04-20T10:00:00+08:00"),
                    model="ixus 95",
                    price=850,
                    serial_no="A12",
                    status="未售出",
                    image_urls=["shared.jpg", "a.jpg"],
                    video_urls=["clip.mp4"],
                    content_text="ixus 95",
                    source_moment_ids=["sns_001", "sns_002"],
                )
            ],
            fetched_moment_ids={"sns_001", "sns_002"},
            sync_started_at="2026-04-20T12:00:00+08:00",
        )

        assert store.list_record_keys_by_image_url("shared.jpg") == ["record-1"]
        assert store.list_record_keys_by_video_url("clip.mp4") == ["record-1"]
        assert store.list_record_keys_by_source_moment_id("sns_002") == ["record-1"]
    finally:
        shutil.rmtree(temp_root, ignore_errors=True)


def test_store_rejects_unknown_detail_table_or_column():
    temp_root = _make_temp_root(f"pytest-storage-whitelist-{uuid.uuid4().hex}-")

    try:
        store = InventoryStore(temp_root / "inventory.db")
        store.initialize()

        with pytest.raises(ValueError):
            store._list_record_keys_by_detail(
                "record_images; drop table inventory_records; --",
                "url",
                "x",
            )

        with pytest.raises(ValueError):
            store._list_record_keys_by_detail(
                "record_images",
                "url; drop table inventory_records; --",
                "x",
            )
    finally:
        shutil.rmtree(temp_root, ignore_errors=True)
