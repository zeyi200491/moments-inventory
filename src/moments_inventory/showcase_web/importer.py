from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import uuid

from moments_inventory.ai_kefu.products import read_xlsx_rows_from_bytes
from moments_inventory.showcase_web.models import ShowcaseImportResult, ShowcaseProduct
from moments_inventory.showcase_web.repository import SQLiteShowcaseRepository


def import_showcase_workbook(
    workbook_path: str | Path,
    repository: SQLiteShowcaseRepository,
) -> ShowcaseImportResult:
    path = Path(workbook_path)
    rows = read_xlsx_rows_from_bytes(path.read_bytes())
    import_id = uuid.uuid4().hex
    imported_at = datetime.now(timezone.utc).isoformat()
    existing_ids = repository.list_product_ids()
    seen_ids: set[str] = set()
    inserted_count = 0
    updated_count = 0

    for record in _manual_records(rows):
        product_id = record["商品ID"]
        if not product_id:
            continue
        existing = repository.get_product(product_id)
        product = _record_to_product(
            record,
            existing=existing,
            import_id=import_id,
            imported_at=imported_at,
        )
        repository.upsert_product(product)
        body_image_path = record["机身图路径"]
        if body_image_path:
            repository.add_product_image(
                f"{product_id}|body|0",
                product_id,
                body_image_path,
                "body",
                0,
                True,
            )
        if existing is None:
            inserted_count += 1
        else:
            updated_count += 1
        seen_ids.add(product_id)

    missing_count = len(existing_ids - seen_ids)
    repository.save_import_log(
        import_id=import_id,
        source_path=str(path),
        imported_at=imported_at,
        inserted_count=inserted_count,
        updated_count=updated_count,
        missing_count=missing_count,
    )
    return ShowcaseImportResult(
        import_id=import_id,
        inserted_count=inserted_count,
        updated_count=updated_count,
        missing_count=missing_count,
    )


def _manual_records(rows: list[list[object]]) -> list[dict[str, str]]:
    if not rows:
        return []
    header = [str(value or "").strip() for value in rows[0]]
    indexes = {name: index for index, name in enumerate(header)}
    records: list[dict[str, str]] = []
    for row in rows[1:]:
        records.append(
            {
                name: _get_by_index(row, indexes.get(name))
                for name in header
            }
        )
    return records


def _record_to_product(
    record: dict[str, str],
    *,
    existing: ShowcaseProduct | None,
    import_id: str,
    imported_at: str,
) -> ShowcaseProduct:
    display_copy = record["展示文案"] or record["原文文案"]
    if existing is not None and existing.display_copy:
        display_copy = existing.display_copy

    return ShowcaseProduct(
        product_id=record["商品ID"],
        model=record["型号"],
        brand=record["品牌"],
        cost_price=_parse_int(record["成本价"]),
        display_price=(
            existing.display_price
            if existing is not None
            else _parse_int(record["展示价"])
        ),
        visible=(
            existing.visible
            if existing is not None
            else record["是否展示"].strip() == "是"
        ),
        sold=existing.sold if existing is not None else False,
        published_at=record["发布时间"],
        raw_copy=record["原文文案"],
        display_copy=display_copy,
        cover_image_path=record["机身图路径"] or (existing.cover_image_path if existing else ""),
        created_at=existing.created_at if existing is not None else imported_at,
        updated_at=imported_at,
        last_seen_import_id=import_id,
    )


def _get_by_index(row: list[object], index: int | None) -> str:
    if index is None or index >= len(row):
        return ""
    return str(row[index] or "").strip()


def _parse_int(value: object) -> int:
    if isinstance(value, int):
        return value
    text = str(value or "").strip()
    if not text:
        return 0
    try:
        return int(float(text))
    except ValueError:
        return 0
