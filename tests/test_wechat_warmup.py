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
from moments_inventory.config import TaskSettings, WarmupSettings
from moments_inventory.models import TargetContact
from moments_inventory.warmup_report import (
    WarmupContactResult,
    WarmupRunResult,
    write_warmup_report,
)
from moments_inventory.warmup_state import (
    WarmupContactDiagnostics,
    WarmupPageState,
    WarmupStepResult,
    WarmupStepStatus,
)
from moments_inventory.wechat_ui_adapter import WeChatWarmupAdapter
from moments_inventory.wechat_warmup import WarmupRunner


REPORT_NAME_PATTERN = re.compile(
    r"^warmup-report-\d{4}-\d{2}-\d{2}-\d{6}(?:-\d+)?\.txt$"
)


@dataclass(slots=True)
class FakeAdapter:
    outcomes: dict[str, bool | WarmupContactDiagnostics] = field(default_factory=dict)
    prepare_calls: list[str] = field(default_factory=list)
    warmup_calls: list[str] = field(default_factory=list)
    segment_recovery_calls: int = 0

    def prepare(self, start_page: str) -> None:
        if self.prepare_calls:
            self.segment_recovery_calls += 1
        self.prepare_calls.append(start_page)

    def warmup_contact(self, remark_name: str) -> WarmupContactDiagnostics:
        self.warmup_calls.append(remark_name)
        outcome = self.outcomes.get(remark_name, False)
        if isinstance(outcome, WarmupContactDiagnostics):
            return outcome
        return make_diagnostics(
            remark_name,
            success=outcome,
            reset_ok=outcome,
            final_state=(
                WarmupPageState.SEARCH_READY if outcome else WarmupPageState.UNKNOWN
            ),
        )


def make_diagnostics(
    remark_name: str,
    *,
    success: bool,
    reset_ok: bool | None = None,
    final_state: WarmupPageState = WarmupPageState.SEARCH_READY,
) -> WarmupContactDiagnostics:
    diagnostics = WarmupContactDiagnostics(remark_name=remark_name)
    diagnostics.search_ok = success
    diagnostics.select_contact_ok = success
    diagnostics.profile_ok = success
    diagnostics.timeline_open_ok = success
    diagnostics.timeline_scroll_ok = success
    diagnostics.reset_ok = success if reset_ok is None else reset_ok
    diagnostics.final_page_state = final_state
    return diagnostics


def make_contact_result(
    remark_name: str,
    *,
    success: bool,
    failed_step: str = "",
    forced_recovery_used: bool = False,
) -> WarmupContactResult:
    diagnostics = make_diagnostics(
        remark_name,
        success=success,
        reset_ok=success,
        final_state=(
            WarmupPageState.SEARCH_READY if success else WarmupPageState.UNKNOWN
        ),
    )
    diagnostics.forced_recovery_used = forced_recovery_used
    if failed_step:
        diagnostics.step_results.append(
            WarmupStepResult(step=failed_step, status=WarmupStepStatus.FAILED)
        )
    return WarmupContactResult(
        remark_name=remark_name,
        success=success,
        reason="test",
        diagnostics=diagnostics,
    )


def _make_temp_root(prefix: str) -> Path:
    return Path(tempfile.mkdtemp(prefix=prefix))


