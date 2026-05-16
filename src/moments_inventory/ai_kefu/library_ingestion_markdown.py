from __future__ import annotations

import re

from moments_inventory.ai_kefu.indexing import split_document_to_chunks
from moments_inventory.ai_kefu.models import KnowledgeChunk


_FAQ_HEADING_PATTERN = re.compile(r"^##\s*(常见问题|FAQ)\s*$", re.IGNORECASE | re.MULTILINE)
_STYLE_SAMPLE_CATEGORY = "回复风格"


def split_master_rule_bundle_markdown(
    *,
    markdown_text: str,
    chunk_size: int,
    chunk_overlap: int,
) -> list[KnowledgeChunk]:
    master_rule_text, faq_text = _split_master_rule_sections(markdown_text)
    chunks: list[KnowledgeChunk] = []

    if faq_text:
        chunks.extend(
            split_document_to_chunks(
                source_name="library:master_rule_bundle:faq",
                category="FAQ",
                text=faq_text,
                chunk_size=chunk_size,
                chunk_overlap=chunk_overlap,
                knowledge_tier="faq",
            )
        )
    if master_rule_text:
        chunks.extend(
            split_document_to_chunks(
                source_name="library:master_rule_bundle:master_rule",
                category="主规则",
                text=master_rule_text,
                chunk_size=chunk_size,
                chunk_overlap=chunk_overlap,
                knowledge_tier="master_rule",
            )
        )
    return chunks


def split_style_sample_markdown(
    *,
    markdown_text: str,
    chunk_size: int,
    chunk_overlap: int,
) -> list[KnowledgeChunk]:
    normalized = markdown_text.strip()
    if not normalized:
        return []
    return split_document_to_chunks(
        source_name="library:style_sample_md",
        category=_STYLE_SAMPLE_CATEGORY,
        text=normalized,
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
        knowledge_tier="style_sample",
    )


def _split_master_rule_sections(markdown_text: str) -> tuple[str, str]:
    normalized = markdown_text.strip()
    if not normalized:
        return "", ""

    match = _FAQ_HEADING_PATTERN.search(normalized)
    if match is None:
        return normalized, ""

    master_rule_text = normalized[: match.start()].strip()
    faq_text = normalized[match.end() :].strip()
    return master_rule_text, faq_text
