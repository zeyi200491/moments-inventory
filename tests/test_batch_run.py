from __future__ import annotations

from datetime import datetime
from pathlib import Path
import shutil
import sqlite3
import tempfile
import uuid

import pytest

from moments_inventory.batch_run import BatchRunService
from moments_inventory.config import (
    BatchRunSettings,
    PathSettings,
    RuleSettings,
    Settings,
    TaskSettings,
    WeFlowSettings,
)
from moments_inventory.models import InventoryRecord, RawMoment, TargetContact
from moments_inventory.storage import InventoryStore


def _make_temp_root(prefix: str) -> Path:
    return Path(tempfile.mkdtemp(prefix=prefix))


def _build_settings(temp_root: Path, targets: list[TargetContact], batch_size: int) -> Settings:
    return Settings(
        weflow=WeFlowSettings(base_url="http://127.0.0.1:5031", timeout_seconds=20),
        task=TaskSettings(days=30, merge_window_minutes=10, output_dir=str(temp_root / "output")),
        targets=targets,
        rules=RuleSettings(),
        paths=PathSettings(sqlite_db=str(temp_root / "inventory.db"), model_dict=str(temp_root / "models.txt")),
        batch_run=BatchRunSettings(enabled=True, batch_size=batch_size),
        model_keywords=["ixus 95", "x100"],
    )


def _build_seed_record(record_key: str, moment_id: str) -> InventoryRecord:
    return InventoryRecord(
        record_key=record_key,
        remark_name="seed-user",
        wxid="seed-wxid",
        published_at=datetime.fromisoformat("2026-04-20T10:00:00+08:00"),
        model="seed-model",
        price=100,
        serial_no="S1",
        status="current",
        image_urls=["seed.jpg"],
        video_urls=[],
        content_text="seed-model 100 S1",
        source_moment_ids=[moment_id],
    )


def _build_moment(username: str, moment_id: str, content: str, minute: int) -> RawMoment:
    return RawMoment(
        moment_id=moment_id,
        author_remark_name=username,
        author_wxid=username,
        published_at=datetime.fromisoformat(f"2026-04-20T10:{minute:02d}:00+08:00"),
        content=content,
        image_urls=[f"{moment_id}.jpg"],
        video_urls=[],
    )


def _staging_count(db_path: Path) -> int:
    with sqlite3.connect(db_path) as conn:
        return conn.execute("select count(*) from inventory_staging_records").fetchone()[0]


class FakeClient:
    def __init__(
        self,
        timelines_by_username: dict[str, list[RawMoment]],
        failing_username: str | None = None,
        resolved_usernames_by_batch: dict[tuple[str | None, ...], list[str]] | None = None,
    ) -> None:
        self.timelines_by_username = timelines_by_username
        self.failing_username = failing_username
        self.resolved_usernames_by_batch = resolved_usernames_by_batch or {}
        self.resolve_calls: list[list[str | None]] = []
        self.fetch_calls: list[list[str]] = []

    def resolve_usernames(self, targets: list[TargetContact]) -> list[str]:
        batch_wxids = [target.wxid for target in targets]
        self.resolve_calls.append(batch_wxids)
        return list(
            self.resolved_usernames_by_batch.get(
                tuple(batch_wxids),
                [target.wxid for target in targets if target.wxid],
            )
        )

    def fetch_timeline(self, usernames: list[str], start: str, end: str) -> list[RawMoment]:
        self.fetch_calls.append(list(usernames))
        username = usernames[0]
        if username == self.failing_username:
            raise RuntimeError(f"fetch failed for {username}")
        return list(self.timelines_by_username.get(username, []))


