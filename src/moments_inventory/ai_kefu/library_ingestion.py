from __future__ import annotations

from dataclasses import dataclass, field

from moments_inventory.ai_kefu.library_ingestion_excel import (
    ingest_product_inventory_excel,
    ingest_product_material_excel,
)
from moments_inventory.ai_kefu.library_ingestion_markdown import split_master_rule_bundle_markdown
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
            markdown_text=payload.decode("utf-8"),
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
        product_records = ingest_product_inventory_excel(payload)
        return LibraryImportResult(
            library_type=library_type,
            product_records=product_records,
            imported_count=len(product_records),
        )

    if library_type in {"shipping_info_excel", "style_sample_md"}:
        return LibraryImportResult(library_type=library_type)

    raise ValueError(f"不支持的业务库类型: {library_type} ({filename})")
