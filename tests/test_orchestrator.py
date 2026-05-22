from __future__ import annotations

from datetime import datetime
from pathlib import Path
import json
import shutil
import sqlite3
import tempfile
import uuid

import pytest

from moments_inventory.config import (
    BatchRunSettings,
    OrchestratorSettings,
    PathSettings,
    RuleSettings,
    Settings,
    TaskSettings,
    WeFlowSettings,
)
from moments_inventory.models import InventoryRecord, RawMoment, TargetContact
from moments_inventory.orchestrator import OrchestratedRunService
from moments_inventory.storage import InventoryStore


def _make_temp_root(prefix: str) -> Path:
    return Path(tempfile.mkdtemp(prefix=prefix))


def _build_settings(
    temp_root: Path,
    targets: list[TargetContact],
    *,
    batch_size: int = 1,
    stop_on_batch_failure: bool = True,
    export_only_when_all_batches_succeed: bool = True,
) -> Settings:
    return Settings(
        weflow=WeFlowSettings(base_url="http://127.0.0.1:5031", timeout_seconds=20),
        task=TaskSettings(days=30, merge_window_minutes=10, output_dir=str(temp_root / "output")),
        targets=targets,
        rules=RuleSettings(),
        paths=PathSettings(
            sqlite_db=str(temp_root / "inventory.db"),
            model_dict=str(temp_root / "models.txt"),
        ),
        batch_run=BatchRunSettings(
            enabled=True,
            batch_size=batch_size,
            stop_on_batch_failure=stop_on_batch_failure,
            export_only_when_all_batches_succeed=export_only_when_all_batches_succeed,
        ),
        orchestrator=OrchestratorSettings(
            enabled=True,
            mode="priority_only",
            batch_size=batch_size,
            priority_output_name="priority.xlsx",
            full_output_name="full.xlsx",
        ),
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
        *,
        failing_username: str | None = None,
    ) -> None:
        self.timelines_by_username = timelines_by_username
        self.failing_username = failing_username

    def resolve_usernames(self, targets: list[TargetContact]) -> list[str]:
        return [target.wxid for target in targets if target.wxid]

    def fetch_timeline(self, usernames: list[str], start: str, end: str) -> list[RawMoment]:
        username = usernames[0]
        if username == self.failing_username:
            raise RuntimeError(f"fetch failed for {username}")
        return list(self.timelines_by_username.get(username, []))


def _fake_export(records: list[InventoryRecord], output_dir: str | Path, **_: object) -> Path:
    output_root = Path(output_dir)
    output_root.mkdir(parents=True, exist_ok=True)
    default_path = output_root / "当前在售库.xlsx"
    payload = "\n".join(record.wxid or "" for record in records)
    default_path.write_text(payload, encoding="utf-8")
    return default_path


def test_priority_only_exports_priority_records_without_committing_current_store() -> None:
    temp_root = _make_temp_root(f"pytest-orchestrator-priority-{uuid.uuid4().hex}-")

    try:
        targets = [
            TargetContact(remark_name="Priority User", wxid="wxid_1", tier=1),
            TargetContact(remark_name="Secondary User", wxid="wxid_2", tier=2),
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
                "wxid_2": [_build_moment("wxid_2", "m2", "x100 200 A2", 2)],
            }
        )

        service = OrchestratedRunService(
            settings=settings,
            store=store,
            client=client,
            warmup_runner=None,
            export_func=_fake_export,
        )

        records = service.run(
            mode="priority_only",
            now=datetime.fromisoformat("2026-04-21T12:00:00+08:00"),
        )

        assert [record.wxid for record in records] == ["wxid_1"]
        assert [record.record_key for record in store.list_all_records()] == ["old-record"]
        assert _staging_count(Path(settings.paths.sqlite_db)) == 0
        assert (Path(settings.task.output_dir) / "priority.xlsx").read_text(encoding="utf-8") == "wxid_1"
        assert not (Path(settings.task.output_dir) / "full.xlsx").exists()

        progress = json.loads((Path(settings.task.output_dir) / "progress.json").read_text(encoding="utf-8"))
        assert progress["priority_done"] is True
        assert progress["priority_export_done"] is True
        assert progress["completed"] is True
        assert progress["full_export_done"] is False
    finally:
        shutil.rmtree(temp_root, ignore_errors=True)


