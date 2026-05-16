import os
import subprocess
import tempfile
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent


def test_windows_delivery_artifacts_exist_and_document_required_setup():
    setup_script = PROJECT_ROOT / "setup_windows.bat"
    run_script = PROJECT_ROOT / "run_export.bat"
    warmup_script = PROJECT_ROOT / "run_warmup_and_export.bat"
    usage_doc = PROJECT_ROOT / "docs" / "windows-使用说明.md"
    models_example = PROJECT_ROOT / "config" / "models.example.txt"

    assert setup_script.exists()
    assert run_script.exists()
    assert warmup_script.exists()
    assert usage_doc.exists()
    assert models_example.exists()

    setup_text = setup_script.read_text(encoding="utf-8")
    run_text = run_script.read_text(encoding="utf-8")
    warmup_text = warmup_script.read_text(encoding="utf-8")
    usage_text = usage_doc.read_text(encoding="utf-8")

    assert ".venv" in setup_text
    assert "config\\config.example.yaml" in setup_text
    assert "sync --export" in run_text
    assert "warmup --export" in warmup_text
    assert 'config\\models.txt' in warmup_text
    assert "WEFLOW_ACCESS_TOKEN" in warmup_text
    assert "config/config.example.yaml" in usage_text
    assert "config/config.yaml" in usage_text
    assert "config/models.txt" in usage_text
    assert "config/models.example.txt" in usage_text
    assert "WEFLOW_ACCESS_TOKEN" in usage_text
    assert "微信先停在通讯录或聊天列表" in usage_text
    assert "warmup.enabled" in usage_text
    assert "remark_name" in usage_text
    assert "必填" in usage_text


def test_run_warmup_and_export_reports_missing_models_in_noninteractive_mode():
    source_script = PROJECT_ROOT / "run_warmup_and_export.bat"
    with tempfile.TemporaryDirectory() as temp_dir:
        temp_path = Path(temp_dir)
        target_script = temp_path / "run_warmup_and_export.bat"
        python_path = temp_path / ".venv" / "Scripts" / "python.exe"
        config_path = temp_path / "config" / "config.yaml"

        target_script.write_text(source_script.read_text(encoding="utf-8"), encoding="utf-8")
        python_path.parent.mkdir(parents=True)
        python_path.write_text("", encoding="utf-8")
        config_path.parent.mkdir(parents=True)
        config_path.write_text("warmup:\n  enabled: true\n", encoding="utf-8")

        env = os.environ.copy()
        env["MOMENTS_INVENTORY_NONINTERACTIVE"] = "1"

        result = subprocess.run(
            ["cmd", "/c", str(target_script)],
            cwd=temp_path,
            env=env,
            capture_output=True,
            text=True,
            timeout=5,
        )

        output = result.stdout + result.stderr

    assert result.returncode == 1
    assert "Missing model dictionary: config\\models.txt" in output


def test_ai_kefu_workbench_launcher_artifacts_exist_and_reference_expected_commands():
    launcher_script = PROJECT_ROOT / "run_ai_kefu_workbench.bat"
    helper_script = PROJECT_ROOT / "scripts" / "start_ai_kefu_workbench.ps1"

    assert launcher_script.exists()
    assert helper_script.exists()

    launcher_text = launcher_script.read_text(encoding="utf-8")
    helper_text = helper_script.read_text(encoding="utf-8")

    assert "start_ai_kefu_workbench.ps1" in launcher_text
    assert "ExecutionPolicy Bypass" in launcher_text
    assert "moments_inventory.cli" in helper_text
    assert "kefu-dev" in helper_text
    assert "frontend\\workbench" in helper_text
    assert "http://127.0.0.1:5173" in helper_text
    assert "MOMENTS_INVENTORY_NONINTERACTIVE" in helper_text
    assert "multipart" in helper_text
    assert "cmd /c" in helper_text


