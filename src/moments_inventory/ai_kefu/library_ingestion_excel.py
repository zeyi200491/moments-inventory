from __future__ import annotations

from moments_inventory.ai_kefu.models import KnowledgeChunk, ProductRecord
from moments_inventory.ai_kefu.products import import_products_from_xlsx_bytes, read_xlsx_rows_from_bytes
from moments_inventory.ai_kefu.structured_imports import build_structured_import_content


def ingest_product_inventory_excel(payload: bytes) -> list[ProductRecord]:
    return import_products_from_xlsx_bytes(payload)


def ingest_product_material_excel(payload: bytes) -> list[KnowledgeChunk]:
    rows = read_xlsx_rows_from_bytes(payload)
    if not rows:
        return []

    header = [str(value or "").strip() for value in rows[0]]
    header_map = {name: index for index, name in enumerate(header)}
    chunks: list[KnowledgeChunk] = []

    for row_index, row in enumerate(rows[1:], start=1):
        product_model = _get_cell(row, header_map, "型号")
        material_type = _get_cell(row, header_map, "素材类型")
        material_url = _get_cell(row, header_map, "素材链接") or _get_cell(row, header_map, "素材地址")
        notes = _get_cell(row, header_map, "备注")
        if not any((product_model, material_type, material_url, notes)):
            continue

        text, tags = build_structured_import_content(
            knowledge_tier="product_material",
            fields={
                "product_model": product_model,
                "material_type": material_type,
                "file_refs": material_url,
                "notes": notes,
            },
        )
        if not text:
            continue

        chunks.append(
            KnowledgeChunk(
                chunk_id=f"product-material-row-{row_index:04d}",
                source_name=f"library:product_material_excel:row-{row_index:04d}",
                category="商品素材",
                knowledge_tier="product_material",
                text=text,
                tags=[_material_tag(material_type), *tags],
            )
        )

    return chunks


def _material_tag(material_type: str) -> str:
    normalized = material_type.strip()
    if "视频" in normalized:
        return "material:inspection_video"
    return "material:real_shot"


def _get_cell(row: list[object], header_map: dict[str, int], header_name: str) -> str:
    index = header_map.get(header_name)
    if index is None or index >= len(row):
        return ""
    value = row[index]
    if value is None:
        return ""
    return str(value).strip()
