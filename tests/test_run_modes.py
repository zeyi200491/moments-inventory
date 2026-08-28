from __future__ import annotations

from pathlib import Path
import tempfile

import yaml

from moments_inventory.config import load_settings
from moments_inventory.run_modes import (
    FIXED_15_WARMUP_TARGETS,
    create_fixed_targets_runtime_config,
    create_runtime_config,
)


def test_create_runtime_config_forces_warmup_orchestrator_and_disables_media() -> None:
    with tempfile.TemporaryDirectory(prefix="pytest-run-modes-") as temp_dir:
        temp_root = Path(temp_dir)
        base_config = temp_root / "config.yaml"
        runtime_config = temp_root / "runtime-config.yaml"
        (temp_root / "models.txt").write_text("ixus\n", encoding="utf-8")
        base_config.write_text(
            """
weflow:
  base_url: "http://127.0.0.1:5031"
  timeout_seconds: 20
  access_token: ""
task:
  days: 30
  merge_window_minutes: 10
  output_dir: "./output"
  download_media: true
targets:
  - remark_name: "user-a"
    tier: 1
rules:
  required_fields:
    - model
    - price
    - serial_no
paths:
  sqlite_db: "./data/inventory.db"
  model_dict: "./models.txt"
warmup:
  enabled: false
orchestrator:
  enabled: false
  mode: "priority_only"
  batch_size: 25
  export_priority_after_p1: true
  export_full_after_all: true
  resume_enabled: true
  write_failed_targets: true
  priority_output_name: "优先货源当前库.xlsx"
  full_output_name: "全量当前库.xlsx"
            """.strip(),
            encoding="utf-8",
        )

        create_runtime_config(base_config, runtime_config)

        content = yaml.safe_load(runtime_config.read_text(encoding="utf-8"))
        assert content["task"]["download_media"] is False
        assert content["warmup"]["enabled"] is True
        assert content["orchestrator"]["enabled"] is True
        assert content["orchestrator"]["mode"] == "priority_only"
        assert Path(content["task"]["output_dir"]) == (temp_root / "output").resolve()


def test_create_runtime_config_can_enable_media_download() -> None:
    with tempfile.TemporaryDirectory(prefix="pytest-run-modes-media-") as temp_dir:
        temp_root = Path(temp_dir)
        base_config = temp_root / "config.yaml"
        runtime_config = temp_root / "runtime-config.yaml"
        (temp_root / "models.txt").write_text("ixus\n", encoding="utf-8")
        base_config.write_text(
            """
weflow:
  base_url: "http://127.0.0.1:5031"
task:
  days: 30
  merge_window_minutes: 10
  output_dir: "./output"
  download_media: false
targets:
  - remark_name: "user-a"
    tier: 1
rules:
  required_fields:
    - model
paths:
  sqlite_db: "./data/inventory.db"
  model_dict: "./models.txt"
warmup:
  enabled: false
orchestrator:
  enabled: false
            """.strip(),
            encoding="utf-8",
        )

        create_runtime_config(base_config, runtime_config, download_media=True)

        settings = load_settings(runtime_config)
        assert settings.task.download_media is True


def test_create_runtime_config_can_enable_popup_open_test_mode() -> None:
    with tempfile.TemporaryDirectory(prefix="pytest-run-modes-popup-test-") as temp_dir:
        temp_root = Path(temp_dir)
        base_config = temp_root / "config.yaml"
        runtime_config = temp_root / "runtime-config.yaml"
        (temp_root / "models.txt").write_text("ixus\n", encoding="utf-8")
        base_config.write_text(
            """
weflow:
  base_url: "http://127.0.0.1:5031"
task:
  days: 30
  merge_window_minutes: 10
  output_dir: "./output"
targets: []
rules:
  required_fields:
    - model
paths:
  sqlite_db: "./data/inventory.db"
  model_dict: "./models.txt"
warmup:
  enabled: false
orchestrator:
  enabled: false
            """.strip(),
            encoding="utf-8",
        )

        create_runtime_config(
            base_config,
            runtime_config,
            skip_timeline_scroll=True,
            timeline_open_observe_ms=1000,
            timeline_open_capture_dir=temp_root / "captures",
        )

        settings = load_settings(runtime_config)
        assert settings.warmup.skip_timeline_scroll is True
        assert settings.warmup.timeline_open_observe_ms == 1000
        assert Path(settings.warmup.timeline_open_capture_dir or "") == (
            temp_root / "captures"
        ).resolve()


