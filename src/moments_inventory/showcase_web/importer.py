from __future__ import annotations

from decimal import Decimal, InvalidOperation
from pathlib import Path

from moments_inventory.xlsx_reader import read_xlsx_rows_from_bytes
from moments_inventory.showcase_brands import normalize_showcase_brand
from moments_inventory.showcase_web.import_service import prepare_import, commit_import
from moments_inventory.showcase_web.models import ShowcaseImportResult
from moments_inventory.showcase_web.repository import SQLiteShowcaseRepository


_REQUIRED_HEADERS = ('商品ID', '型号', '品牌', '成本价', '展示价', '是否展示', '发布时间', '原文文案', '展示文案', '机身图路径')


def preview_showcase_workbook(workbook_path, repository, *, mode='incremental', scope='default', complete=False, max_missing_fraction=0.3):
    """先校验全表并冻结来源及版本，预览期间不写入数据库。"""
    path = Path(workbook_path)
    content = path.read_bytes()
    records = _manual_records(read_xlsx_rows_from_bytes(content))
    return prepare_import(repository, records, content=content, source_path=str(path), mode=mode, scope=scope, complete=complete, max_missing_fraction=max_missing_fraction)


def import_showcase_workbook(workbook_path: str | Path, repository: SQLiteShowcaseRepository, *, mode='incremental', scope='default', complete=False, max_missing_fraction=0.3) -> ShowcaseImportResult:
    preview = preview_showcase_workbook(workbook_path, repository, mode=mode, scope=scope, complete=complete, max_missing_fraction=max_missing_fraction)
    return commit_import(repository, preview)


def parse_review_workbook(content: bytes) -> list[dict]:
    """解析复核工作簿并保留 Excel 行号；单行错误作为复核问题返回。"""
    rows = read_xlsx_rows_from_bytes(content)
    if not rows:
        raise ValueError('Excel 缺少表头')
    header = [str(value or '').strip() for value in rows[0]]
    if len(header) != len(set(header)) or not set(_REQUIRED_HEADERS).issubset(header):
        raise ValueError('Excel 表头缺失或重复')
    parsed = []
    ids: dict[str, list[int]] = {}
    for number, row in enumerate(rows[1:], start=2):
        if not any(value not in ('', None) for value in row):
            continue
        raw = {
            name: str(row[index] if index < len(row) and row[index] is not None else '').strip()
            for index, name in enumerate(header)
        }
        try:
            record = _manual_records([header, row])[0]
            record_errors = []
        except (ValueError, IndexError) as exc:
            record = None
            record_errors = [str(exc)]
        source_key = raw.get('来源商品键', raw.get('product_key', '')).strip()
        errors = list(record_errors)
        if len(source_key) > 256 or any(ord(character) < 32 for character in source_key):
            errors.append(f'第 {number} 行来源商品键无效')
        product_id = raw.get('商品ID', '').strip()
        if product_id:
            ids.setdefault(product_id, []).append(len(parsed))
        parsed.append({
            'row_number': number,
            'source_key': source_key,
            'snapshot': record if record is not None else {'raw': raw},
            'errors': errors,
        })
    # 复核批次保留重复目标行并显式报错；正式 CLI 导入仍由 _manual_records 原样拒绝。
    for product_id, indexes in ids.items():
        if len(indexes) > 1:
            for index in indexes:
                parsed[index]['errors'].append(f'工作簿商品ID重复：{product_id}')
    return parsed


def _manual_records(rows):
    if not rows:
        raise ValueError('Excel 缺少表头')
    header = [str(value or '').strip() for value in rows[0]]
    if len(header) != len(set(header)) or not set(_REQUIRED_HEADERS).issubset(header):
        raise ValueError('Excel 表头缺失或重复')
    records = []
    seen = set()
    for number, row in enumerate(rows[1:], start=2):
        if not any(value not in ('', None) for value in row):
            continue
        record = {name: str(row[index] if index < len(row) and row[index] is not None else '').strip() for index, name in enumerate(header)}
        product_id = record['商品ID']
        if not product_id or product_id in seen:
            raise ValueError(f'第 {number} 行商品ID为空或重复')
        if record['是否展示'] not in ('是', '否'):
            raise ValueError(f'第 {number} 行是否展示必须为是或否')
        seen.add(product_id)
        source_product_key = record.get('来源商品键', record.get('product_key', '')).strip()
        if len(source_product_key) > 256 or any(ord(character) < 32 for character in source_product_key):
            raise ValueError(f'第 {number} 行来源商品键无效')
        copy = record['展示文案'] or record['原文文案']
        image_paths = list(dict.fromkeys(
            path.strip() for path in record['机身图路径'].splitlines() if path.strip()
        ))
        records.append(dict(product_id=product_id, source_product_key=source_product_key, model=record['型号'], brand=normalize_showcase_brand(record['品牌'], record['型号'], record['原文文案'], copy), cost_price=_parse_int(record['成本价']), source_display_price=_parse_int(record['展示价']), source_display_copy=copy, source_visible=record['是否展示'] == '是', published_at=record['发布时间'], raw_copy=record['原文文案'], cover_image_path=image_paths[0] if image_paths else '', body_image_paths=image_paths))
    return records


def _parse_int(value):
    try:
        amount = Decimal(str(value))
        if not amount.is_finite() or amount < 0 or amount != amount.to_integral_value() or amount > 9223372036854775807:
            raise ValueError('价格必须是非负整数元')
        return int(amount)
    except InvalidOperation as exc:
        raise ValueError(f'无效价格：{value}') from exc