def test_full_mode_exports_priority_then_full_and_commits_union() -> None:
    temp_root = _make_temp_root(f"pytest-orchestrator-full-{uuid.uuid4().hex}-")

    try:
        targets = [
            TargetContact(remark_name="Priority User", wxid="wxid_1", tier=1),
            TargetContact(remark_name="Secondary User A", wxid="wxid_2", tier=2),
            TargetContact(remark_name="Secondary User B", wxid="wxid_3", tier=2),
        ]
        settings = _build_settings(temp_root, targets, batch_size=1)
        store = InventoryStore(settings.paths.sqlite_db)
        store.initialize()
        client = FakeClient(
            {
                "wxid_1": [_build_moment("wxid_1", "m1", "ixus 95 100 A1", 1)],
                "wxid_2": [_build_moment("wxid_2", "m2", "ixus 95 200 A2", 2)],
                "wxid_3": [_build_moment("wxid_3", "m3", "x100 300 A3", 3)],
            }
        )

        service = OrchestratedRunService(
            settings=settings,
            store=store,
            client=client,
            warmup_runner=None,
            export_func=_fake_export,
        )

        records = service.run(
            mode="full",
            now=datetime.fromisoformat("2026-04-21T12:00:00+08:00"),
        )

        assert [record.wxid for record in records] == ["wxid_1", "wxid_2", "wxid_3"]
        assert [record.wxid for record in store.list_all_records()] == ["wxid_1", "wxid_2", "wxid_3"]
        assert (Path(settings.task.output_dir) / "priority.xlsx").read_text(encoding="utf-8") == "wxid_1"
        assert (Path(settings.task.output_dir) / "full.xlsx").read_text(encoding="utf-8") == "wxid_1\nwxid_2\nwxid_3"
        assert _staging_count(Path(settings.paths.sqlite_db)) == 0
    finally:
        shutil.rmtree(temp_root, ignore_errors=True)


def test_full_mode_resume_continues_from_progress_after_failed_secondary_batch() -> None:
    temp_root = _make_temp_root(f"pytest-orchestrator-resume-{uuid.uuid4().hex}-")

    try:
        targets = [
            TargetContact(remark_name="Priority User", wxid="wxid_1", tier=1),
            TargetContact(remark_name="Secondary User A", wxid="wxid_2", tier=2),
            TargetContact(remark_name="Secondary User B", wxid="wxid_3", tier=2),
        ]
        settings = _build_settings(temp_root, targets, batch_size=1)
        store = InventoryStore(settings.paths.sqlite_db)
        store.initialize()

        failing_service = OrchestratedRunService(
            settings=settings,
            store=store,
            client=FakeClient(
                {
                    "wxid_1": [_build_moment("wxid_1", "m1", "ixus 95 100 A1", 1)],
                    "wxid_2": [_build_moment("wxid_2", "m2", "ixus 95 200 A2", 2)],
                    "wxid_3": [_build_moment("wxid_3", "m3", "x100 300 A3", 3)],
                },
                failing_username="wxid_3",
            ),
            warmup_runner=None,
            export_func=_fake_export,
        )

        with pytest.raises(RuntimeError, match="fetch failed for wxid_3"):
            failing_service.run(
                mode="full",
                now=datetime.fromisoformat("2026-04-21T12:00:00+08:00"),
            )

        progress = json.loads((Path(settings.task.output_dir) / "progress.json").read_text(encoding="utf-8"))
        assert progress["priority_done"] is True
        assert progress["secondary_next_batch"] == 1
        assert progress["secondary_failed_batches"] == ["p2-02"]
        assert _staging_count(Path(settings.paths.sqlite_db)) == 2

        resumed_service = OrchestratedRunService(
            settings=settings,
            store=store,
            client=FakeClient(
                {
                    "wxid_1": [_build_moment("wxid_1", "m1", "ixus 95 100 A1", 1)],
                    "wxid_2": [_build_moment("wxid_2", "m2", "ixus 95 200 A2", 2)],
                    "wxid_3": [_build_moment("wxid_3", "m3", "x100 300 A3", 3)],
                }
            ),
            warmup_runner=None,
            export_func=_fake_export,
        )
        records = resumed_service.run(
            mode="full",
            resume=True,
            now=datetime.fromisoformat("2026-04-21T12:00:00+08:00"),
        )

        assert [record.wxid for record in records] == ["wxid_1", "wxid_2", "wxid_3"]
        assert _staging_count(Path(settings.paths.sqlite_db)) == 0
        assert (Path(settings.task.output_dir) / "full.xlsx").read_text(encoding="utf-8") == "wxid_1\nwxid_2\nwxid_3"
    finally:
        shutil.rmtree(temp_root, ignore_errors=True)
