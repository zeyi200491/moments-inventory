from __future__ import annotations

from pathlib import Path
import re

from moments_inventory.ai_kefu.products import read_xlsx_rows_from_bytes
from moments_inventory.exporter import _write_workbook


_BRAND_ALIASES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("佳能", ("佳能", "canon")),
    ("索尼", ("索尼", "sony")),
    ("富士", ("富士", "fujifilm", "fuji")),
    ("奥林巴斯", ("奥林巴斯", "olympus")),
    ("柯达", ("柯达", "kodak")),
    ("尼康", ("尼康", "nikon")),
    ("卡西欧", ("卡西欧", "casio")),
    ("三星", ("三星", "samsung")),
    ("松下", ("松下", "panasonic")),
)

SHOWCASE_HEADERS = [
    "商品ID",
    "型号",
    "品牌",
    "成本价",
    "展示价",
    "是否展示",
    "发布时间",
    "来源",
    "原文文案",
    "展示文案",
    "机身图路径",
    "视频路径",
    "出片图型号",
    "备注",
]

_SOURCE_ALIASES: dict[str, tuple[str, ...]] = {
    "型号": ("型号",),
    "价格": ("价格",),
    "状态": ("状态",),
    "备注名": ("备注名", "来源", "来源备注名"),
    "备注名wxid": ("备注名wxid", "来源 wxid", "来源wxid"),
    "发布时间": ("发布时间", "朋友圈发布时间"),
    "序列号": ("序列号", "编号"),
    "图片路径": ("图片路径", "图片本地路径", "机身图路径"),
    "视频路径": ("视频路径", "视频本地路径"),
    "原文文案": ("原文文案", "文案原文"),
    "备注": ("备注",),
    "是否需要人工复核": ("是否需要人工复核", "是否待人工补充"),
}


def normalize_showcase_model_key(value: str) -> str:
    compact = re.sub(r"[\s\-_]+", "", value.strip()).lower()
    for brand, aliases in _BRAND_ALIASES:
        for alias in aliases:
            alias_key = re.sub(r"[\s\-_]+", "", alias).lower()
            if compact.startswith(alias_key):
                return f"{brand}{compact[len(alias_key):]}"
    return compact


def merge_showcase_workbook(source_xlsx: str | Path, manual_xlsx: str | Path) -> Path:
    source_path = Path(source_xlsx)
    manual_path = Path(manual_xlsx)
    manual_path.parent.mkdir(parents=True, exist_ok=True)

    source_rows = _read_rows(source_path)
    manual_rows = _read_rows(manual_path) if manual_path.exists() else []
    existing_by_id = _manual_rows_by_product_id(manual_rows)

    output_rows: list[list[str | int | None]] = [SHOWCASE_HEADERS]
    for source_row in _source_records(source_rows):
        product_id = _build_product_id(source_row)
        old = existing_by_id.get(product_id, {})
        cost_price = _parse_int(source_row["价格"])
        display_copy = old.get("展示文案") or source_row["原文文案"]
        sample_key = old.get("出片图型号") or normalize_showcase_model_key(source_row["型号"])
        output_rows.append(
            [
                product_id,
                source_row["型号"],
                old.get("品牌") or _derive_brand(source_row["型号"]),
                cost_price,
                _parse_int(old.get("展示价")) or cost_price,
                old.get("是否展示") or "是",
                source_row["发布时间"],
                source_row["备注名"],
                source_row["原文文案"],
                display_copy,
                source_row["图片路径"],
                source_row["视频路径"],
                sample_key,
                old.get("备注") or "",
            ]
        )

    _write_workbook(manual_path, output_rows)
    return manual_path


def _read_rows(path: Path) -> list[list[object]]:
    return read_xlsx_rows_from_bytes(path.read_bytes())


def _header_map(header: list[object]) -> dict[str, int]:
    return {str(value or "").strip(): index for index, value in enumerate(header)}


def _canonical_source_map(header: list[object]) -> dict[str, int]:
    raw_map = _header_map(header)
    canonical: dict[str, int] = {}
    for field_name, aliases in _SOURCE_ALIASES.items():
        for alias in aliases:
            if alias in raw_map:
                canonical[field_name] = raw_map[alias]
                break
    return canonical


def _source_records(rows: list[list[object]]) -> list[dict[str, str]]:
    if not rows:
        return []
    canonical = _canonical_source_map(rows[0])
    records: list[dict[str, str]] = []
    for row in rows[1:]:
        model = _get_by_index(row, canonical.get("型号"))
        price = _get_by_index(row, canonical.get("价格"))
        if not model or not price:
            continue
        records.append(
            {
                field_name: _get_by_index(row, canonical.get(field_name))
                for field_name in _SOURCE_ALIASES
            }
        )
    return records


def _manual_rows_by_product_id(rows: list[list[object]]) -> dict[str, dict[str, str]]:
    if not rows:
        return {}
    header = [str(value or "").strip() for value in rows[0]]
    indexes = {name: index for index, name in enumerate(header)}
    product_id_index = indexes.get("商品ID")
    if product_id_index is None:
        return {}

    mapped: dict[str, dict[str, str]] = {}
    for row in rows[1:]:
        product_id = _get_by_index(row, product_id_index)
        if not product_id:
            continue
        mapped[product_id] = {
            header_name: _get_by_index(row, index)
            for header_name, index in indexes.items()
        }
    return mapped


def _build_product_id(source_row: dict[str, str]) -> str:
    parts = [
        source_row["备注名wxid"] or source_row["备注名"],
        source_row["发布时间"],
        source_row["序列号"] or source_row["型号"],
    ]
    return "|".join(part for part in parts if part)


def _derive_brand(model: str) -> str:
    key = normalize_showcase_model_key(model)
    for brand, _ in _BRAND_ALIASES:
        if key.startswith(brand):
            return brand
    return ""


def _parse_int(value: object) -> int | None:
    digits = re.sub(r"[^\d]", "", str(value or ""))
    if not digits:
        return None
    return int(digits)


def _get_by_index(row: list[object], index: int | None) -> str:
    if index is None or index >= len(row):
        return ""
    value = row[index]
    if value is None:
        return ""
    return str(value).strip()
