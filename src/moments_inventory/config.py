from __future__ import annotations

from dataclasses import dataclass, field
import os
from pathlib import Path

import yaml

from moments_inventory.models import TargetContact


class ConfigError(ValueError):
    pass


@dataclass(slots=True)
class WeFlowSettings:
    base_url: str
    timeout_seconds: int = 20
    access_token: str | None = None


@dataclass(slots=True)
class TaskSettings:
    days: int = 30
    merge_window_minutes: int = 10
    output_dir: str = "./output"


@dataclass(slots=True)
class RuleSettings:
    required_fields: list[str] = field(
        default_factory=lambda: ["model", "price", "serial_no"]
    )


@dataclass(slots=True)
class PathSettings:
    sqlite_db: str
    model_dict: str


@dataclass(slots=True)
class WarmupSettings:
    enabled: bool = False
    start_page: str = "contacts"
    search_delay_ms: int = 800
    open_profile_delay_ms: int = 1000
    open_timeline_delay_ms: int = 1200
    scroll_count: int = 4
    scroll_delay_ms: int = 900
    back_delay_ms: int = 600
    max_consecutive_failures: int = 3
    min_success_count: int = 1
    auto_export_on_success: bool = True


@dataclass(slots=True)
class BatchRunSettings:
    enabled: bool = False
    batch_size: int = 25
    stop_on_batch_failure: bool = True
    export_only_when_all_batches_succeed: bool = True
    keep_batch_temp_reports: bool = True


@dataclass(slots=True)
class Settings:
    weflow: WeFlowSettings
    task: TaskSettings
    targets: list[TargetContact]
    rules: RuleSettings
    paths: PathSettings
    warmup: WarmupSettings = field(default_factory=WarmupSettings)
    batch_run: BatchRunSettings = field(default_factory=BatchRunSettings)
    model_keywords: list[str] = field(default_factory=list)


_WARMUP_BOOL_FIELDS = {"enabled", "auto_export_on_success"}
_WARMUP_INT_FIELDS = {
    "search_delay_ms",
    "open_profile_delay_ms",
    "open_timeline_delay_ms",
    "scroll_count",
    "scroll_delay_ms",
    "back_delay_ms",
    "max_consecutive_failures",
    "min_success_count",
}
_WARMUP_ALLOWED_KEYS = _WARMUP_BOOL_FIELDS | _WARMUP_INT_FIELDS | {"start_page"}
_WARMUP_ALLOWED_START_PAGES = {"contacts", "chat_list"}
_BATCH_RUN_BOOL_FIELDS = {
    "enabled",
    "stop_on_batch_failure",
    "export_only_when_all_batches_succeed",
    "keep_batch_temp_reports",
}
_BATCH_RUN_INT_FIELDS = {"batch_size"}
_BATCH_RUN_ALLOWED_KEYS = _BATCH_RUN_BOOL_FIELDS | _BATCH_RUN_INT_FIELDS


def _expect_mapping(value: object, path: str) -> dict:
    if not isinstance(value, dict):
        raise ConfigError(f"{path} 必须是对象")
    return value


def _expect_list(value: object, path: str) -> list:
    if not isinstance(value, list):
        raise ConfigError(f"{path} 必须是数组")
    return value


def _validate_keys(
    path: str,
    data: dict,
    required_keys: set[str],
    optional_keys: set[str] | None = None,
) -> None:
    optional_keys = optional_keys or set()
    allowed_keys = required_keys | optional_keys

    for key in sorted(data.keys() - allowed_keys):
        raise ConfigError(f"存在未知配置字段: {path}.{key}")
    for key in sorted(required_keys - set(data.keys())):
        raise ConfigError(f"缺少必填配置字段: {path}.{key}")


