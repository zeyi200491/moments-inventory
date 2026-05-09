from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import re
import shutil
from types import SimpleNamespace
import tempfile
import uuid

import pytest

import moments_inventory.cli as cli_module
from moments_inventory.config import TaskSettings
from moments_inventory.config import WarmupSettings
from moments_inventory.models import TargetContact
from moments_inventory.warmup_report import (
    WarmupContactResult,
    WarmupRunResult,
    write_warmup_report,
)
from moments_inventory.wechat_warmup import WarmupRunner


REPORT_NAME_PATTERN = re.compile(
    r"^warmup-report-\d{4}-\d{2}-\d{2}-\d{6}(?:-\d+)?\.txt$"
)


@dataclass(slots=True)
class FakeAdapter:
    outcomes: dict[str, bool] = field(default_factory=dict)
    prepare_calls: list[str] = field(default_factory=list)
    warmup_calls: list[str] = field(default_factory=list)

    def prepare(self, start_page: str) -> None:
        self.prepare_calls.append(start_page)

    def warmup_contact(self, remark_name: str) -> bool:
        self.warmup_calls.append(remark_name)
        return self.outcomes.get(remark_name, False)


def _make_temp_root(prefix: str) -> Path:
    return Path(tempfile.mkdtemp(prefix=prefix))


def test_warmup_runner_counts_mixed_results_and_enables_export() -> None:
    temp_root = _make_temp_root(f"pytest-warmup-runner-{uuid.uuid4().hex}-")

    try:
        adapter = FakeAdapter(outcomes={"张三": True, "李四": False, "王五": True})
        runner = WarmupRunner(
            settings=WarmupSettings(min_success_count=2, auto_export_on_success=True),
            targets=[
                TargetContact(remark_name="张三", wxid="wxid_1"),
                TargetContact(remark_name="李四", wxid="wxid_2"),
                TargetContact(remark_name="王五", wxid="wxid_3"),
            ],
            adapter=adapter,
            output_dir=temp_root,
        )

        result = runner.run()
        report_path = Path(result.report_path)
        report_lines = report_path.read_text(encoding="utf-8").splitlines()

        assert adapter.prepare_calls == ["contacts"]
        assert adapter.warmup_calls == ["张三", "李四", "王五"]
        assert result.success_count == 2
        assert result.failure_count == 1
        assert result.aborted is False
        assert result.should_export is True
        assert report_path.exists()
        assert REPORT_NAME_PATTERN.match(report_path.name)
        assert report_lines[7:10] == [
            "- remark_name: 张三 | status: 成功 | reason: 预刷新成功",
            "- remark_name: 李四 | status: 失败 | reason: 适配器执行预刷新失败",
            "- remark_name: 王五 | status: 成功 | reason: 预刷新成功",
        ]
    finally:
        shutil.rmtree(temp_root, ignore_errors=True)


def test_warmup_runner_aborts_after_reaching_max_consecutive_failures() -> None:
    temp_root = _make_temp_root(f"pytest-warmup-abort-{uuid.uuid4().hex}-")

    try:
        adapter = FakeAdapter(outcomes={"张三": False, "李四": False, "王五": True})
        runner = WarmupRunner(
            settings=WarmupSettings(
                max_consecutive_failures=2,
                min_success_count=1,
                auto_export_on_success=True,
            ),
            targets=[
                TargetContact(remark_name="张三", wxid="wxid_1"),
                TargetContact(remark_name="李四", wxid="wxid_2"),
                TargetContact(remark_name="王五", wxid="wxid_3"),
            ],
            adapter=adapter,
            output_dir=temp_root,
        )

        result = runner.run()

        assert adapter.warmup_calls == ["张三", "李四"]
        assert result.success_count == 0
        assert result.failure_count == 2
        assert result.aborted is True
        assert result.should_export is False
    finally:
        shutil.rmtree(temp_root, ignore_errors=True)


