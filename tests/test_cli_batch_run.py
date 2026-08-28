from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace
from xml.etree import ElementTree as ET
import zipfile

import pytest

import moments_inventory.cli as cli_module
from moments_inventory.cli import build_parser
from moments_inventory.config import BatchRunSettings, TaskSettings, WarmupSettings
from moments_inventory.exporter import CURRENT_STATUSES
from moments_inventory.models import InventoryRecord
from moments_inventory.models import TargetContact
from moments_inventory.warmup_report import WarmupRunResult


def _read_sheet_rows(workbook_path) -> list[tuple]:
    namespace = {"main": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
    with zipfile.ZipFile(workbook_path) as archive:
        sheet_xml = archive.read("xl/worksheets/sheet1.xml")

    root = ET.fromstring(sheet_xml)
    rows: list[tuple] = []
    for row in root.findall(".//main:sheetData/main:row", namespace):
        values: list[str | int | None] = []
        for cell in row.findall("main:c", namespace):
            if cell.attrib.get("t") == "inlineStr":
                text_node = cell.find("main:is/main:t", namespace)
                values.append(text_node.text if text_node is not None else "")
                continue
            value_node = cell.find("main:v", namespace)
            if value_node is None:
                values.append(None)
                continue
            raw = value_node.text or ""
            values.append(int(raw) if raw.isdigit() else raw)
        rows.append(tuple(values))
    return rows


def _stdout_stat(output: str, label: str) -> int:
    prefix = f"{label}: "
    for line in output.splitlines():
        if line.startswith(prefix):
            return int(line.removeprefix(prefix))
    raise AssertionError(f"missing stdout stat: {label}")


def test_build_parser_supports_batch_run_export_flag() -> None:
    parser = build_parser()
    args = parser.parse_args(["batch-run", "--export"])

    assert args.command == "batch-run"
    assert args.export is True


def test_build_parser_supports_orchestrated_run_flags() -> None:
    parser = build_parser()
    args = parser.parse_args(["orchestrated-run", "--mode", "full", "--resume"])

    assert args.command == "orchestrated-run"
    assert args.mode == "full"
    assert args.resume is True


def test_cli_batch_run_export_runs_service_and_exports_records(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = SimpleNamespace(
        warmup=WarmupSettings(enabled=True),
        batch_run=BatchRunSettings(enabled=True, stop_on_batch_failure=True),
        targets=[
            TargetContact(remark_name="user-a", wxid="wxid_1"),
            TargetContact(remark_name="user-b", wxid="wxid_2"),
        ],
        task=TaskSettings(output_dir="output-dir"),
        weflow=SimpleNamespace(
            base_url="http://127.0.0.1:5030",
            access_token="demo-token",
        ),
    )
    exported: dict[str, object] = {}
    runner_state: dict[str, object] = {}
    warmup_calls: list[list[str | None]] = []

    class FakeController:
        pass

    class FakeAdapter:
        def __init__(self, *, settings: object, controller: object) -> None:
            runner_state["adapter_settings"] = settings
            runner_state["controller"] = controller

    class FakeWarmupRunner:
        def __init__(
            self,
            *,
            settings: object,
            targets: list[TargetContact],
            adapter: object,
            output_dir: object,
        ) -> None:
            self.targets = targets
            runner_state["warmup_settings"] = settings
            runner_state["warmup_output_dir"] = output_dir

        def run(self) -> WarmupRunResult:
            warmup_calls.append([target.wxid for target in self.targets])
            return WarmupRunResult(
                success_count=len(self.targets),
                failure_count=0,
                aborted=False,
                should_export=False,
                contact_results=[],
            )

    class FakeBatchRunService:
        def __init__(self, settings: object, warmup_runner: object = None) -> None:
            runner_state["settings"] = settings
            runner_state["warmup_runner"] = warmup_runner

        def run(self) -> list[str]:
            assert callable(runner_state["warmup_runner"])
            runner_state["warmup_runner"](
                [
                    TargetContact(remark_name="user-a", wxid="wxid_1"),
                    TargetContact(remark_name="user-b", wxid="wxid_2"),
                ]
            )
            return ["record-1", "record-2"]

    def fake_export_loaded_records(records: list[str], settings_obj: object) -> None:
        exported["records"] = records
        exported["settings"] = settings_obj

    monkeypatch.setattr(cli_module, "load_settings", lambda _path: settings)
    monkeypatch.setattr(cli_module, "BatchRunService", FakeBatchRunService)
    monkeypatch.setattr(cli_module, "PywinautoWechatController", FakeController)
    monkeypatch.setattr(cli_module, "WeChatWarmupAdapter", FakeAdapter)
    monkeypatch.setattr(cli_module, "WarmupRunner", FakeWarmupRunner)
    monkeypatch.setattr(cli_module, "_export_loaded_records", fake_export_loaded_records)
    monkeypatch.setattr(cli_module, "_print_lifecycle_export_stats", lambda _records: None)

    assert cli_module.main(["--config", "config/config.yaml", "batch-run", "--export"]) == 0
    assert runner_state["settings"] is settings
    assert runner_state["warmup_settings"] is settings.warmup
    assert runner_state["warmup_output_dir"] == settings.task.output_dir
    assert isinstance(runner_state["controller"], FakeController)
    assert warmup_calls == [["wxid_1", "wxid_2"]]
    assert exported == {
        "records": ["record-1", "record-2"],
        "settings": settings,
    }


def test_cli_batch_run_export_reports_lifecycle_export_stats(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path,
) -> None:
    settings = SimpleNamespace(
        warmup=WarmupSettings(enabled=False),
        batch_run=BatchRunSettings(enabled=True, stop_on_batch_failure=True),
        targets=[],
        task=TaskSettings(output_dir=str(tmp_path), download_media=False),
        weflow=SimpleNamespace(
            base_url="http://127.0.0.1:5030",
            access_token="demo-token",
        ),
    )

    def build_record(
        record_key: str,
        *,
        lifecycle_status: str = "current",
        risk_flags: list[str] | None = None,
    ) -> InventoryRecord:
        return InventoryRecord(
            record_key=record_key,
            remark_name="user-a",
            wxid="wxid_123",
            published_at=datetime.fromisoformat("2026-04-20T10:00:00+08:00"),
            model=f"IXUS {record_key}",
            price=880,
            serial_no="A12",
            status=next(iter(CURRENT_STATUSES)),
            content_text=f"IXUS {record_key} 880💰 A12",
            lifecycle_status=lifecycle_status,
            risk_flags=risk_flags or [],
        )

    records = [
        build_record("current"),
        build_record("review", lifecycle_status="review"),
        build_record("price-drop", risk_flags=["price_drop_repost"]),
        build_record("sold", lifecycle_status="sold", risk_flags=["sold_keyword"]),
        build_record("delisted", lifecycle_status="delisted", risk_flags=["deleted_missing"]),
        build_record("unmatched", risk_flags=["unmatched_model"]),
        build_record("low-confidence", risk_flags=["low_model_confidence"]),
        build_record("reference", risk_flags=["reference_model"]),
        build_record("conflict", risk_flags=["model_conflict"]),
    ]

    class FakeBatchRunService:
        def __init__(self, settings: object, warmup_runner: object = None) -> None:
            pass

        def run(self) -> list[InventoryRecord]:
            return records

    monkeypatch.setattr(cli_module, "load_settings", lambda _path: settings)
    monkeypatch.setattr(cli_module, "BatchRunService", FakeBatchRunService)

    assert cli_module.main(["--config", "config/config.yaml", "batch-run", "--export"]) == 0

    output = capsys.readouterr().out
    assert "候选记录: 9" in output
    assert "展示记录: 3" in output
    assert "复核记录: 8" in output
    assert "疑似降价重发: 1" in output
    assert "疑似已售/下架: 2" in output
    assert "未匹配型号: 1" in output
    assert "低置信型号: 1" in output
    assert "平替/对比文案: 1" in output
    assert "型号冲突: 1" in output

    current_path = tmp_path / "current.xlsx"
    review_path = tmp_path / "review_needed.xlsx"
    assert current_path.exists()
    assert review_path.exists()
    assert _stdout_stat(output, "展示记录") == len(_read_sheet_rows(current_path)) - 1
    assert _stdout_stat(output, "复核记录") == len(_read_sheet_rows(review_path)) - 1


def test_build_batch_warmup_runner_returns_none_when_warmup_disabled() -> None:
    settings = SimpleNamespace(
        warmup=WarmupSettings(enabled=False),
        batch_run=BatchRunSettings(enabled=True, stop_on_batch_failure=True),
        task=TaskSettings(output_dir="output-dir"),
    )

    assert cli_module._build_batch_warmup_runner(settings) is None


def test_build_batch_warmup_runner_raises_when_batch_is_aborted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = SimpleNamespace(
        warmup=WarmupSettings(enabled=True),
        batch_run=BatchRunSettings(enabled=True, stop_on_batch_failure=True),
        task=TaskSettings(output_dir="output-dir"),
    )

    class FakeController:
        pass

    class FakeAdapter:
        def __init__(self, *, settings: object, controller: object) -> None:
            pass

    class FakeWarmupRunner:
        def __init__(self, *, settings: object, targets: object, adapter: object, output_dir: object) -> None:
            pass

        def run(self) -> WarmupRunResult:
            return WarmupRunResult(
                success_count=0,
                failure_count=0,
                aborted=True,
                should_export=False,
                contact_results=[],
            )

    monkeypatch.setattr(cli_module, "PywinautoWechatController", FakeController)
    monkeypatch.setattr(cli_module, "WeChatWarmupAdapter", FakeAdapter)
    monkeypatch.setattr(cli_module, "WarmupRunner", FakeWarmupRunner)

    warmup_runner = cli_module._build_batch_warmup_runner(settings)

    with pytest.raises(RuntimeError, match="batch warmup aborted"):
        warmup_runner([TargetContact(remark_name="user-a", wxid="wxid_1")])


def test_build_batch_warmup_runner_raises_when_failures_should_stop(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = SimpleNamespace(
        warmup=WarmupSettings(enabled=True),
        batch_run=BatchRunSettings(enabled=True, stop_on_batch_failure=True),
        task=TaskSettings(output_dir="output-dir"),
    )

    class FakeController:
        pass

    class FakeAdapter:
        def __init__(self, *, settings: object, controller: object) -> None:
            pass

    class FakeWarmupRunner:
        def __init__(self, *, settings: object, targets: object, adapter: object, output_dir: object) -> None:
            pass

        def run(self) -> WarmupRunResult:
            return WarmupRunResult(
                success_count=1,
                failure_count=1,
                aborted=False,
                should_export=False,
                contact_results=[],
            )

    monkeypatch.setattr(cli_module, "PywinautoWechatController", FakeController)
    monkeypatch.setattr(cli_module, "WeChatWarmupAdapter", FakeAdapter)
    monkeypatch.setattr(cli_module, "WarmupRunner", FakeWarmupRunner)

    warmup_runner = cli_module._build_batch_warmup_runner(settings)

    with pytest.raises(RuntimeError, match="batch warmup reported failures"):
        warmup_runner([TargetContact(remark_name="user-a", wxid="wxid_1")])


def test_cli_orchestrated_run_uses_service(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = SimpleNamespace(
        warmup=WarmupSettings(enabled=True),
        batch_run=BatchRunSettings(enabled=True, stop_on_batch_failure=True),
        orchestrator=SimpleNamespace(enabled=True),
        targets=[TargetContact(remark_name="user-a", wxid="wxid_1", tier=1)],
        task=TaskSettings(output_dir="output-dir"),
    )
    state: dict[str, object] = {}

    class FakeController:
        pass

    class FakeAdapter:
        def __init__(self, *, settings: object, controller: object) -> None:
            state["adapter_settings"] = settings
            state["controller"] = controller

    class FakeWarmupRunner:
        def __init__(self, *, settings: object, targets: object, adapter: object, output_dir: object) -> None:
            state["warmup_settings"] = settings
            state["warmup_output_dir"] = output_dir
            state["warmup_targets"] = targets

        def run(self) -> WarmupRunResult:
            return WarmupRunResult(
                success_count=1,
                failure_count=0,
                aborted=False,
                should_export=False,
                contact_results=[],
            )

    class FakeOrchestratedRunService:
        def __init__(self, settings: object, warmup_runner: object = None) -> None:
            state["settings"] = settings
            state["warmup_runner"] = warmup_runner

        def run(self, *, mode: str | None = None, resume: bool = False) -> list[str]:
            state["mode"] = mode
            state["resume"] = resume
            assert callable(state["warmup_runner"])
            state["warmup_runner"]([TargetContact(remark_name="user-a", wxid="wxid_1", tier=1)])
            return ["record-1"]

    monkeypatch.setattr(cli_module, "load_settings", lambda _path: settings)
    monkeypatch.setattr(cli_module, "OrchestratedRunService", FakeOrchestratedRunService)
    monkeypatch.setattr(cli_module, "PywinautoWechatController", FakeController)
    monkeypatch.setattr(cli_module, "WeChatWarmupAdapter", FakeAdapter)
    monkeypatch.setattr(cli_module, "WarmupRunner", FakeWarmupRunner)

    assert (
        cli_module.main(
            ["--config", "config/config.yaml", "orchestrated-run", "--mode", "full", "--resume"]
        )
        == 0
    )
    assert state["settings"] is settings
    assert state["mode"] == "full"
    assert state["resume"] is True
    assert state["warmup_settings"] is settings.warmup
    assert state["warmup_output_dir"] == settings.task.output_dir