def test_warmup_adapter_force_recovers_after_reset_failure_when_enabled() -> None:
    class RecoveryController:
        def __init__(self) -> None:
            self.calls: list[tuple[str, object | None]] = []

        def ensure_wechat_window(self) -> None:
            self.calls.append(("ensure_wechat_window", None))

        def open_search(self, start_page: str) -> None:
            self.calls.append(("open_search", start_page))

        def input_search_text(self, text: str) -> None:
            self.calls.append(("input_search_text", text))

        def select_contact(self, remark_name: str) -> None:
            self.calls.append(("select_contact", remark_name))

        def open_timeline(self) -> None:
            self.calls.append(("open_timeline", None))

        def page_down(self) -> None:
            self.calls.append(("page_down", None))

        def reset_to_searchable_page(self, back_delay_ms: int) -> None:
            self.calls.append(("reset_to_searchable_page", back_delay_ms))
            raise RuntimeError("reset failed")

        def force_recover_to_searchable_page(self) -> bool:
            self.calls.append(("force_recover_to_searchable_page", None))
            return True

        def detect_page_state(self) -> WarmupPageState:
            self.calls.append(("detect_page_state", None))
            return WarmupPageState.SEARCH_READY

        def sleep_ms(self, milliseconds: int) -> None:
            self.calls.append(("sleep_ms", milliseconds))

    controller = RecoveryController()
    adapter = WeChatWarmupAdapter(
        settings=WarmupSettings(force_recovery_on_reset_failure=True),
        controller=controller,
    )
    adapter.prepare("contacts")

    diagnostics = adapter.warmup_contact("张三")

    assert diagnostics.forced_recovery_used is True
    assert diagnostics.reset_ok is True
    assert diagnostics.final_page_state is WarmupPageState.SEARCH_READY
    assert controller.calls[-3:] == [
        ("reset_to_searchable_page", 600),
        ("force_recover_to_searchable_page", None),
        ("detect_page_state", None),
    ]


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

        assert adapter.prepare_calls == ["contacts", "contacts"]
        assert adapter.segment_recovery_calls == 1
        assert adapter.warmup_calls == ["张三", "李四", "王五"]
        assert result.success_count == 2
        assert result.failure_count == 1
        assert result.aborted is False
        assert result.should_export is True
        assert report_path.exists()
        assert REPORT_NAME_PATTERN.match(report_path.name)
        assert report_lines[7] == (
            f"- remark_name: 张三 | status: 鎴愬姛 | reason: {result.contact_results[0].reason}"
        )
        assert report_lines[8] == (
            f"- remark_name: 李四 | status: 澶辫触 | reason: {result.contact_results[1].reason}"
        )
        assert report_lines[9] == (
            f"- remark_name: 王五 | status: 鎴愬姛 | reason: {result.contact_results[2].reason}"
        )
        assert report_lines[-2:] == ["step_summary:", "forced_recovery_used: 0"]
    finally:
        shutil.rmtree(temp_root, ignore_errors=True)


def test_warmup_runner_uses_contact_diagnostics_to_determine_success() -> None:
    temp_root = _make_temp_root(f"pytest-warmup-diagnostics-{uuid.uuid4().hex}-")

    try:
        adapter = FakeAdapter(
            outcomes={
                "联系人1": make_diagnostics("联系人1", success=True),
                "联系人2": make_diagnostics(
                    "联系人2",
                    success=False,
                    reset_ok=True,
                    final_state=WarmupPageState.UNKNOWN,
                ),
                "联系人3": make_diagnostics(
                    "联系人3",
                    success=False,
                    reset_ok=False,
                    final_state=WarmupPageState.SEARCH_READY,
                ),
            }
        )
        runner = WarmupRunner(
            settings=WarmupSettings(min_success_count=1, auto_export_on_success=True),
            targets=[
                TargetContact(remark_name="联系人1", wxid="wxid_1"),
                TargetContact(remark_name="联系人2", wxid="wxid_2"),
                TargetContact(remark_name="联系人3", wxid="wxid_3"),
            ],
            adapter=adapter,
            output_dir=temp_root,
        )

        result = runner.run()

        assert result.success_count == 1
        assert result.failure_count == 2
        assert result.contact_results[0].success is True
        assert result.contact_results[1].success is False
        assert result.contact_results[2].success is False
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
        assert result.contact_results[0].reason
        assert report_lines[7] == (
            f"- remark_name: 锛堢己澶卞娉ㄥ悕锛? | status: 澶辫触 | reason: {result.contact_results[0].reason}"
        )
        assert report_lines[8] == (
            f"- remark_name: 王五 | status: 鎴愬姛 | reason: {result.contact_results[1].reason}"
        )
        assert report_lines[-2:] == ["step_summary:", "forced_recovery_used: 0"]
    finally:
        shutil.rmtree(temp_root, ignore_errors=True)