def test_batch_run_service_commits_union_from_all_batches() -> None:
    temp_root = _make_temp_root(f"pytest-batch-run-success-{uuid.uuid4().hex}-")

    try:
        targets = [
            TargetContact(remark_name="User 1", wxid="wxid_1"),
            TargetContact(remark_name="User 2", wxid="wxid_2"),
            TargetContact(remark_name="User 1", wxid="wxid_1"),
            TargetContact(remark_name="User 3", wxid="wxid_3"),
            TargetContact(remark_name="User 4", wxid="wxid_4"),
            TargetContact(remark_name="User 5", wxid="wxid_5"),
        ]
        settings = _build_settings(temp_root, targets, batch_size=2)
        store = InventoryStore(settings.paths.sqlite_db)
        store.initialize()
        store.upsert_records(
            [_build_seed_record("old-record", "old-moment")],
            fetched_moment_ids={"old-moment"},
            sync_started_at="2026-04-20T09:00:00+08:00",
        )

        client = FakeClient(
            {
                "wxid_1": [_build_moment("wxid_1", "m1", "ixus 95 100 A1", 1)],
                "wxid_2": [_build_moment("wxid_2", "m2", "ixus 95 200 A2", 2)],
                "wxid_3": [_build_moment("wxid_3", "m3", "x100 300 A3", 3)],
                "wxid_4": [_build_moment("wxid_4", "m4", "ixus 95 400 A4", 4)],
                "wxid_5": [_build_moment("wxid_5", "m5", "x100 500 A5", 5)],
            }
        )
        warmed_batches: list[list[str]] = []

        def warmup_runner(batch_targets: list[TargetContact]) -> None:
            warmed_batches.append([target.wxid for target in batch_targets if target.wxid])

        service = BatchRunService(
            settings=settings,
            store=store,
            client=client,
            warmup_runner=warmup_runner,
        )

        records = service.run(now=datetime.fromisoformat("2026-04-21T12:00:00+08:00"))

        assert [record.wxid for record in records] == [
            "wxid_1",
            "wxid_2",
            "wxid_3",
            "wxid_4",
            "wxid_5",
        ]
        assert all(record.record_key != "old-record" for record in records)
        assert warmed_batches == [
            ["wxid_1", "wxid_2"],
            ["wxid_3", "wxid_4"],
            ["wxid_5"],
        ]
        assert _staging_count(Path(settings.paths.sqlite_db)) == 0
    finally:
        shutil.rmtree(temp_root, ignore_errors=True)


def test_batch_run_service_keeps_formal_store_unchanged_when_batch_fails() -> None:
    temp_root = _make_temp_root(f"pytest-batch-run-failure-{uuid.uuid4().hex}-")

    try:
        targets = [
            TargetContact(remark_name="User 1", wxid="wxid_1"),
            TargetContact(remark_name="User 2", wxid="wxid_2"),
            TargetContact(remark_name="User 3", wxid="wxid_3"),
        ]
        settings = _build_settings(temp_root, targets, batch_size=1)
        store = InventoryStore(settings.paths.sqlite_db)
        store.initialize()
        store.upsert_records(
            [_build_seed_record("old-record", "old-moment")],
            fetched_moment_ids={"old-moment"},
            sync_started_at="2026-04-20T09:00:00+08:00",
        )

        client = FakeClient(
            {
                "wxid_1": [_build_moment("wxid_1", "m1", "ixus 95 100 A1", 1)],
                "wxid_2": [_build_moment("wxid_2", "m2", "ixus 95 200 A2", 2)],
                "wxid_3": [_build_moment("wxid_3", "m3", "x100 300 A3", 3)],
            },
            failing_username="wxid_2",
        )

        service = BatchRunService(
            settings=settings,
            store=store,
            client=client,
            warmup_runner=lambda batch_targets: None,
        )

        with pytest.raises(RuntimeError, match="fetch failed for wxid_2"):
            service.run(now=datetime.fromisoformat("2026-04-21T12:00:00+08:00"))

        records = store.list_all_records()

        assert [record.record_key for record in records] == ["old-record"]
        assert _staging_count(Path(settings.paths.sqlite_db)) == 0
    finally:
        shutil.rmtree(temp_root, ignore_errors=True)


def test_batch_run_service_deduplicates_targets_by_wxid_and_usernames() -> None:
    temp_root = _make_temp_root(f"pytest-batch-run-dedup-{uuid.uuid4().hex}-")

    try:
        targets = [
            TargetContact(remark_name="Alias A", wxid="wxid_1"),
            TargetContact(remark_name="Alias B", wxid="wxid_1"),
            TargetContact(remark_name="Alias C", wxid="wxid_2"),
        ]
        settings = _build_settings(temp_root, targets, batch_size=10)
        store = InventoryStore(settings.paths.sqlite_db)
        store.initialize()

        client = FakeClient(
            {
                "wxid_1": [_build_moment("wxid_1", "m1", "ixus 95 100 A1", 1)],
                "wxid_2": [_build_moment("wxid_2", "m2", "x100 200 A2", 2)],
            },
            resolved_usernames_by_batch={
                ("wxid_1", "wxid_2"): ["wxid_1", "wxid_1", "wxid_2", "wxid_2"],
            },
        )
        warmed_batches: list[list[str | None]] = []

        def warmup_runner(batch_targets: list[TargetContact]) -> None:
            warmed_batches.append([target.wxid for target in batch_targets])

        service = BatchRunService(
            settings=settings,
            store=store,
            client=client,
            warmup_runner=warmup_runner,
        )

        records = service.run(now=datetime.fromisoformat("2026-04-21T12:00:00+08:00"))

        assert [record.wxid for record in records] == ["wxid_1", "wxid_2"]
        assert warmed_batches == [["wxid_1", "wxid_2"]]
        assert client.resolve_calls == [["wxid_1", "wxid_2"]]
        assert client.fetch_calls == [["wxid_1"], ["wxid_2"]]
        assert _staging_count(Path(settings.paths.sqlite_db)) == 0
    finally:
        shutil.rmtree(temp_root, ignore_errors=True)


