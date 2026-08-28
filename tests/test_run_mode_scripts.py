from __future__ import annotations

import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile


PROJECT_ROOT = Path(__file__).resolve().parent.parent


def test_quick_mode_script_does_not_pause_before_running() -> None:
    content = Path("run_quick_mode.bat").read_text(encoding="utf-8")
    assert "Press any key to start." not in content
    assert "pause >nul" not in content


def test_full_mode_script_does_not_pause_before_running() -> None:
    content = Path("run_full_mode.bat").read_text(encoding="utf-8")
    assert "Press any key to start." not in content
    assert "pause >nul" not in content


def test_full_mode_script_preflights_weflow_token_from_user_environment() -> None:
    content = Path("run_full_mode.bat").read_text(encoding="utf-8")
    assert "HKCU\\Environment" in content
    assert "WEFLOW_ACCESS_TOKEN" in content
    assert "moments_inventory.weflow_client" in content
    assert "WeFlow preflight failed" in content


def test_full_mode_script_cleans_snapshot_directories_on_exit() -> None:
    content = Path("run_full_mode.bat").read_text(encoding="utf-8")
    assert "call :cleanup_screenshots" in content
    assert "%ROOT%output\\*snapshots*" in content
    assert "rmdir /s /q" in content


def test_full_mode_script_enables_media_download() -> None:
    content = Path("run_full_mode.bat").read_text(encoding="utf-8")
    assert "--download-media" in content
    assert "Media download is enabled." in content


def test_fixed_15_warmup_script_uses_preset_runtime_config() -> None:
    content = Path("run_fixed_15_warmup_export.bat").read_text(encoding="utf-8")
    assert "--preset fixed-15-warmup" in content
    assert "--run-output-dir" in content


def test_popup_open_test_mode_script_skips_timeline_scroll() -> None:
    content = Path("run_popup_open_test_mode.bat").read_text(encoding="utf-8")
    assert "--skip-timeline-scroll" in content
    assert "--timeline-open-observe-ms" in content
    assert "--timeline-open-observe-ms 1000" in content
    assert "--timeline-open-capture-dir" in content
    assert "popup-open-test-snapshots" in content
    assert " warmup" in content
    assert "orchestrated-run" not in content
    assert "WeFlowClient" not in content


def test_popup_open_test_mode_script_cleans_snapshot_directories_on_exit() -> None:
    content = Path("run_popup_open_test_mode.bat").read_text(encoding="utf-8")
    assert "call :cleanup_screenshots" in content
    assert "%ROOT%output\\*snapshots*" in content
    assert "rmdir /s /q" in content


def test_full_mode_script_bootstraps_missing_runtime_config_from_examples() -> None:
    source_script = PROJECT_ROOT / "run_full_mode.bat"
    with tempfile.TemporaryDirectory() as temp_dir:
        temp_path = Path(temp_dir)
        target_script = temp_path / "run_full_mode.bat"
        python_path = temp_path / ".venv" / "Scripts" / "python.exe"
        config_example = temp_path / "config" / "config.example.yaml"
        models_example = temp_path / "config" / "models.example.txt"
        config_path = temp_path / "config" / "config.yaml"
        models_path = temp_path / "config" / "models.txt"

        target_script.write_text(source_script.read_text(encoding="utf-8"), encoding="utf-8")
        python_path.parent.mkdir(parents=True)
        shutil.copyfile(sys.executable, python_path)
        config_example.parent.mkdir(parents=True)
        config_example.write_text(
            "\n".join(
                [
                    'weflow:',
                    '  base_url: "http://127.0.0.1:5031"',
                    'task:',
                    '  days: 30',
                    '  merge_window_minutes: 10',
                    '  output_dir: "./output"',
                    'targets: []',
                    'rules:',
                    '  required_fields:',
                    '    - model',
                    '    - price',
                    '    - serial_no',
                    'paths:',
                    '  sqlite_db: "../data/inventory.db"',
                    '  model_dict: "./models.txt"',
                ]
            ),
            encoding="utf-8",
        )
        models_example.write_text("ixus 95\n", encoding="utf-8")

        env = os.environ.copy()
        env["MOMENTS_INVENTORY_NONINTERACTIVE"] = "1"

        result = subprocess.run(
            ["cmd", "/c", str(target_script)],
            cwd=temp_path,
            env=env,
            capture_output=True,
            text=True,
            timeout=20,
        )

        output = result.stdout + result.stderr

        assert result.returncode == 1
        assert config_path.exists()
        assert models_path.exists()
        assert "Created config\\config.yaml from config\\config.example.yaml" in output
        assert "Created config\\models.txt from config\\models.example.txt" in output