def test_warmup_runner_marks_missing_remark_name_as_failure() -> None:
    temp_root = _make_temp_root(f"pytest-warmup-missing-{uuid.uuid4().hex}-")

    try:
        adapter = FakeAdapter(outcomes={"王五": True})
        runner = WarmupRunner(
            settings=WarmupSettings(min_success_count=1, auto_export_on_success=True),
            targets=[
                TargetContact(remark_name=None, wxid="wxid_missing"),
                TargetContact(remark_name="王五", wxid="wxid_3"),
            ],
            adapter=adapter,
            output_dir=temp_root,
        )

        result = runner.run()
        report_lines = Path(result.report_path).read_text(encoding="utf-8").splitlines()

        assert adapter.warmup_calls == ["王五"]
        assert result.success_count == 1
        assert result.failure_count == 1
        assert result.contact_results[0].success is False
        assert "备注名" in result.contact_results[0].reason
        assert report_lines[7] == (
            "- remark_name: （缺失备注名） | status: 失败 | reason: 联系人缺少备注名，无法执行预刷新"
        )
        assert report_lines[8] == "- remark_name: 王五 | status: 成功 | reason: 预刷新成功"
    finally:
        shutil.rmtree(temp_root, ignore_errors=True)


def test_write_warmup_report_outputs_structured_lines_without_mutating_result() -> None:
    temp_root = _make_temp_root(f"pytest-warmup-report-{uuid.uuid4().hex}-")

    try:
        result = WarmupRunResult(
            success_count=1,
            failure_count=1,
            aborted=False,
            should_export=True,
            contact_results=[
                WarmupContactResult(remark_name="张三", success=True, reason="预刷新成功"),
                WarmupContactResult(
                    remark_name=None,
                    success=False,
                    reason="联系人缺少备注名，无法执行预刷新",
                ),
            ],
        )

        report_path = write_warmup_report(temp_root, result)
        report_lines = report_path.read_text(encoding="utf-8").splitlines()

        assert report_path.exists()
        assert REPORT_NAME_PATTERN.match(report_path.name)
        assert result.report_path is None
        assert report_lines == [
            "微信预刷新报告",
            "success_count: 1",
            "failure_count: 1",
            "aborted: False",
            "should_export: True",
            "",
            "联系人结果:",
            "- remark_name: 张三 | status: 成功 | reason: 预刷新成功",
            "- remark_name: （缺失备注名） | status: 失败 | reason: 联系人缺少备注名，无法执行预刷新",
        ]
    finally:
        shutil.rmtree(temp_root, ignore_errors=True)