def test_batch_run_service_uses_configured_target_remark_names() -> None:
    temp_root = _make_temp_root(f"pytest-batch-run-remark-map-{uuid.uuid4().hex}-")

    try:
        targets = [
            TargetContact(remark_name="Configured Seller", wxid="wxid_1"),
        ]
        settings = _build_settings(temp_root, targets, batch_size=10)
        store = InventoryStore(settings.paths.sqlite_db)
        store.initialize()

        client = FakeClient(
            {
                "wxid_1": [
                    RawMoment(
                        moment_id="m1",
                        author_remark_name="WeFlow Alias",
                        author_wxid="wxid_1",
                        published_at=datetime.fromisoformat("2026-04-20T10:01:00+08:00"),
                        content="ixus 95 100 A1",
                        image_urls=["m1.jpg"],
                        video_urls=[],
                    )
                ],
            }
        )

        service = BatchRunService(
            settings=settings,
            store=store,
            client=client,
            warmup_runner=None,
        )

        records = service.run(now=datetime.fromisoformat("2026-04-21T12:00:00+08:00"))

        assert [record.remark_name for record in records] == ["Configured Seller"]
    finally:
        shutil.rmtree(temp_root, ignore_errors=True)


def test_batch_run_service_raises_when_no_usernames_resolve_for_batch() -> None:
    temp_root = _make_temp_root(f"pytest-batch-run-no-usernames-{uuid.uuid4().hex}-")

    try:
        targets = [
            TargetContact(remark_name="User A", wxid=None),
        ]
        settings = _build_settings(temp_root, targets, batch_size=1)
        store = InventoryStore(settings.paths.sqlite_db)
        store.initialize()
        client = FakeClient({}, resolved_usernames_by_batch={(None,): []})

        service = BatchRunService(
            settings=settings,
            store=store,
            client=client,
            warmup_runner=lambda batch_targets: None,
        )

        with pytest.raises(RuntimeError, match="no usernames resolved for batch targets"):
            service.run(now=datetime.fromisoformat("2026-04-21T12:00:00+08:00"))
    finally:
        shutil.rmtree(temp_root, ignore_errors=True)


def test_batch_run_service_skips_later_batch_when_resolved_username_was_already_processed() -> None:
    temp_root = _make_temp_root(f"pytest-batch-run-cross-batch-{uuid.uuid4().hex}-")

    try:
        targets = [
            TargetContact(remark_name="Batch A", wxid="wxid_batch_a"),
            TargetContact(remark_name="Batch B", wxid="wxid_batch_b"),
        ]
        settings = _build_settings(temp_root, targets, batch_size=1)
        store = InventoryStore(settings.paths.sqlite_db)
        store.initialize()

        client = FakeClient(
            {
                "shared-user": [_build_moment("shared-user", "m1", "ixus 95 100 A1", 1)],
            },
            resolved_usernames_by_batch={
                ("wxid_batch_a",): ["shared-user"],
                ("wxid_batch_b",): ["shared-user"],
            },
        )
        warmed_batches: list[list[str | None]] = []

        def warmup_runner(batch_targets: list[TargetContact]) -> None:
            warmed_batches.append([target.wxid for target in batch_targets])

        service = BatchRunService(
            settings=settings,
            store=store,
            client=client,
            warmup_runner=warmup_runner,
        )

        records = service.run(now=datetime.fromisoformat("2026-04-21T12:00:00+08:00"))

        assert [record.wxid for record in records] == ["shared-user"]
        assert warmed_batches == [["wxid_batch_a"]]
        assert client.resolve_calls == [["wxid_batch_a"], ["wxid_batch_b"]]
        assert client.fetch_calls == [["shared-user"]]
        assert _staging_count(Path(settings.paths.sqlite_db)) == 0
    finally:
        shutil.rmtree(temp_root, ignore_errors=True)
