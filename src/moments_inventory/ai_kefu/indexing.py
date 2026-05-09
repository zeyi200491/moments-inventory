from __future__ import annotations

import hashlib

from moments_inventory.ai_kefu.models import KnowledgeChunk, KnowledgeTier


def _build_chunk_id(
    source_name: str,
    category: str,
    start: int,
    end: int,
    text: str,
) -> str:
    digest = hashlib.sha256(
        f"{source_name}\n{category}\n{start}\n{end}\n{text}".encode("utf-8")
    ).hexdigest()
    return f"chunk-{digest[:24]}"


def split_document_to_chunks(
    source_name: str,
    category: str,
    text: str,
    chunk_size: int,
    chunk_overlap: int,
    knowledge_tier: KnowledgeTier | None = None,
) -> list[KnowledgeChunk]:
    if chunk_size <= 0:
        raise ValueError("chunk_size 必须大于 0")
    if chunk_overlap < 0:
        raise ValueError("chunk_overlap 不能小于 0")
    if chunk_overlap >= chunk_size:
        raise ValueError("chunk_overlap 必须小于 chunk_size")
    if not text:
        return []

    step = chunk_size - chunk_overlap
    chunks: list[KnowledgeChunk] = []

    for start in range(0, len(text), step):
        chunk_text = text[start : start + chunk_size]
        if not chunk_text:
            continue
        end = start + len(chunk_text)
        chunks.append(
            KnowledgeChunk(
                chunk_id=_build_chunk_id(source_name, category, start, end, chunk_text),
                source_name=source_name,
                category=category,
                knowledge_tier=knowledge_tier,
                text=chunk_text,
            )
        )
        if end >= len(text):
            break

    return chunks
