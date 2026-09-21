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
        copy = record['展示文案'] or record['原文文案']
        records.append(dict(product_id=product_id, model=record['型号'], brand=normalize_showcase_brand(record['品牌'], record['型号'], record['原文文案'], copy), cost_price=_parse_int(record['成本价']), source_display_price=_parse_int(record['展示价']), source_display_copy=copy, source_visible=record['是否展示'] == '是', published_at=record['发布时间'], raw_copy=record['原文文案'], cover_image_path=record['机身图路径']))
    return records


def _parse_int(value):
    try:
        amount = Decimal(str(value))
        if not amount.is_finite() or amount < 0 or amount != amount.to_integral_value() or amount > 9223372036854775807:
            raise ValueError('价格必须是非负整数元')
        return int(amount)
    except InvalidOperation as exc:
        raise ValueError(f'无效价格：{value}') from exc