def test_warmup_runner_processes_targets_in_segments_and_recovers_between_segments() -> None:
    temp_root = _make_temp_root(f"pytest-warmup-segments-{uuid.uuid4().hex}-")

    try:
        adapter = FakeAdapter(outcomes={f"联系人{i}": True for i in range(10)})
        targets = [
            TargetContact(remark_name=f"联系人{i}", wxid=f"wxid_{i}")
            for i in range(10)
        ]
        runner = WarmupRunner(
            settings=WarmupSettings(segment_size=5),
            targets=targets,
            adapter=adapter,
            output_dir=temp_root,
        )

        runner.run()

        assert adapter.segment_recovery_calls == 2
        assert adapter.warmup_calls == [f"联系人{i}" for i in range(10)]
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
                WarmupContactResult(remark_name="张三", success=True, reason="棰勫埛鏂版垚鍔?"),
                WarmupContactResult(
                    remark_name=None,
                    success=False,
                    reason="鑱旂郴浜虹己灏戝娉ㄥ悕锛屾棤娉曟墽琛岄鍒锋柊",
                ),
            ],
        )

        report_path = write_warmup_report(temp_root, result)
        report_lines = report_path.read_text(encoding="utf-8").splitlines()

        assert report_path.exists()
        assert REPORT_NAME_PATTERN.match(report_path.name)
        assert result.report_path is None
        assert report_lines[:5] == [
            "寰俊棰勫埛鏂版姤鍛?",
            "success_count: 1",
            "failure_count: 1",
            "aborted: False",
            "should_export: True",
        ]
        assert report_lines[6] == "鑱旂郴浜虹粨鏋?"
        assert report_lines[7] == (
            "- remark_name: 张三 | status: 鎴愬姛 | reason: 棰勫埛鏂版垚鍔?"
        )
        assert report_lines[8] == (
            "- remark_name: 锛堢己澶卞娉ㄥ悕锛? | status: 澶辫触 | reason: 鑱旂郴浜虹己灏戝娉ㄥ悕锛屾棤娉曟墽琛岄鍒锋柊"
        )
        assert report_lines[10:] == ["step_summary:", "forced_recovery_used: 0"]
    finally:
        shutil.rmtree(temp_root, ignore_errors=True)


def test_warmup_report_contains_step_summary() -> None:
    temp_root = _make_temp_root(f"pytest-warmup-step-summary-{uuid.uuid4().hex}-")

    try:
        result = WarmupRunResult(
            success_count=1,
            failure_count=1,
            aborted=False,
            should_export=False,
            contact_results=[
                make_contact_result("白得一批", success=True),
                make_contact_result(
                    "小黎",
                    success=False,
                    failed_step="open_timeline",
                ),
            ],
        )

        report_path = write_warmup_report(temp_root, result)
        content = report_path.read_text(encoding="utf-8")

        assert "step_summary:" in content
        assert "open_timeline_failed: 1" in content
        assert "forced_recovery_used: 0" in content
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
            download_media: bool = True,
        ) -> tuple[str, str]:
            export_calls["count"] += 1
            exported["records"] = records
            exported["output_dir"] = output_dir
            exported["base_url"] = base_url
            exported["access_token"] = access_token
            return ("current.xlsx", "history.xlsx")

        monkeypatch.setattr(cli_module, "load_settings", fake_load_settings)
        monkeypatch.setattr(cli_module, "SyncService", FakeService)
        monkeypatch.setattr(cli_module, "PywinautoWechatController", FakeController)
        monkeypatch.setattr(cli_module, "WeChatWarmupAdapter", FakeAdapter)
        monkeypatch.setattr(cli_module, "WarmupRunner", FakeRunner)
        monkeypatch.setattr(cli_module, "export_records", fake_export_records)

        assert (
            cli_module.main(
                ["--config", str(temp_root / "config.yaml"), "warmup", "--export"]
            )
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
            targets=[TargetContact(remark_name="联系人1", wxid="wxid_1")],
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
            download_media: bool = True,
        ) -> tuple[str, str]:
            export_calls["count"] += 1
            return ("current.xlsx", "history.xlsx")

        monkeypatch.setattr(cli_module, "load_settings", lambda _path: settings)
        monkeypatch.setattr(cli_module, "SyncService", FakeService)
        monkeypatch.setattr(cli_module, "PywinautoWechatController", FakeController)
        monkeypatch.setattr(cli_module, "WeChatWarmupAdapter", FakeAdapter)
        monkeypatch.setattr(cli_module, "WarmupRunner", FakeRunner)
        monkeypatch.setattr(cli_module, "export_records", fake_export_records)

        assert (
            cli_module.main(
                ["--config", str(temp_root / "config.yaml"), "warmup", "--export"]
            )
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
    temp_root = _make_temp_root(
        f"pytest-cli-warmup-skip-export-option-{uuid.uuid4().hex}-"
    )

    try:
        settings = SimpleNamespace(
            warmup=WarmupSettings(enabled=True),
            targets=[TargetContact(remark_name="联系人1", wxid="wxid_1")],
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
            download_media: bool = True,
        ) -> tuple[str, str]:
            export_calls["count"] += 1
            return ("current.xlsx", "history.xlsx")

        monkeypatch.setattr(cli_module, "load_settings", lambda _path: settings)
        monkeypatch.setattr(cli_module, "SyncService", FakeService)
        monkeypatch.setattr(cli_module, "PywinautoWechatController", FakeController)
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
