from __future__ import annotations

from types import SimpleNamespace

import pytest

import moments_inventory.cli as cli_module
from moments_inventory.cli import build_parser
from moments_inventory.config import BatchRunSettings, TaskSettings, WarmupSettings
from moments_inventory.models import TargetContact
from moments_inventory.warmup_report import WarmupRunResult


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