def test_cli_warmup_export_runs_sync_and_export_when_runner_requests_export(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    temp_root = _make_temp_root(f"pytest-cli-warmup-export-{uuid.uuid4().hex}-")

    try:
        settings = SimpleNamespace(
            warmup=WarmupSettings(enabled=True),
            targets=[TargetContact(remark_name="张三", wxid="wxid_1")],
            task=TaskSettings(output_dir=str(temp_root / "output")),
            weflow=SimpleNamespace(
                base_url="http://127.0.0.1:5030",
                access_token="demo-token",
            ),
        )
        warmup_result = WarmupRunResult(
            success_count=1,
            failure_count=0,
            aborted=False,
            should_export=True,
            contact_results=[],
        )
        adapter_init: dict[str, object] = {}
        runner_init: dict[str, object] = {}
        exported: dict[str, object] = {}
        run_calls = {"count": 0}
        sync_calls = {"count": 0}
        export_calls = {"count": 0}

        class FakeService:
            def __init__(self, _settings: object) -> None:
                self.records = ["record-1"]

            def sync(self) -> list[str]:
                sync_calls["count"] += 1
                return self.records

            def load_records(self) -> list[str]:
                return self.records

        class FakeRunner:
            def __init__(
                self,
                *,
                settings: object,
                targets: object,
                adapter: object,
                output_dir: object,
            ) -> None:
                runner_init["settings"] = settings
                runner_init["targets"] = targets
                runner_init["adapter"] = adapter
                runner_init["output_dir"] = output_dir

            def run(self) -> WarmupRunResult:
                run_calls["count"] += 1
                return warmup_result

        class FakeController:
            pass

        class FakeAdapter:
            def __init__(self, *, settings: object, controller: object) -> None:
                adapter_init["settings"] = settings
                adapter_init["controller"] = controller

        def fake_load_settings(_path: str) -> object:
            return settings

        def fake_export_records(
            records: list[str],
            output_dir: str,
            *,
            base_url: str,
            access_token: str | None,
        ) -> tuple[str, str]:
            export_calls["count"] += 1
            exported["records"] = records
            exported["output_dir"] = output_dir
            exported["base_url"] = base_url
            exported["access_token"] = access_token
            return ("current.xlsx", "history.xlsx")

        monkeypatch.setattr(cli_module, "load_settings", fake_load_settings)
        monkeypatch.setattr(cli_module, "SyncService", FakeService)
        monkeypatch.setattr(cli_module, "PywinautoKeyboardController", FakeController)
        monkeypatch.setattr(cli_module, "WeChatWarmupAdapter", FakeAdapter)
        monkeypatch.setattr(cli_module, "WarmupRunner", FakeRunner)
        monkeypatch.setattr(cli_module, "export_records", fake_export_records)

        assert (
            cli_module.main(["--config", str(temp_root / "config.yaml"), "warmup", "--export"])
            == 0
        )
        assert adapter_init["settings"] is settings.warmup
        assert isinstance(adapter_init["controller"], FakeController)
        assert runner_init["settings"] is settings.warmup
        assert runner_init["targets"] == settings.targets
        assert runner_init["output_dir"] == settings.task.output_dir
        assert run_calls["count"] == 1
        assert sync_calls["count"] == 1
        assert export_calls["count"] == 1
        assert exported == {
            "records": ["record-1"],
            "output_dir": settings.task.output_dir,
            "base_url": settings.weflow.base_url,
            "access_token": settings.weflow.access_token,
        }
    finally:
        shutil.rmtree(temp_root, ignore_errors=True)


def test_cli_warmup_export_skips_sync_and_export_when_runner_blocks_export(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    temp_root = _make_temp_root(f"pytest-cli-warmup-skip-export-flag-{uuid.uuid4().hex}-")

    try:
        settings = SimpleNamespace(
            warmup=WarmupSettings(enabled=True),
            targets=[TargetContact(remark_name="寮犱笁", wxid="wxid_1")],
            task=TaskSettings(output_dir=str(temp_root / "output")),
            weflow=SimpleNamespace(
                base_url="http://127.0.0.1:5030",
                access_token="demo-token",
            ),
        )
        warmup_result = WarmupRunResult(
            success_count=1,
            failure_count=0,
            aborted=False,
            should_export=False,
            contact_results=[],
        )
        run_calls = {"count": 0}
        sync_calls = {"count": 0}
        export_calls = {"count": 0}

        class FakeService:
            def __init__(self, _settings: object) -> None:
                self.records = ["record-1"]

            def sync(self) -> list[str]:
                sync_calls["count"] += 1
                return self.records

            def load_records(self) -> list[str]:
                return self.records

        class FakeRunner:
            def __init__(
                self,
                *,
                settings: object,
                targets: object,
                adapter: object,
                output_dir: object,
            ) -> None:
                pass

            def run(self) -> WarmupRunResult:
                run_calls["count"] += 1
                return warmup_result

        class FakeController:
            pass

        class FakeAdapter:
            def __init__(self, *, settings: object, controller: object) -> None:
                pass

        def fake_export_records(
            records: list[str],
            output_dir: str,
            *,
            base_url: str,
            access_token: str | None,
        ) -> tuple[str, str]:
            export_calls["count"] += 1
            return ("current.xlsx", "history.xlsx")

        monkeypatch.setattr(cli_module, "load_settings", lambda _path: settings)
        monkeypatch.setattr(cli_module, "SyncService", FakeService)
        monkeypatch.setattr(cli_module, "PywinautoKeyboardController", FakeController)
        monkeypatch.setattr(cli_module, "WeChatWarmupAdapter", FakeAdapter)
        monkeypatch.setattr(cli_module, "WarmupRunner", FakeRunner)
        monkeypatch.setattr(cli_module, "export_records", fake_export_records)

        assert (
            cli_module.main(["--config", str(temp_root / "config.yaml"), "warmup", "--export"])
            == 0
        )
        assert run_calls["count"] == 1
        assert sync_calls["count"] == 0
        assert export_calls["count"] == 0
    finally:
        shutil.rmtree(temp_root, ignore_errors=True)


def test_cli_warmup_without_export_flag_skips_sync_and_export(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    temp_root = _make_temp_root(f"pytest-cli-warmup-skip-export-option-{uuid.uuid4().hex}-")

    try:
        settings = SimpleNamespace(
            warmup=WarmupSettings(enabled=True),
            targets=[TargetContact(remark_name="寮犱笁", wxid="wxid_1")],
            task=TaskSettings(output_dir=str(temp_root / "output")),
            weflow=SimpleNamespace(
                base_url="http://127.0.0.1:5030",
                access_token="demo-token",
            ),
        )
        warmup_result = WarmupRunResult(
            success_count=1,
            failure_count=0,
            aborted=False,
            should_export=True,
            contact_results=[],
        )
        run_calls = {"count": 0}
        sync_calls = {"count": 0}
        export_calls = {"count": 0}

        class FakeService:
            def __init__(self, _settings: object) -> None:
                self.records = ["record-1"]

            def sync(self) -> list[str]:
                sync_calls["count"] += 1
                return self.records

            def load_records(self) -> list[str]:
                return self.records

        class FakeRunner:
            def __init__(
                self,
                *,
                settings: object,
                targets: object,
                adapter: object,
                output_dir: object,
            ) -> None:
                pass

            def run(self) -> WarmupRunResult:
                run_calls["count"] += 1
                return warmup_result

        class FakeController:
            pass

        class FakeAdapter:
            def __init__(self, *, settings: object, controller: object) -> None:
                pass

        def fake_export_records(
            records: list[str],
            output_dir: str,
            *,
            base_url: str,
            access_token: str | None,
        ) -> tuple[str, str]:
            export_calls["count"] += 1
            return ("current.xlsx", "history.xlsx")

        monkeypatch.setattr(cli_module, "load_settings", lambda _path: settings)
        monkeypatch.setattr(cli_module, "SyncService", FakeService)
        monkeypatch.setattr(cli_module, "PywinautoKeyboardController", FakeController)
        monkeypatch.setattr(cli_module, "WeChatWarmupAdapter", FakeAdapter)
        monkeypatch.setattr(cli_module, "WarmupRunner", FakeRunner)
        monkeypatch.setattr(cli_module, "export_records", fake_export_records)

        assert cli_module.main(["--config", str(temp_root / "config.yaml"), "warmup"]) == 0
        assert run_calls["count"] == 1
        assert sync_calls["count"] == 0
        assert export_calls["count"] == 0
    finally:
        shutil.rmtree(temp_root, ignore_errors=True)


def test_cli_warmup_rejects_disabled_warmup(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    temp_root = _make_temp_root(f"pytest-cli-warmup-disabled-{uuid.uuid4().hex}-")

    try:
        settings = SimpleNamespace(
            warmup=WarmupSettings(enabled=False),
            targets=[],
            task=TaskSettings(output_dir=str(temp_root / "output")),
            weflow=SimpleNamespace(base_url="http://127.0.0.1:5030", access_token=None),
        )

        monkeypatch.setattr(cli_module, "load_settings", lambda _path: settings)

        with pytest.raises(SystemExit) as exc_info:
            cli_module.main(["--config", str(temp_root / "config.yaml"), "warmup"])

        assert exc_info.value.code == 2
        assert "warmup" in capsys.readouterr().err
    finally:
        shutil.rmtree(temp_root, ignore_errors=True)
