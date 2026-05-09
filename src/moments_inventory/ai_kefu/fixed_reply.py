from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from moments_inventory.ai_kefu.models import KnowledgeChunk
from moments_inventory.ai_kefu.workflow import WorkflowAnalysis


FIXED_REPLY_KNOWLEDGE_CATEGORIES = {"固定话术", "锁定话术"}
MAX_CONNECTOR_LENGTH = 8

LockMode = Literal["strict", "soft"]


@dataclass(slots=True, frozen=True)
class FixedReplyMatch:
    chunk: KnowledgeChunk
    lock_mode: LockMode
    prefix: str = ""
    suffix: str = ""


class FixedReplySelector:
    def select(
        self,
        workflow_analysis: WorkflowAnalysis,
        knowledge_chunks: list[KnowledgeChunk],
    ) -> FixedReplyMatch | None:
        if workflow_analysis.reply_type != "固定话术":
            return None

        candidates = [
            chunk
            for chunk in knowledge_chunks
            if chunk.category in FIXED_REPLY_KNOWLEDGE_CATEGORIES and chunk.text.strip()
        ]
        if not candidates:
            return None

        scored: list[tuple[int, KnowledgeChunk]] = []
        for chunk in candidates:
            score = self._score_chunk(workflow_analysis, chunk)
            if score > 0:
                scored.append((score, chunk))

        if not scored:
            return None

        scored.sort(key=lambda item: (-item[0], item[1].chunk_id))
        selected_chunk = scored[0][1]
        return FixedReplyMatch(
            chunk=selected_chunk,
            lock_mode=self._resolve_lock_mode(selected_chunk),
            prefix=self._extract_connector(selected_chunk, prefix=True),
            suffix=self._extract_connector(selected_chunk, prefix=False),
        )

    def _score_chunk(self, workflow_analysis: WorkflowAnalysis, chunk: KnowledgeChunk) -> int:
        score = 0
        for tag in chunk.tags:
            normalized_tag = tag.strip()
            if normalized_tag in {"locked", "strict_locked"}:
                score += 2
            elif normalized_tag == "soft_locked":
                score += 1
            elif normalized_tag == f"intent:{workflow_analysis.intent}":
                score += 10
            elif normalized_tag == f"stage:{workflow_analysis.customer_stage}":
                score += 6
        return score

    def _resolve_lock_mode(self, chunk: KnowledgeChunk) -> LockMode:
        normalized_tags = {tag.strip() for tag in chunk.tags}
        if "soft_locked" in normalized_tags:
            return "soft"
        return "strict"

    def _extract_connector(self, chunk: KnowledgeChunk, *, prefix: bool) -> str:
        tag_prefix = "prefix:" if prefix else "suffix:"
        for tag in chunk.tags:
            normalized_tag = tag.strip()
            if not normalized_tag.startswith(tag_prefix):
                continue
            connector = normalized_tag[len(tag_prefix) :].strip()
            if self._is_safe_connector(connector):
                return connector
        return ""

    def _is_safe_connector(self, connector: str) -> bool:
        return bool(connector) and len(connector) <= MAX_CONNECTOR_LENGTH and "\n" not in connector