def test_create_runtime_config_rewrites_relative_paths_against_base_config() -> None:
    with tempfile.TemporaryDirectory(prefix="pytest-run-modes-paths-") as temp_dir:
        temp_root = Path(temp_dir)
        config_dir = temp_root / "config"
        data_dir = temp_root / "data"
        output_dir = temp_root / "output"
        config_dir.mkdir()
        data_dir.mkdir()
        output_dir.mkdir()
        (config_dir / "models.txt").write_text("ixus 95\n", encoding="utf-8")

        base_config = config_dir / "config.yaml"
        runtime_config = temp_root / ".test-tmp" / "run-modes" / "runtime-config.yaml"
        base_config.write_text(
            """
weflow:
  base_url: "http://127.0.0.1:5031"
  timeout_seconds: 20
  access_token: ""
task:
  days: 30
  merge_window_minutes: 10
  output_dir: "../output"
targets:
  - remark_name: "user-a"
    tier: 1
rules:
  required_fields:
    - model
    - price
    - serial_no
paths:
  sqlite_db: "../data/inventory.db"
  model_dict: "./models.txt"
            """.strip(),
            encoding="utf-8",
        )

        create_runtime_config(base_config, runtime_config)
        settings = load_settings(runtime_config)

        assert Path(settings.task.output_dir) == output_dir.resolve()
        assert Path(settings.paths.sqlite_db) == (data_dir / "inventory.db").resolve()
        assert Path(settings.paths.model_dict) == (config_dir / "models.txt").resolve()
        assert Path(settings.paths.model_catalog_index) == (
            data_dir / "model_catalog_index.json"
        ).resolve()


def test_create_fixed_targets_runtime_config_uses_expected_targets_and_switches() -> None:
    with tempfile.TemporaryDirectory(prefix="pytest-run-modes-fixed-targets-") as temp_dir:
        temp_root = Path(temp_dir)
        config_dir = temp_root / "config"
        data_dir = temp_root / "data"
        output_dir = temp_root / "oneoff-output"
        config_dir.mkdir()
        data_dir.mkdir()
        output_dir.mkdir()
        (config_dir / "models.txt").write_text("ixus 95\n", encoding="utf-8")

        base_config = config_dir / "config.yaml"
        runtime_config = temp_root / ".test-tmp" / "run-modes" / "fixed-15.config.yaml"
        base_config.write_text(
            """
weflow:
  base_url: "http://127.0.0.1:5031"
  timeout_seconds: 20
  access_token: ""
task:
  days: 30
  merge_window_minutes: 10
  output_dir: "../output"
  download_media: true
targets:
  - remark_name: "user-a"
    tier: 2
rules:
  required_fields:
    - model
    - price
    - serial_no
paths:
  sqlite_db: "../data/inventory.db"
  model_dict: "./models.txt"
warmup:
  enabled: false
orchestrator:
  enabled: false
  mode: "full"
  batch_size: 25
  export_priority_after_p1: true
  export_full_after_all: true
  resume_enabled: true
  write_failed_targets: true
  priority_output_name: "priority.xlsx"
  full_output_name: "full.xlsx"
            """.strip(),
            encoding="utf-8",
        )

        create_fixed_targets_runtime_config(
            base_config,
            runtime_config,
            output_dir=output_dir,
        )
        settings = load_settings(runtime_config)

        assert [target.remark_name for target in settings.targets] == list(FIXED_15_WARMUP_TARGETS)
        assert all(target.tier == 1 for target in settings.targets)
        assert settings.warmup.enabled is True
        assert settings.task.download_media is False
        assert settings.orchestrator.enabled is True
        assert settings.orchestrator.mode == "priority_only"
        assert settings.orchestrator.export_full_after_all is False
        assert settings.orchestrator.priority_output_name == "15人warmup无媒体.xlsx"
        assert Path(settings.task.output_dir) == output_dir.resolve()
