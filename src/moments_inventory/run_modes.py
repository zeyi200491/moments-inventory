from __future__ import annotations

import argparse
from pathlib import Path
import re
import zipfile
import xml.etree.ElementTree as ET

import yaml


FIXED_15_WARMUP_TARGETS: tuple[str, ...] = (
    "校长福州申通货源",
    "星火数码库存河南唐山申通货源",
    "阳阳福建福州韵达货源",
    "眠羊库存号河南郑州中通货源",
    "涵涵数码河南货源",
    "大胜山东菏泽中通货源",
    "迪仔河北邯郸申通货源",
    "富婆武汉中通货源",
    "禾宝广东极兔货源",
    "华南广东中通货源",
    "摩托库存号广东中山申通货源",
    "安安天津顺丰货源",
    "菜菜广州中通货源",
    "财团厦门圆通货源",
    "小🐟南京京东货源",
)

FIXED_15_WARMUP_OUTPUT_NAME = "15人warmup无媒体.xlsx"
_SHEET_NS = {"a": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
_CELL_REF_RE = re.compile(r"([A-Z]+)")


def _rewrite_relative_path(raw_value: object, *, base_dir: Path) -> object:
    if not isinstance(raw_value, str) or not raw_value.strip():
        return raw_value
    path = Path(raw_value)
    if path.is_absolute():
        return str(path)
    return str((base_dir / path).resolve())


def _load_base_config(base_config_path: str | Path) -> tuple[Path, Path, dict]:
    base_path = Path(base_config_path)
    base_dir = base_path.parent.resolve()
    raw = yaml.safe_load(base_path.read_text(encoding="utf-8")) or {}
    if not isinstance(raw, dict):
        raise ValueError("config root must be a mapping")
    return base_path, base_dir, raw


def _repo_root_from_base_dir(base_dir: Path) -> Path:
    if base_dir.name.lower() == "config" and base_dir.parent != base_dir:
        return base_dir.parent
    return base_dir


def _normalize_paths(raw: dict, *, base_dir: Path) -> None:
    paths = raw.get("paths")
    if isinstance(paths, dict):
        paths["sqlite_db"] = _rewrite_relative_path(paths.get("sqlite_db"), base_dir=base_dir)
        paths["model_dict"] = _rewrite_relative_path(paths.get("model_dict"), base_dir=base_dir)
        paths["model_catalog_index"] = _rewrite_relative_path(
            paths.get("model_catalog_index", "../data/model_catalog_index.json"),
            base_dir=base_dir,
        )


def _write_config(output_path: Path, raw: dict) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        yaml.safe_dump(raw, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    return output_path


def _extract_cell_value(cell: ET.Element, shared_strings: list[str]) -> str:
    cell_type = cell.get("t")
    if cell_type == "inlineStr":
        return "".join((node.text or "") for node in cell.iterfind(".//a:t", _SHEET_NS))

    value_node = cell.find("a:v", _SHEET_NS)
    if value_node is None:
        return ""

    raw_value = value_node.text or ""
    if cell_type == "s":
        index = int(raw_value)
        if 0 <= index < len(shared_strings):
            return shared_strings[index]
        return ""
    return raw_value


def _column_index_from_ref(cell_ref: str) -> int:
    match = _CELL_REF_RE.match(cell_ref)
    if not match:
        return 0
    letters = match.group(1)
    index = 0
    for char in letters:
        index = index * 26 + (ord(char) - 64)
    return max(index - 1, 0)


def _read_excel_rows(path: Path) -> list[list[str]]:
    with zipfile.ZipFile(path) as workbook:
        shared_strings: list[str] = []
        if "xl/sharedStrings.xml" in workbook.namelist():
            shared_root = ET.fromstring(workbook.read("xl/sharedStrings.xml"))
            for item in shared_root.findall("a:si", _SHEET_NS):
                shared_strings.append(
                    "".join((node.text or "") for node in item.iterfind(".//a:t", _SHEET_NS))
                )

        sheet_root = ET.fromstring(workbook.read("xl/worksheets/sheet1.xml"))
        rows: list[list[str]] = []
        for row in sheet_root.findall("a:sheetData/a:row", _SHEET_NS):
            cell_map: dict[int, str] = {}
            max_index = -1
            for cell in row.findall("a:c", _SHEET_NS):
                cell_ref = cell.get("r", "")
                column_index = _column_index_from_ref(cell_ref)
                cell_map[column_index] = _extract_cell_value(cell, shared_strings)
                max_index = max(max_index, column_index)
            rows.append([cell_map.get(index, "") for index in range(max_index + 1)])
        return rows


def _load_wxid_map_from_excel(path: Path) -> dict[str, str]:
    try:
        rows = _read_excel_rows(path)
    except Exception:
        return {}
    if not rows:
        return {}

    header = rows[0]
    header_aliases = {
        "remark_name": ("备注名", "来源备注名"),
        "wxid": ("备注名wxid", "来源 wxid", "来源wxid"),
    }

    remark_index = -1
    wxid_index = -1
    for alias in header_aliases["remark_name"]:
        if alias in header:
            remark_index = header.index(alias)
            break
    for alias in header_aliases["wxid"]:
        if alias in header:
            wxid_index = header.index(alias)
            break

    if remark_index < 0 or wxid_index < 0:
        return {}

    mapping: dict[str, str] = {}
    for row in rows[1:]:
        if remark_index >= len(row) or wxid_index >= len(row):
            continue
        remark_name = str(row[remark_index]).strip()
        wxid = str(row[wxid_index]).strip()
        if remark_name and wxid and remark_name not in mapping:
            mapping[remark_name] = wxid
    return mapping


def _collect_known_wxids(repo_root: Path) -> dict[str, str]:
    mapping: dict[str, str] = {}
    for output_dir in (repo_root / "output", repo_root / "config" / "output"):
        if not output_dir.exists():
            continue
        excel_files = sorted(output_dir.glob("*.xlsx"), key=lambda item: item.stat().st_mtime, reverse=True)
        for path in excel_files:
            for remark_name, wxid in _load_wxid_map_from_excel(path).items():
                mapping.setdefault(remark_name, wxid)
    return mapping


def _populate_target_wxids(raw: dict, *, repo_root: Path) -> None:
    targets = raw.get("targets")
    if not isinstance(targets, list):
        return

    known_wxids = _collect_known_wxids(repo_root)
    if not known_wxids:
        return

    for target in targets:
        if not isinstance(target, dict):
            continue
        if target.get("wxid"):
            continue
        remark_name = target.get("remark_name")
        if not isinstance(remark_name, str):
            continue
        resolved_wxid = known_wxids.get(remark_name.strip())
        if resolved_wxid:
            target["wxid"] = resolved_wxid


def create_runtime_config(
    base_config_path: str | Path,
    output_config_path: str | Path,
    *,
    output_dir: str | Path | None = None,
    download_media: bool = False,
    skip_timeline_scroll: bool = False,
    timeline_open_observe_ms: int = 1500,
    timeline_open_capture_dir: str | Path | None = None,
) -> Path:
    _, base_dir, raw = _load_base_config(base_config_path)
    output_path = Path(output_config_path)
    repo_root = _repo_root_from_base_dir(base_dir)
    resolved_output_dir = Path(output_dir).resolve() if output_dir else (repo_root / "output").resolve()

    task = raw.setdefault("task", {})
    warmup = raw.setdefault("warmup", {})
    orchestrator = raw.setdefault("orchestrator", {})

    if not isinstance(task, dict) or not isinstance(warmup, dict) or not isinstance(orchestrator, dict):
        raise ValueError("task, warmup, and orchestrator must be mappings")

    task["download_media"] = bool(download_media)
    task["output_dir"] = str(resolved_output_dir)
    warmup["enabled"] = True
    if skip_timeline_scroll:
        warmup["skip_timeline_scroll"] = True
        warmup["timeline_open_observe_ms"] = int(timeline_open_observe_ms)
        if timeline_open_capture_dir:
            warmup["timeline_open_capture_dir"] = str(
                Path(timeline_open_capture_dir).resolve()
            )
    warmup["max_consecutive_failures"] = max(
        int(warmup.get("max_consecutive_failures", 3) or 3),
        len(FIXED_15_WARMUP_TARGETS),
    )
    orchestrator["enabled"] = True

    _normalize_paths(raw, base_dir=base_dir)
    _populate_target_wxids(raw, repo_root=repo_root)
    return _write_config(output_path, raw)


def create_fixed_targets_runtime_config(
    base_config_path: str | Path,
    output_config_path: str | Path,
    *,
    output_dir: str | Path,
) -> Path:
    _, base_dir, raw = _load_base_config(base_config_path)
    output_path = Path(output_config_path)
    repo_root = _repo_root_from_base_dir(base_dir)
    resolved_output_dir = Path(output_dir).resolve()

    raw["targets"] = [
        {"remark_name": target_name, "tier": 1}
        for target_name in FIXED_15_WARMUP_TARGETS
    ]

    task = raw.setdefault("task", {})
    warmup = raw.setdefault("warmup", {})
    orchestrator = raw.setdefault("orchestrator", {})

    if not isinstance(task, dict) or not isinstance(warmup, dict) or not isinstance(orchestrator, dict):
        raise ValueError("task, warmup, and orchestrator must be mappings")

    task["download_media"] = False
    task["output_dir"] = str(resolved_output_dir)
    warmup["enabled"] = True
    orchestrator["enabled"] = True
    orchestrator["mode"] = "priority_only"
    orchestrator["export_priority_after_p1"] = True
    orchestrator["export_full_after_all"] = False
    orchestrator["priority_output_name"] = FIXED_15_WARMUP_OUTPUT_NAME
    orchestrator["full_output_name"] = "unused-full.xlsx"

    _normalize_paths(raw, base_dir=base_dir)
    _populate_target_wxids(raw, repo_root=repo_root)
    return _write_config(output_path, raw)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Prepare runtime config for orchestrated run scripts")
    parser.add_argument("--base-config", required=True, help="base config path")
    parser.add_argument("--output-config", required=True, help="output config path")
    parser.add_argument("--run-output-dir", help="explicit output directory for runtime config")
    parser.add_argument(
        "--download-media",
        action="store_true",
        help="enable media download in the generated runtime config",
    )
    parser.add_argument(
        "--skip-timeline-scroll",
        action="store_true",
        help="confirm popup opening but skip the long timeline wheel scroll",
    )
    parser.add_argument(
        "--timeline-open-observe-ms",
        type=int,
        default=1500,
        help="pause this long after popup confirmation when skipping timeline scroll",
    )
    parser.add_argument(
        "--timeline-open-capture-dir",
        help="save confirmed popup screenshots to this directory in popup-open test mode",
    )
    parser.add_argument(
        "--preset",
        choices=["fixed-15-warmup"],
        help="build a predefined one-off runtime config",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.preset == "fixed-15-warmup":
        if not args.run_output_dir:
            raise SystemExit("--run-output-dir is required when --preset is used")
        create_fixed_targets_runtime_config(
            args.base_config,
            args.output_config,
            output_dir=args.run_output_dir,
        )
        return 0

    create_runtime_config(
        args.base_config,
        args.output_config,
        output_dir=args.run_output_dir,
        download_media=args.download_media,
        skip_timeline_scroll=args.skip_timeline_scroll,
        timeline_open_observe_ms=args.timeline_open_observe_ms,
        timeline_open_capture_dir=args.timeline_open_capture_dir,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