def test_ai_kefu_workbench_launcher_reports_missing_frontend_package_in_noninteractive_mode():
    source_launcher = PROJECT_ROOT / "run_ai_kefu_workbench.bat"
    source_helper = PROJECT_ROOT / "scripts" / "start_ai_kefu_workbench.ps1"

    with tempfile.TemporaryDirectory() as temp_dir:
        temp_path = Path(temp_dir)
        launcher_path = temp_path / "run_ai_kefu_workbench.bat"
        helper_path = temp_path / "scripts" / "start_ai_kefu_workbench.ps1"
        python_path = temp_path / ".venv" / "Scripts" / "python.exe"
        ai_kefu_config = temp_path / "config" / "ai_kefu.yaml"

        launcher_path.write_text(source_launcher.read_text(encoding="utf-8"), encoding="utf-8")
        helper_path.parent.mkdir(parents=True)
        helper_path.write_text(source_helper.read_text(encoding="utf-8"), encoding="utf-8")
        python_path.parent.mkdir(parents=True)
        python_path.write_text("", encoding="utf-8")
        ai_kefu_config.parent.mkdir(parents=True)
        ai_kefu_config.write_text("chat_model: test\n", encoding="utf-8")

        env = os.environ.copy()
        env["MOMENTS_INVENTORY_NONINTERACTIVE"] = "1"

        result = subprocess.run(
            ["cmd", "/c", str(launcher_path)],
            cwd=temp_path,
            env=env,
            capture_output=True,
            text=True,
            timeout=10,
        )

        output = result.stdout + result.stderr

    assert result.returncode == 1
    assert "Missing frontend package file" in output


def test_ai_kefu_workbench_launcher_reports_missing_openai_api_key_in_noninteractive_mode():
    source_launcher = PROJECT_ROOT / "run_ai_kefu_workbench.bat"
    source_helper = PROJECT_ROOT / "scripts" / "start_ai_kefu_workbench.ps1"

    with tempfile.TemporaryDirectory() as temp_dir:
        temp_path = Path(temp_dir)
        launcher_path = temp_path / "run_ai_kefu_workbench.bat"
        helper_path = temp_path / "scripts" / "start_ai_kefu_workbench.ps1"
        python_path = temp_path / ".venv" / "Scripts" / "python.exe"
        ai_kefu_config = temp_path / "config" / "ai_kefu.yaml"
        frontend_package = temp_path / "frontend" / "workbench" / "package.json"
        frontend_modules = temp_path / "frontend" / "workbench" / "node_modules"

        launcher_path.write_text(source_launcher.read_text(encoding="utf-8"), encoding="utf-8")
        helper_path.parent.mkdir(parents=True)
        helper_path.write_text(source_helper.read_text(encoding="utf-8"), encoding="utf-8")
        python_path.parent.mkdir(parents=True)
        python_path.write_text("", encoding="utf-8")
        ai_kefu_config.parent.mkdir(parents=True)
        ai_kefu_config.write_text(
            '\n'.join(
                [
                    'workspace_dir: "./data/ai_kefu_workspace"',
                    'database_path: "./data/ai_kefu/ai-kefu.db"',
                    'embedding_provider: "openai"',
                    'chat_provider: "openai_compatible"',
                    'chat_model: "gpt-4.1-mini"',
                    'chat_provider_options:',
                    '  api_base: "https://api.openai.com/v1"',
                    '  api_key_env: "AI_KEFU_OPENAI_API_KEY"',
                    '  timeout_seconds: 30',
                ]
            ),
            encoding="utf-8",
        )
        frontend_package.parent.mkdir(parents=True)
        frontend_package.write_text("{}", encoding="utf-8")
        frontend_modules.mkdir(parents=True)

        env = os.environ.copy()
        env["MOMENTS_INVENTORY_NONINTERACTIVE"] = "1"
        env.pop("AI_KEFU_OPENAI_API_KEY", None)

        result = subprocess.run(
            ["cmd", "/c", str(launcher_path)],
            cwd=temp_path,
            env=env,
            capture_output=True,
            text=True,
            timeout=10,
        )

        output = result.stdout + result.stderr

    assert result.returncode == 1
    assert "Missing required environment variable: AI_KEFU_OPENAI_API_KEY" in output


def test_batched_delivery_artifacts_exist_and_docs_drop_history_workbook():
    batched_script = PROJECT_ROOT / "run_batched_warmup_and_export.bat"
    usage_text = (PROJECT_ROOT / "docs" / "windows-使用说明.md").read_text(encoding="utf-8")
    readme_text = (PROJECT_ROOT / "README.md").read_text(encoding="utf-8")

    assert batched_script.exists()
    assert "历史总库.xlsx" not in usage_text
    assert "历史总库 Excel" not in readme_text
    assert "run_batched_warmup_and_export.bat" in usage_text
    assert "batch-run --export" in readme_text
