from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent


def test_windows_delivery_artifacts_exist_and_document_required_setup():
    setup_script = PROJECT_ROOT / "setup_windows.bat"
    run_script = PROJECT_ROOT / "run_export.bat"
    usage_doc = PROJECT_ROOT / "docs" / "windows-使用说明.md"
    models_example = PROJECT_ROOT / "config" / "models.example.txt"

    assert setup_script.exists()
    assert run_script.exists()
    assert usage_doc.exists()
    assert models_example.exists()

    setup_text = setup_script.read_text(encoding="utf-8")
    run_text = run_script.read_text(encoding="utf-8")
    usage_text = usage_doc.read_text(encoding="utf-8")

    assert ".venv" in setup_text
    assert "config\\config.example.yaml" in setup_text
    assert "sync --export" in run_text
    assert "config/config.example.yaml" in usage_text
    assert "config/config.yaml" in usage_text
    assert "config/models.txt" in usage_text
    assert "config/models.example.txt" in usage_text
    assert "WEFLOW_ACCESS_TOKEN" in usage_text