def _expect_non_empty_string(value: object, path: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ConfigError(f"{path} 必须是非空字符串")
    return value.strip()


def _expect_positive_int(value: object, path: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise ConfigError(f"{path} 必须是正整数")
    return value


def _expect_bool(value: object, path: str) -> bool:
    if not isinstance(value, bool):
        raise ConfigError(f"{path} 必须是布尔值")
    return value


def _expect_string_list(value: object, path: str) -> list[str]:
    items = _expect_list(value, path)
    normalized: list[str] = []
    for index, item in enumerate(items):
        normalized.append(_expect_non_empty_string(item, f"{path}[{index}]"))
    return normalized


def _read_model_keywords(path: Path) -> list[str]:
    return [
        line.strip().lower()
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _resolve_path(base_dir: Path, raw_path: str) -> str:
    path = Path(raw_path)
    if path.is_absolute():
        return str(path)
    return str((base_dir / path).resolve())


def _resolve_access_token(raw_value: str | None) -> str | None:
    if raw_value and raw_value.strip():
        return raw_value.strip()
    env_value = os.environ.get("WEFLOW_ACCESS_TOKEN", "").strip()
    return env_value or None


def _validate_targets(raw_targets: object) -> list[TargetContact]:
    targets = _expect_list(raw_targets, "targets")
    normalized: list[TargetContact] = []
    for index, raw_target in enumerate(targets):
        path = f"targets[{index}]"
        target = _expect_mapping(raw_target, path)
        _validate_keys(path, target, set(), {"remark_name", "wxid"})
        remark_name = target.get("remark_name")
        wxid = target.get("wxid")
        if remark_name is not None and not isinstance(remark_name, str):
            raise ConfigError(f"{path}.remark_name 必须是字符串")
        if wxid is not None and not isinstance(wxid, str):
            raise ConfigError(f"{path}.wxid 必须是字符串")
        normalized.append(
            TargetContact(
                remark_name=remark_name.strip() or None if isinstance(remark_name, str) else None,
                wxid=wxid.strip() or None if isinstance(wxid, str) else None,
            )
        )
    return normalized


def _parse_warmup_settings(raw_warmup: object | None) -> WarmupSettings:
    defaults = WarmupSettings()
    warmup_raw = _expect_mapping({} if raw_warmup is None else raw_warmup, "warmup")
    _validate_keys("warmup", warmup_raw, set(), _WARMUP_ALLOWED_KEYS)

    start_page = _expect_non_empty_string(
        warmup_raw.get("start_page", defaults.start_page),
        "warmup.start_page",
    )
    if start_page not in _WARMUP_ALLOWED_START_PAGES:
        raise ConfigError("warmup.start_page 只能是 contacts 或 chat_list")

    parsed_values: dict[str, object] = {"start_page": start_page}

    for field_name in sorted(_WARMUP_BOOL_FIELDS):
        parsed_values[field_name] = _expect_bool(
            warmup_raw.get(field_name, getattr(defaults, field_name)),
            f"warmup.{field_name}",
        )

    for field_name in sorted(_WARMUP_INT_FIELDS):
        parsed_values[field_name] = _expect_positive_int(
            warmup_raw.get(field_name, getattr(defaults, field_name)),
            f"warmup.{field_name}",
        )

    return WarmupSettings(**parsed_values)


def _parse_batch_run_settings(raw_batch_run: object | None) -> BatchRunSettings:
    defaults = BatchRunSettings()
    batch_run_raw = _expect_mapping(
        {} if raw_batch_run is None else raw_batch_run,
        "batch_run",
    )
    _validate_keys("batch_run", batch_run_raw, set(), _BATCH_RUN_ALLOWED_KEYS)

    parsed_values: dict[str, object] = {}

    for field_name in sorted(_BATCH_RUN_BOOL_FIELDS):
        parsed_values[field_name] = _expect_bool(
            batch_run_raw.get(field_name, getattr(defaults, field_name)),
            f"batch_run.{field_name}",
        )

    for field_name in sorted(_BATCH_RUN_INT_FIELDS):
        parsed_values[field_name] = _expect_positive_int(
            batch_run_raw.get(field_name, getattr(defaults, field_name)),
            f"batch_run.{field_name}",
        )

    return BatchRunSettings(**parsed_values)


def load_settings(path: str | Path) -> Settings:
    config_path = Path(path)
    raw = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    raw = _expect_mapping(raw, "config")
    _validate_keys(
        raw_path := "config",
        raw,
        {"weflow", "task", "targets", "rules", "paths"},
        {"warmup", "batch_run"},
    )
    base_dir = config_path.parent.resolve()

    weflow_raw = _expect_mapping(raw["weflow"], "weflow")
    _validate_keys("weflow", weflow_raw, {"base_url"}, {"timeout_seconds", "access_token"})

    task_raw = _expect_mapping(raw["task"], "task")
    _validate_keys("task", task_raw, {"days", "merge_window_minutes", "output_dir"})

    rules_raw = _expect_mapping(raw["rules"], "rules")
    _validate_keys("rules", rules_raw, {"required_fields"})

    paths_raw = _expect_mapping(raw["paths"], "paths")
    _validate_keys("paths", paths_raw, {"sqlite_db", "model_dict"})

    model_path = Path(_resolve_path(base_dir, _expect_non_empty_string(paths_raw["model_dict"], "paths.model_dict")))
    sqlite_db = _resolve_path(base_dir, _expect_non_empty_string(paths_raw["sqlite_db"], "paths.sqlite_db"))
    output_dir = _resolve_path(base_dir, _expect_non_empty_string(task_raw["output_dir"], "task.output_dir"))

    return Settings(
        weflow=WeFlowSettings(
            base_url=_expect_non_empty_string(weflow_raw["base_url"], "weflow.base_url"),
            timeout_seconds=_expect_positive_int(
                weflow_raw.get("timeout_seconds", 20),
                "weflow.timeout_seconds",
            ),
            access_token=_resolve_access_token(weflow_raw.get("access_token")),
        ),
        task=TaskSettings(
            days=_expect_positive_int(task_raw["days"], "task.days"),
            merge_window_minutes=_expect_positive_int(
                task_raw["merge_window_minutes"],
                "task.merge_window_minutes",
            ),
            output_dir=output_dir,
        ),
        targets=_validate_targets(raw["targets"]),
        rules=RuleSettings(
            required_fields=_expect_string_list(
                rules_raw["required_fields"],
                "rules.required_fields",
            )
        ),
        paths=PathSettings(sqlite_db=sqlite_db, model_dict=str(model_path)),
        warmup=_parse_warmup_settings(raw.get("warmup")),
        batch_run=_parse_batch_run_settings(raw.get("batch_run")),
        model_keywords=_read_model_keywords(model_path),
    )
