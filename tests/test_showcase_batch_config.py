from pathlib import Path

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SHOWCASE_BATCH_SCRIPTS = (
    "start_showcase_server.bat",
    "import_showcase_excel.bat",
    "backup_showcase_db.bat",
    "reset_showcase_admin_password.bat",
)


@pytest.mark.parametrize("script_name", SHOWCASE_BATCH_SCRIPTS)
def test_showcase_batch_script_prefers_local_config_and_passes_selected_path(script_name: str) -> None:
    script = (PROJECT_ROOT / script_name).read_text(encoding="utf-8")

    assert 'set "SHOWCASE_CONFIG=%~dp0config\\showcase.yaml"' in script
    assert (
        'if exist "%~dp0config\\showcase.local.yaml" '
        'set "SHOWCASE_CONFIG=%~dp0config\\showcase.local.yaml"'
    ) in script
    assert '--showcase-config "%SHOWCASE_CONFIG%"' in script
