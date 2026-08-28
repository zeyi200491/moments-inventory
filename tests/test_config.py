from pathlib import Path
import os
import shutil
import subprocess
import sys
import tempfile
import tomllib
import uuid
import venv

import pytest

from moments_inventory.config import ConfigError, load_settings


PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _make_temp_root(prefix: str) -> Path:
    return Path(tempfile.mkdtemp(prefix=prefix))


def _venv_python(venv_dir: Path) -> Path:
    if sys.platform == "win32":
        return venv_dir / "Scripts" / "python.exe"
    return venv_dir / "bin" / "python"


def _venv_script(venv_dir: Path) -> Path:
    if sys.platform == "win32":
        scripts_dir = venv_dir / "Scripts"
        for candidate in (
            scripts_dir / "moments-inventory.exe",
            scripts_dir / "moments-inventory-script.py",
        ):
            if candidate.exists():
                return candidate
        return scripts_dir / "moments-inventory.exe"
    return venv_dir / "bin" / "moments-inventory"


def _subprocess_tempfile_is_writable() -> bool:
    probe = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "import pathlib, tempfile; "
                "root = pathlib.Path(tempfile.mkdtemp()); "
                "(root / 'probe.txt').write_text('ok', encoding='utf-8')"
            ),
        ],
        capture_output=True,
        text=True,
    )
    return probe.returncode == 0


def test_pyproject_uses_single_version_source_and_src_layout():
    pyproject = tomllib.loads((PROJECT_ROOT / "pyproject.toml").read_text(encoding="utf-8"))

    assert pyproject["project"]["dynamic"] == ["version"]
    assert pyproject["tool"]["setuptools"]["dynamic"]["version"] == {
        "attr": "moments_inventory.__version__"
    }
    assert "pythonpath" not in pyproject["tool"]["pytest"]["ini_options"]


def test_pyproject_declares_cli_script():
    pyproject = tomllib.loads((PROJECT_ROOT / "pyproject.toml").read_text(encoding="utf-8"))

    assert pyproject["project"]["scripts"]["moments-inventory"] == "moments_inventory:main"


def test_load_settings_reads_targets():
    temp_root = _make_temp_root(f"pytest-config-{uuid.uuid4().hex}-")

    try:
        config_file = temp_root / "config.yaml"
        model_file = temp_root / "models.txt"
        model_file.write_text("ixus 95\nsony t2\n", encoding="utf-8")
        config_file.write_text(
            """
weflow:
  base_url: "http://127.0.0.1:5030"
  timeout_seconds: 20
  access_token: "demo-token"
task:
  days: 30
  merge_window_minutes: 10
  output_dir: "./output"
  download_media: false
targets:
  - remark_name: "user-a"
    wxid: "wxid_123"
    tier: 1
rules:
  required_fields:
    - model
    - price
    - serial_no
paths:
  sqlite_db: "./data/inventory.db"
  model_dict: "MODELS_FILE"
orchestrator:
  enabled: true
  mode: "full"
  batch_size: 25
  export_priority_after_p1: true
  export_full_after_all: true
  resume_enabled: true
  write_failed_targets: true
  priority_output_name: "priority.xlsx"
  full_output_name: "full.xlsx"
            """.replace("MODELS_FILE", str(model_file).replace("\\", "/")),
            encoding="utf-8",
        )

        settings = load_settings(config_file)

        assert settings.weflow.base_url == "http://127.0.0.1:5030"
        assert settings.task.merge_window_minutes == 10
        assert settings.task.download_media is False
        assert settings.targets[0].remark_name == "user-a"
        assert settings.targets[0].tier == 1
        assert settings.weflow.access_token == "demo-token"
        assert settings.orchestrator.enabled is True
        assert settings.orchestrator.mode == "full"
        assert settings.model_keywords == ["ixus 95", "sony t2"]
        assert settings.paths.model_catalog_index.endswith("model_catalog_index.json")
    finally:
        shutil.rmtree(temp_root, ignore_errors=True)


