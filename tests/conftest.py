from pathlib import Path
import os
import shutil
import sys
import tempfile

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SRC_ROOT = PROJECT_ROOT / "src"
ORIGINAL_TEMPDIR = tempfile.tempdir
ORIGINAL_TEMP_ENV = {
    env_name: os.environ[env_name]
    for env_name in ("TMP", "TEMP", "TMPDIR")
    if env_name in os.environ
}
TEST_TEMP_ROOT = Path(
    tempfile.mkdtemp(prefix="aik-t-", dir=tempfile.gettempdir())
)

if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

TEST_TEMP_ROOT.mkdir(parents=True, exist_ok=True)
tempfile.tempdir = str(TEST_TEMP_ROOT)

for env_name in ("TMP", "TEMP", "TMPDIR"):
    os.environ[env_name] = str(TEST_TEMP_ROOT)


def pytest_sessionfinish(session, exitstatus):
    tempfile.tempdir = ORIGINAL_TEMPDIR

    for env_name in ("TMP", "TEMP", "TMPDIR"):
        if env_name in ORIGINAL_TEMP_ENV:
            os.environ[env_name] = ORIGINAL_TEMP_ENV[env_name]
        else:
            os.environ.pop(env_name, None)

    shutil.rmtree(TEST_TEMP_ROOT, ignore_errors=True)
