from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
from typing import Iterable

import openpyxl


REQUIRED_HEADERS = {"品牌", "统一物理机型/规范名", "欧亚/中国常见名", "传感器"}
OUTPUT_ROOT = Path(r"E:\Ai jjfajgsw\AIkefu\output\ccdcpt")
TARGET_IMAGES_PER_MODEL = 7
XHS_HOME_URL = "https://www.xiaohongshu.com"


class ExcelFormatError(ValueError):
    pass


@dataclass(frozen=True)
class ModelTask:
    brand: str
    brand_dir: str
    model_name: str
    canonical_name: str
    common_name: str
    search_query: str
    output_dir: Path


def clean_cell(value: object) -> str:
    if value is None:
        return ""
    return str(value).strip()


def extract_chinese_brand(raw_brand: str) -> str:
    chinese = "".join(re.findall(r"[\u4e00-\u9fff]+", raw_brand))
    return chinese or safe_path_part(raw_brand) or "未知品牌"


def safe_path_part(value: str) -> str:
    cleaned = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", value.strip())
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" .")
    return cleaned or "未命名"


def header_map(headers: Iterable[object]) -> dict[str, int]:
    mapping = {clean_cell(value): index for index, value in enumerate(headers)}
    missing = sorted(REQUIRED_HEADERS - set(mapping))
    if missing:
        raise ExcelFormatError(f"Excel 缺少必要字段：{', '.join(missing)}")
    return mapping


def load_model_tasks(excel_path: str | Path, output_root: Path = OUTPUT_ROOT) -> list[ModelTask]:
    path = Path(excel_path)
    workbook = openpyxl.load_workbook(path, read_only=True, data_only=True)
    sheet = workbook.worksheets[0]
    rows = sheet.iter_rows(values_only=True)
    try:
        headers = next(rows)
    except StopIteration as exc:
        raise ExcelFormatError("Excel 第一个工作表为空") from exc

    columns = header_map(headers)
    tasks: list[ModelTask] = []
    seen: set[tuple[str, str]] = set()

    for row in rows:
        sensor = clean_cell(row[columns["传感器"]]).upper()
        if sensor != "CCD":
            continue

        brand = clean_cell(row[columns["品牌"]])
        canonical_name = clean_cell(row[columns["统一物理机型/规范名"]])
        common_name = clean_cell(row[columns["欧亚/中国常见名"]])
        model_name = common_name or canonical_name
        if not model_name:
            continue

        brand_dir = extract_chinese_brand(brand)
        safe_brand = safe_path_part(brand_dir)
        safe_model = safe_path_part(model_name)
        dedupe_key = (safe_brand.casefold(), safe_model.casefold())
        if dedupe_key in seen:
            continue
        seen.add(dedupe_key)

        tasks.append(
            ModelTask(
                brand=brand,
                brand_dir=safe_brand,
                model_name=model_name,
                canonical_name=canonical_name,
                common_name=common_name,
                search_query=f"{model_name} 出片图",
                output_dir=output_root / safe_brand / safe_model,
            )
        )

    return tasks
