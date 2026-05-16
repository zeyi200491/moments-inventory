from __future__ import annotations

from dataclasses import dataclass, field

from moments_inventory.ai_kefu.library_ingestion_excel import (
    ingest_product_inventory_excel,
    ingest_product_material_excel,
    ingest_shipping_info_excel,
)
from moments_inventory.ai_kefu.library_ingestion_markdown import (
    split_master_rule_bundle_markdown,
    split_style_sample_markdown,
)
from moments_inventory.ai_kefu.models import KnowledgeChunk, LibraryType, ProductRecord


@dataclass(slots=True)
class LibraryImportResult:
    library_type: LibraryType
    knowledge_chunks: list[KnowledgeChunk] = field(default_factory=list)
    product_records: list[ProductRecord] = field(default_factory=list)
    imported_count: int = 0
    skipped_count: int = 0


def ingest_library_bytes(
    *,
    library_type: LibraryType,
    filename: str,
    payload: bytes,
    chunk_size: int,
    chunk_overlap: int,
) -> LibraryImportResult:
    if library_type == "master_rule_bundle":
        knowledge_chunks = split_master_rule_bundle_markdown(
            markdown_text=_decode_markdown_payload(payload, filename, "主规则文件"),
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
        )
        return LibraryImportResult(
            library_type=library_type,
            knowledge_chunks=sorted(knowledge_chunks, key=lambda chunk: chunk.source_name),
            imported_count=len(knowledge_chunks),
        )

    if library_type == "product_material_excel":
        knowledge_chunks = ingest_product_material_excel(payload)
        return LibraryImportResult(
            library_type=library_type,
            knowledge_chunks=knowledge_chunks,
            imported_count=len(knowledge_chunks),
        )

    if library_type == "product_inventory_excel":
        result = ingest_product_inventory_excel(payload)
        return LibraryImportResult(
            library_type=library_type,
            knowledge_chunks=result.knowledge_chunks,
            product_records=result.product_records,
            imported_count=len(result.product_records),
        )

    if library_type == "style_sample_md":
        knowledge_chunks = split_style_sample_markdown(
            markdown_text=_decode_markdown_payload(payload, filename, "风格样本库文件"),
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
        )
        return LibraryImportResult(
            library_type=library_type,
            knowledge_chunks=knowledge_chunks,
            imported_count=len(knowledge_chunks),
        )

    if library_type == "shipping_info_excel":
        knowledge_chunks = ingest_shipping_info_excel(payload)
        return LibraryImportResult(
            library_type=library_type,
            knowledge_chunks=knowledge_chunks,
            imported_count=len(knowledge_chunks),
        )

    raise ValueError(f"不支持的业务库类型：{library_type}（{filename}）")


def _decode_markdown_payload(payload: bytes, filename: str, library_label: str) -> str:
    try:
        return payload.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError(f"{library_label}必须是 UTF-8 编码的 Markdown：{filename}") from exc
