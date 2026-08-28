from datetime import datetime
from pathlib import Path
import sqlite3
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


def test_stage_records_are_isolated_by_run_id():
    temp_root = _make_temp_root(f"pytest-storage-staging-{uuid.uuid4().hex}-")

    try:
        store = InventoryStore(temp_root / "inventory.db")
        store.initialize()

        run_one_record = build_record("record-1")
        run_two_record = build_record("record-1", status="已售出")

        store.stage_records("run-1", 0, [run_one_record])
        store.stage_records("run-2", 1, [run_two_record])

        run_one_records = store.list_staged_records("run-1")
        run_two_records = store.list_staged_records("run-2")

        assert len(run_one_records) == 1
        assert run_one_records[0].record_key == "record-1"
        assert run_one_records[0].status == build_record("record-1").status

        assert len(run_two_records) == 1
        assert run_two_records[0].record_key == "record-1"
        assert run_two_records[0].status == "已售出"
    finally:
        shutil.rmtree(temp_root, ignore_errors=True)


def test_store_persists_product_lifecycle_fields():
    temp_root = _make_temp_root(f"pytest-storage-lifecycle-{uuid.uuid4().hex}-")
    try:
        store = InventoryStore(temp_root / "inventory.db")
        record = build_record("record-life")
        record.product_key = "media:abc"
        record.fingerprint_reason = "wxid+media"
        record.lifecycle_status = "current"
        record.risk_flags = ["price_drop_repost"]
        record.price_history = ["2026-08-01T10:00:00+08:00|980", "2026-08-15T10:00:00+08:00|880"]
        record.last_seen_at = "2026-08-28T10:00:00+08:00"

        store.upsert_records(
            [record],
            fetched_moment_ids={"sns_001"},
            sync_started_at="2026-08-28T10:00:00+08:00",
        )

        loaded = store.list_all_records()[0]
        assert loaded.product_key == "media:abc"
        assert loaded.fingerprint_reason == "wxid+media"
        assert loaded.lifecycle_status == "current"
        assert loaded.risk_flags == ["price_drop_repost"]
        assert loaded.price_history[-1].endswith("|880")
        assert loaded.last_seen_at == "2026-08-28T10:00:00+08:00"
    finally:
        shutil.rmtree(temp_root, ignore_errors=True)


def test_store_preserves_empty_lifecycle_last_seen_metadata():
    temp_root = _make_temp_root(f"pytest-storage-lifecycle-empty-{uuid.uuid4().hex}-")
    try:
        store = InventoryStore(temp_root / "inventory.db")

        upserted_record = build_record("record-life-empty-upsert")
        assert upserted_record.last_seen_at is None
        store.upsert_records(
            [upserted_record],
            fetched_moment_ids={"sns_001"},
            sync_started_at="2026-08-28T10:00:00+08:00",
        )

        loaded = store.list_all_records()[0]
        assert loaded.last_seen_at is None

        staged_record = build_record("record-life-empty-stage")
        assert staged_record.last_seen_at is None
        store.stage_records("run-empty-last-seen", 0, [staged_record])
        store.replace_current_records_from_stage(
            "run-empty-last-seen",
            committed_at="2026-08-28T11:00:00+08:00",
        )

        loaded_after_stage = store.list_all_records()[0]
        assert loaded_after_stage.record_key == "record-life-empty-stage"
        assert loaded_after_stage.last_seen_at is None
    finally:
        shutil.rmtree(temp_root, ignore_errors=True)


def test_store_keeps_unmatched_model_review_records():
    temp_root = _make_temp_root(f"pytest-storage-unmatched-review-{uuid.uuid4().hex}-")
    try:
        store = InventoryStore(temp_root / "inventory.db")
        record = build_record("unmatched-review")
        record.model = None
        record.risk_flags = ["unmatched_model"]

        store.upsert_records(
            [record],
            fetched_moment_ids={"sns_001"},
            sync_started_at="2026-08-28T10:00:00+08:00",
        )

        loaded = store.list_all_records()
        assert len(loaded) == 1
        assert loaded[0].model is None
        assert loaded[0].risk_flags == ["unmatched_model"]
    finally:
        shutil.rmtree(temp_root, ignore_errors=True)


