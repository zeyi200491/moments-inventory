from pathlib import Path
import os
import shutil
import sys
import tempfile
import uuid

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SRC_ROOT = PROJECT_ROOT / "src"
TEST_TEMP_ROOT = PROJECT_ROOT / ".test-tmp" / uuid.uuid4().hex

if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

TEST_TEMP_ROOT.mkdir(parents=True, exist_ok=True)
tempfile.tempdir = str(TEST_TEMP_ROOT)

for env_name in ("TMP", "TEMP", "TMPDIR"):
    os.environ[env_name] = str(TEST_TEMP_ROOT)


def pytest_sessionfinish(session, exitstatus):
    shutil.rmtree(TEST_TEMP_ROOT, ignore_errors=True)
