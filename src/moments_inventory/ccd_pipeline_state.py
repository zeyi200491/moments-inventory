from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile
from typing import Any
from uuid import uuid4


class PipelineStateError(RuntimeError):
    """CCD 流程状态无法安全读取或保存。"""


_SENSITIVE_PARTS = ("password", "token", "cookie", "secret", "authorization")
_RUN_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{1,80}$")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _assert_no_sensitive_keys(value: Any) -> None:
    if isinstance(value, dict):
        for key, nested in value.items():
            if any(part in str(key).casefold() for part in _SENSITIVE_PARTS):
                raise PipelineStateError("运行状态包含禁止保存的敏感字段名称")
            _assert_no_sensitive_keys(nested)
    elif isinstance(value, list):
        for nested in value:
            _assert_no_sensitive_keys(nested)


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


class RunStateStore:
    """将每次 CCD 发布流程状态以原子 JSON 文件持久化。"""

    def __init__(self, root: str | Path):
        self.root = Path(root).resolve()

    def path_for(self, run_id: str) -> Path:
        if not _RUN_ID_PATTERN.fullmatch(str(run_id)):
            raise PipelineStateError("运行编号格式无效")
        return self.root / f"{run_id}.json"

    def create_run(self, *, environment: dict[str, Any], target: dict[str, Any]) -> dict[str, Any]:
        now = _now()
        return {
            "schema_version": 1,
            "run_id": uuid4().hex,
            "created_at": now,
            "updated_at": now,
            "environment": environment,
            "target": target,
            "current_stage": "preflight",
            "status": "running",
            "stages": {},
        }

    def save_run(self, run_state: dict[str, Any]) -> None:
        _assert_no_sensitive_keys(run_state)
        run_id = str(run_state.get("run_id", ""))
        destination = self.path_for(run_id)
        destination.parent.mkdir(parents=True, exist_ok=True)
        run_state["updated_at"] = _now()
        payload = json.dumps(run_state, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
        temporary_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w", encoding="utf-8", newline="\n", dir=destination.parent,
                prefix=f".{run_id}.", suffix=".tmp", delete=False,
            ) as temporary:
                temporary.write(payload)
                temporary.flush()
                os.fsync(temporary.fileno())
                temporary_path = Path(temporary.name)
            try:
                os.chmod(temporary_path, 0o600)
            except OSError:
                pass
            os.replace(temporary_path, destination)
        except OSError as exc:
            if temporary_path is not None:
                temporary_path.unlink(missing_ok=True)
            raise PipelineStateError("运行状态无法原子保存") from exc

    def load_run(self, run_id: str) -> dict[str, Any]:
        path = self.path_for(run_id)
        try:
            state = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError as exc:
            raise PipelineStateError("未找到指定的运行状态") from exc
        except (OSError, json.JSONDecodeError) as exc:
            raise PipelineStateError("运行状态损坏或不可读取，原文件已保留") from exc
        if not isinstance(state, dict) or state.get("run_id") != run_id or state.get("schema_version") != 1:
            raise PipelineStateError("运行状态编号或版本不匹配")
        _assert_no_sensitive_keys(state)
        return state