def test_store_migrates_legacy_last_seen_constraint_to_allow_empty_lifecycle_metadata():
    temp_root = _make_temp_root(f"pytest-storage-legacy-last-seen-{uuid.uuid4().hex}-")
    try:
        db_path = temp_root / "inventory.db"
        with sqlite3.connect(db_path) as conn:
            conn.execute(
                """
                create table inventory_records (
                  record_key text primary key,
                  remark_name text,
                  wxid text,
                  published_at text not null,
                  model text,
                  price integer,
                  serial_no text,
                  status text not null,
                  image_urls text not null,
                  video_urls text not null,
                  content_text text not null,
                  note text not null,
                  needs_manual integer not null,
                  source_moment_ids text not null,
                  first_seen_at text not null,
                  last_seen_at text not null
                )
                """
            )

        store = InventoryStore(db_path)
        record = build_record("record-legacy-empty-last-seen")
        assert record.last_seen_at is None
        store.upsert_records(
            [record],
            fetched_moment_ids={"sns_001"},
            sync_started_at="2026-08-28T10:00:00+08:00",
        )

        loaded = store.list_all_records()[0]
        assert loaded.last_seen_at is None
    finally:
        shutil.rmtree(temp_root, ignore_errors=True)


def test_store_reads_invalid_lifecycle_json_lists_as_empty_lists():
    temp_root = _make_temp_root(f"pytest-storage-invalid-lifecycle-json-{uuid.uuid4().hex}-")
    try:
        store = InventoryStore(temp_root / "inventory.db")

        record = build_record("record-invalid-lifecycle-json")
        record.risk_flags = ["price_drop_repost"]
        record.price_history = ["2026-08-15T10:00:00+08:00|880"]
        store.upsert_records(
            [record],
            fetched_moment_ids={"sns_001"},
            sync_started_at="2026-08-28T10:00:00+08:00",
        )
        store.stage_records("run-invalid-lifecycle-json", 0, [record])

        with sqlite3.connect(temp_root / "inventory.db") as conn:
            conn.execute(
                """
                update inventory_records
                set risk_flags = '', price_history = '{bad-json'
                where record_key = ?
                """,
                (record.record_key,),
            )
            conn.execute(
                """
                update inventory_staging_records
                set risk_flags = '[bad-json', price_history = ''
                where run_id = ? and record_key = ?
                """,
                ("run-invalid-lifecycle-json", record.record_key),
            )

        loaded = store.list_all_records()[0]
        assert loaded.risk_flags == []
        assert loaded.price_history == []

        staged = store.list_staged_records("run-invalid-lifecycle-json")[0]
        assert staged.risk_flags == []
        assert staged.price_history == []
    finally:
        shutil.rmtree(temp_root, ignore_errors=True)


def test_stage_replace_round_trips_product_lifecycle_fields():
    temp_root = _make_temp_root(f"pytest-storage-stage-lifecycle-{uuid.uuid4().hex}-")
    try:
        store = InventoryStore(temp_root / "inventory.db")
        record = build_record("record-stage-life")
        record.product_key = "media:stage"
        record.fingerprint_reason = "wxid+stage-media"
        record.lifecycle_status = "stale"
        record.risk_flags = ["price_drop_repost", "missing_recent_media"]
        record.price_history = ["2026-08-01T10:00:00+08:00|980", "2026-08-28T10:00:00+08:00|780"]
        record.last_seen_at = "2026-08-28T10:00:00+08:00"

        store.stage_records("run-stage-life", 0, [record])
        staged = store.list_staged_records("run-stage-life")[0]
        assert staged.product_key == "media:stage"
        assert staged.fingerprint_reason == "wxid+stage-media"
        assert staged.lifecycle_status == "stale"
        assert staged.risk_flags == ["price_drop_repost", "missing_recent_media"]
        assert staged.price_history == ["2026-08-01T10:00:00+08:00|980", "2026-08-28T10:00:00+08:00|780"]
        assert staged.last_seen_at == "2026-08-28T10:00:00+08:00"

        store.replace_current_records_from_stage(
            "run-stage-life",
            committed_at="2026-08-28T11:00:00+08:00",
        )

        loaded = store.list_all_records()[0]
        assert loaded.product_key == "media:stage"
        assert loaded.fingerprint_reason == "wxid+stage-media"
        assert loaded.lifecycle_status == "stale"
        assert loaded.risk_flags == ["price_drop_repost", "missing_recent_media"]
        assert loaded.price_history == ["2026-08-01T10:00:00+08:00|980", "2026-08-28T10:00:00+08:00|780"]
        assert loaded.last_seen_at == "2026-08-28T10:00:00+08:00"
    finally:
        shutil.rmtree(temp_root, ignore_errors=True)
