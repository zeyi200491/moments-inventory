from __future__ import annotations

from dataclasses import dataclass
import zipfile
from typing import Callable, TypeVar
from xml.etree.ElementTree import ParseError

from moments_inventory.ai_kefu.models import KnowledgeChunk, ProductRecord
from moments_inventory.ai_kefu.products import (
    import_products_from_rows,
    import_products_from_xlsx_bytes,
    read_xlsx_rows_from_bytes,
)
from moments_inventory.ai_kefu.structured_imports import build_structured_import_content
from moments_inventory.exporter import HEADERS


T = TypeVar("T")


@dataclass(slots=True)
class ProductInventoryImportResult:
    product_records: list[ProductRecord]
    knowledge_chunks: list[KnowledgeChunk]


def ingest_product_inventory_excel(payload: bytes) -> ProductInventoryImportResult:
    rows = _load_excel_rows(
        payload=payload,
        loader=read_xlsx_rows_from_bytes,
    )
    return ProductInventoryImportResult(
        product_records=import_products_from_rows(rows),
        knowledge_chunks=_build_inventory_material_chunks(rows),
    )


def ingest_product_material_excel(payload: bytes) -> list[KnowledgeChunk]:
    rows = _load_excel_rows(
        payload=payload,
        loader=read_xlsx_rows_from_bytes,
    )
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


def _build_inventory_material_chunks(rows: list[list[object]]) -> list[KnowledgeChunk]:
    if not rows:
        return []

    header = [str(value or "").strip() for value in rows[0]]
    header_map = {name: index for index, name in enumerate(header)}
    chunks: list[KnowledgeChunk] = []

    for row_index, row in enumerate(rows[1:], start=1):
        product_model = _get_cell(row, header_map, HEADERS[0])
        image_path = _get_cell(row, header_map, HEADERS[7])
        video_path = _get_cell(row, header_map, HEADERS[8])
        raw_copy = _get_cell(row, header_map, HEADERS[9])
        notes = _get_cell(row, header_map, HEADERS[10])
        material_type = _build_inventory_material_type(image_path, video_path, raw_copy)
        if not product_model or not material_type:
            continue

        file_refs = "\n".join(path for path in (image_path, video_path) if path)
        text, tags = build_structured_import_content(
            knowledge_tier="product_material",
            fields={
                "product_model": product_model,
                "material_type": material_type,
                "file_refs": file_refs,
                "highlights": raw_copy,
                "notes": notes,
            },
        )
        if not text:
            continue

        chunks.append(
            KnowledgeChunk(
                chunk_id=f"product-inventory-material-row-{row_index:04d}",
                source_name=f"library:product_inventory_excel:row-{row_index:04d}",
                category="商品素材",
                knowledge_tier="product_material",
                text=text,
                tags=_build_inventory_material_tags(material_type, tags),
            )
        )

    return chunks


def _build_inventory_material_type(image_path: str, video_path: str, raw_copy: str) -> str:
    material_types: list[str] = []
    if image_path.strip():
        material_types.append("实拍图")
    if video_path.strip():
        material_types.append("验机视频")
    if raw_copy.strip() and not material_types:
        material_types.append("商品文案")
    return "、".join(material_types)


def _build_inventory_material_tags(material_type: str, tags: list[str]) -> list[str]:
    material_tags: list[str] = []
    if "验机视频" in material_type:
        material_tags.append("material:inspection_video")
    if "实拍图" in material_type:
        material_tags.append("material:real_shot")
    if "商品文案" in material_type:
        material_tags.append("material:copywriting")
    return [*material_tags, *tags]


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


def _load_excel_rows(payload: bytes, loader: Callable[[bytes], T]) -> T:
    try:
        return loader(payload)
    except (IndexError, KeyError, ParseError, ValueError, zipfile.BadZipFile) as exc:
        raise ValueError("Excel 文件无法解析，请重新导出后再上传") from exc