def test_load_settings_falls_back_to_env_access_token():
    temp_root = _make_temp_root(f"pytest-config-env-{uuid.uuid4().hex}-")
    original_token = os.environ.get("WEFLOW_ACCESS_TOKEN")
    os.environ["WEFLOW_ACCESS_TOKEN"] = "env-token"

    try:
        config_file = temp_root / "config.yaml"
        model_file = temp_root / "models.txt"
        model_file.write_text("ixus 95\n", encoding="utf-8")
        config_file.write_text(
            """
weflow:
  base_url: "http://127.0.0.1:5030"
  timeout_seconds: 20
  access_token: ""
task:
  days: 30
  merge_window_minutes: 10
  output_dir: "./output"
targets:
  - remark_name: "user-a"
    wxid: "wxid_123"
rules:
  required_fields:
    - model
    - price
    - serial_no
paths:
  sqlite_db: "./data/inventory.db"
  model_dict: "MODELS_FILE"
            """.replace("MODELS_FILE", str(model_file).replace("\\", "/")),
            encoding="utf-8",
        )

        settings = load_settings(config_file)

        assert settings.weflow.access_token == "env-token"
    finally:
        if original_token is None:
            os.environ.pop("WEFLOW_ACCESS_TOKEN", None)
        else:
            os.environ["WEFLOW_ACCESS_TOKEN"] = original_token
        shutil.rmtree(temp_root, ignore_errors=True)


def test_load_settings_rejects_unknown_weflow_field():
    temp_root = _make_temp_root(f"pytest-config-unknown-{uuid.uuid4().hex}-")

    try:
        config_file = temp_root / "config.yaml"
        model_file = temp_root / "models.txt"
        model_file.write_text("ixus 95\n", encoding="utf-8")
        config_file.write_text(
            """
weflow:
  baseurl: "http://127.0.0.1:5030"
  timeout_seconds: 20
task:
  days: 30
  merge_window_minutes: 10
  output_dir: "./output"
targets:
  - remark_name: "user-a"
    wxid: "wxid_123"
rules:
  required_fields:
    - model
    - price
    - serial_no
paths:
  sqlite_db: "./data/inventory.db"
  model_dict: "MODELS_FILE"
            """.replace("MODELS_FILE", str(model_file).replace("\\", "/")),
            encoding="utf-8",
        )

        with pytest.raises(ConfigError, match="weflow.baseurl"):
            load_settings(config_file)
    finally:
        shutil.rmtree(temp_root, ignore_errors=True)


def test_load_settings_rejects_missing_required_field():
    temp_root = _make_temp_root(f"pytest-config-missing-{uuid.uuid4().hex}-")

    try:
        config_file = temp_root / "config.yaml"
        model_file = temp_root / "models.txt"
        model_file.write_text("ixus 95\n", encoding="utf-8")
        config_file.write_text(
            """
weflow:
  timeout_seconds: 20
task:
  days: 30
  merge_window_minutes: 10
  output_dir: "./output"
targets:
  - remark_name: "user-a"
    wxid: "wxid_123"
rules:
  required_fields:
    - model
    - price
    - serial_no
paths:
  sqlite_db: "./data/inventory.db"
  model_dict: "MODELS_FILE"
            """.replace("MODELS_FILE", str(model_file).replace("\\", "/")),
            encoding="utf-8",
        )

        with pytest.raises(ConfigError, match="weflow.base_url"):
            load_settings(config_file)
    finally:
        shutil.rmtree(temp_root, ignore_errors=True)


def test_editable_install_exposes_import_and_console_script():
    if not _subprocess_tempfile_is_writable():
        pytest.skip("当前环境的标准库 tempfile/ensurepip 不可写，跳过 editable install 烟雾测试")

    temp_path = _make_temp_root(f"pytest-smoke-{uuid.uuid4().hex}-")
    venv_dir = temp_path / "venv"

    try:
        venv.EnvBuilder(with_pip=True).create(venv_dir)

        subprocess_env = os.environ.copy()
        python_executable = _venv_python(venv_dir)
        subprocess.run(
            [str(python_executable), "-m", "pip", "install", "-e", str(PROJECT_ROOT), "--no-deps"],
            check=True,
            capture_output=True,
            text=True,
            env=subprocess_env,
        )

        import_check = subprocess.run(
            [
                str(python_executable),
                "-c",
                "import moments_inventory; assert moments_inventory.__version__ == '0.1.0'",
            ],
            check=True,
            capture_output=True,
            text=True,
            env=subprocess_env,
        )
        assert import_check.returncode == 0

        script_run = subprocess.run(
            [str(_venv_script(venv_dir))],
            check=True,
            capture_output=True,
            text=True,
            env=subprocess_env,
        )
        assert script_run.returncode == 0
    finally:
        if temp_path.exists():
            shutil.rmtree(temp_path, ignore_errors=True)


def test_readme_mentions_sync_export_command():
    readme = (PROJECT_ROOT / "README.md").read_text(encoding="utf-8")

    assert "python -m moments_inventory.cli sync --export" in readme
