from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
import math

from moments_inventory.ai_kefu.knowledge_policy import (
    partition_knowledge_chunks,
    should_include_product_docs,
)
from moments_inventory.ai_kefu.models import KnowledgeChunk, ProductRecord
from moments_inventory.ai_kefu.workflow import WorkflowAnalysis


@dataclass(slots=True)
class RetrievalResult:
    master_rule_chunks: list[KnowledgeChunk] = field(default_factory=list)
    fixed_reply_chunks: list[KnowledgeChunk] = field(default_factory=list)
    faq_chunks: list[KnowledgeChunk] = field(default_factory=list)
    product_inventory_chunks: list[KnowledgeChunk] = field(default_factory=list)
    product_material_chunks: list[KnowledgeChunk] = field(default_factory=list)
    shipping_info_chunks: list[KnowledgeChunk] = field(default_factory=list)
    after_sale_doc_chunks: list[KnowledgeChunk] = field(default_factory=list)
    style_chunks: list[KnowledgeChunk] = field(default_factory=list)


@dataclass(slots=True)
class ScoredChunk:
    chunk: KnowledgeChunk
    score: float


class TieredKnowledgeRetriever:
    def __init__(self, top_k: int = 2, fallback_k: int = 2) -> None:
        self._top_k = top_k
        self._fallback_k = fallback_k
        self._k1 = 1.5
        self._b = 0.75

    def retrieve(
        self,
        *,
        customer_message: str,
        workflow_analysis: WorkflowAnalysis,
        knowledge_chunks: list[KnowledgeChunk],
        selected_products: list[ProductRecord],
        query_embedding: list[float] | None = None,
    ) -> RetrievalResult:
        layers = partition_knowledge_chunks(knowledge_chunks)
        include_product_material = should_include_product_docs(
            workflow_analysis,
            selected_products,
        )
        include_shipping_info = self._should_include_shipping_info(
            workflow_analysis,
            customer_message,
        )
        include_after_sale_doc = self._should_include_after_sale_doc(
            workflow_analysis,
            customer_message,
        )

        return RetrievalResult(
            master_rule_chunks=list(layers.master_rule_chunks),
            fixed_reply_chunks=list(layers.fixed_reply_chunks),
            faq_chunks=self.retrieve_with_fallback(
                customer_message,
                layers.faq_chunks,
                fallback_when_no_hit=not (
                    include_product_material
                    or include_shipping_info
                    or include_after_sale_doc
                ),
                query_embedding=query_embedding,
            ),
            product_inventory_chunks=list(layers.product_inventory_chunks),
            product_material_chunks=(
                self.retrieve_with_fallback(
                    customer_message,
                    layers.product_material_chunks,
                    fallback_when_no_hit=True,
                    query_embedding=query_embedding,
                )
                if include_product_material
                else []
            ),
            shipping_info_chunks=(
                self.retrieve_with_fallback(
                    customer_message,
                    layers.shipping_info_chunks,
                    fallback_when_no_hit=True,
                    query_embedding=query_embedding,
                )
                if include_shipping_info
                else []
            ),
            after_sale_doc_chunks=(
                self.retrieve_with_fallback(
                    customer_message,
                    layers.after_sale_doc_chunks,
                    fallback_when_no_hit=True,
                    query_embedding=query_embedding,
                )
                if include_after_sale_doc
                else []
            ),
            style_chunks=list(layers.style_chunks),
        )

    def retrieve_with_fallback(
        self,
        customer_message: str,
        knowledge_chunks: list[KnowledgeChunk],
        *,
        fallback_when_no_hit: bool,
        query_embedding: list[float] | None = None,
    ) -> list[KnowledgeChunk]:
        if not knowledge_chunks:
            return []

        query_terms = self._tokenize_text(customer_message)
        normalized_message = self._normalize_text(customer_message)
        scored_chunks = self._score_chunks(
            normalized_message=normalized_message,
            query_terms=query_terms,
            knowledge_chunks=knowledge_chunks,
            query_embedding=query_embedding,
        )
        ranked_hits = [item.chunk for item in scored_chunks if item.score > 0][: self._top_k]

        if not ranked_hits:
            if not fallback_when_no_hit:
                return []
            return knowledge_chunks[: self._fallback_k]

        if fallback_when_no_hit and len(ranked_hits) < self._top_k:
            missing_count = min(self._fallback_k, self._top_k - len(ranked_hits))
            seen_chunk_ids = {chunk.chunk_id for chunk in ranked_hits}
            for chunk in knowledge_chunks:
                if chunk.chunk_id in seen_chunk_ids:
                    continue
                ranked_hits.append(chunk)
                seen_chunk_ids.add(chunk.chunk_id)
                missing_count -= 1
                if missing_count == 0:
                    break

        return ranked_hits

    def _score_chunks(
        self,
        *,
        normalized_message: str,
        query_terms: list[str],
        knowledge_chunks: list[KnowledgeChunk],
        query_embedding: list[float] | None,
    ) -> list[ScoredChunk]:
        indexed_documents = [self._build_indexed_document(chunk) for chunk in knowledge_chunks]
        average_document_length = (
            sum(document["length"] for document in indexed_documents)
            / len(indexed_documents)
        )
        document_frequency = self._build_document_frequency(
            indexed_documents,
            query_terms,
        )

        scored_chunks: list[ScoredChunk] = []
        for chunk, document in zip(knowledge_chunks, indexed_documents, strict=True):
            score = self._score_document(
                normalized_message=normalized_message,
                query_terms=query_terms,
                document=document,
                document_frequency=document_frequency,
                document_count=len(indexed_documents),
                average_document_length=average_document_length or 1.0,
                query_embedding=query_embedding,
            )
            scored_chunks.append(ScoredChunk(chunk=chunk, score=score))

        scored_chunks.sort(key=lambda item: (-item.score, item.chunk.chunk_id))
        return scored_chunks

    def _score_document(
        self,
        *,
        normalized_message: str,
        query_terms: list[str],
        document: dict[str, object],
        document_frequency: dict[str, int],
        document_count: int,
        average_document_length: float,
        query_embedding: list[float] | None,
    ) -> float:
        text_term_counts: Counter[str] = document["text_term_counts"]  # type: ignore[assignment]
        category_term_counts: Counter[str] = document["category_term_counts"]  # type: ignore[assignment]
        source_term_counts: Counter[str] = document["source_term_counts"]  # type: ignore[assignment]
        tag_term_counts: Counter[str] = document["tag_term_counts"]  # type: ignore[assignment]
        normalized_tags: list[str] = document["normalized_tags"]  # type: ignore[assignment]
        normalized_category: str = document["normalized_category"]  # type: ignore[assignment]
        normalized_source_name: str = document["normalized_source_name"]  # type: ignore[assignment]
        normalized_text: str = document["normalized_text"]  # type: ignore[assignment]
        document_length: int = document["length"]  # type: ignore[assignment]
        document_embedding: list[float] | None = document["embedding"]  # type: ignore[assignment]

        score = 0.0
        matched_query_term_count = 0
        unique_query_terms = list(dict.fromkeys(query_terms))
        for term in unique_query_terms:
            total_term_frequency = (
                text_term_counts.get(term, 0)
                + category_term_counts.get(term, 0)
                + source_term_counts.get(term, 0)
                + tag_term_counts.get(term, 0)
            )
            if total_term_frequency == 0:
                continue
            matched_query_term_count += 1

            inverse_document_frequency = self._inverse_document_frequency(
                document_count=document_count,
                document_frequency=document_frequency.get(term, 0),
            )
            score += inverse_document_frequency * (
                self._bm25_term_score(
                    term_frequency=text_term_counts.get(term, 0),
                    document_length=document_length,
                    average_document_length=average_document_length,
                )
                * 1.8
                + self._bm25_term_score(
                    term_frequency=category_term_counts.get(term, 0),
                    document_length=document_length,
                    average_document_length=average_document_length,
                )
                * 1.0
                + self._bm25_term_score(
                    term_frequency=source_term_counts.get(term, 0),
                    document_length=document_length,
                    average_document_length=average_document_length,
                )
                * 0.9
                + self._bm25_term_score(
                    term_frequency=tag_term_counts.get(term, 0),
                    document_length=document_length,
                    average_document_length=average_document_length,
                )
                * 0.45
            )

            if term in normalized_text:
                score += 1.3
            if term in normalized_category:
                score += 0.9
            if term in normalized_source_name:
                score += 0.8
            if term in normalized_tags:
                score += 0.35

        shared_bigram_count = self._shared_bigram_count(
            normalized_message,
            normalized_text,
        )
        if shared_bigram_count >= 2:
            score += shared_bigram_count * 0.35

        if normalized_message and normalized_message in normalized_text:
            score += 2.0

        phrase_hit_count = self._count_phrase_hits(
            normalized_message,
            normalized_tags,
        )
        if phrase_hit_count > 0:
            score += phrase_hit_count * 0.8

        has_strong_signal = (
            phrase_hit_count > 0
            or shared_bigram_count >= 2
            or (normalized_message and normalized_message in normalized_text)
        )

        semantic_score = self._cosine_similarity(query_embedding, document_embedding)
        if semantic_score > 0:
            score += semantic_score * 2.5
            has_strong_signal = True

        if matched_query_term_count < 2 and not has_strong_signal:
            return 0.0

        return score

    def _build_indexed_document(self, chunk: KnowledgeChunk) -> dict[str, object]:
        normalized_category = self._normalize_text(chunk.category)
        normalized_source_name = self._normalize_text(chunk.source_name)
        normalized_text = self._normalize_text(chunk.text)
        normalized_tags = [
            normalized_tag
            for tag in chunk.tags
            if (normalized_tag := self._normalize_text(tag))
        ]

        text_terms = self._tokenize_text(chunk.text)
        category_terms = self._tokenize_text(chunk.category)
        source_terms = self._tokenize_text(chunk.source_name)
        tag_terms: list[str] = []
        for tag in chunk.tags:
            tag_terms.extend(self._tokenize_text(tag))

        all_terms = [*text_terms, *category_terms, *source_terms, *tag_terms]

        return {
            "text_term_counts": Counter(text_terms),
            "category_term_counts": Counter(category_terms),
            "source_term_counts": Counter(source_terms),
            "tag_term_counts": Counter(tag_terms),
            "length": max(len(all_terms), 1),
            "normalized_category": normalized_category,
            "normalized_source_name": normalized_source_name,
            "normalized_text": normalized_text,
            "normalized_tags": normalized_tags,
            "terms": all_terms,
            "embedding": chunk.embedding,
        }

    def _build_document_frequency(
        self,
        indexed_documents: list[dict[str, object]],
        query_terms: list[str],
    ) -> dict[str, int]:
        unique_query_terms = set(query_terms)
        document_frequency = {term: 0 for term in unique_query_terms}
        for document in indexed_documents:
            document_terms = set(document["terms"])  # type: ignore[arg-type]
            for term in unique_query_terms:
                if term in document_terms:
                    document_frequency[term] += 1
        return document_frequency

    def _inverse_document_frequency(
        self,
        *,
        document_count: int,
        document_frequency: int,
    ) -> float:
        return math.log(
            1 + (document_count - document_frequency + 0.5) / (document_frequency + 0.5)
        )

    def _bm25_term_score(
        self,
        *,
        term_frequency: int,
        document_length: int,
        average_document_length: float,
    ) -> float:
        denominator = term_frequency + self._k1 * (
            1 - self._b + self._b * document_length / max(average_document_length, 1.0)
        )
        return term_frequency * (self._k1 + 1) / denominator

    def _count_phrase_hits(
        self,
        normalized_message: str,
        normalized_tags: list[str],
    ) -> int:
        if not normalized_message:
            return 0
        return sum(1 for tag in normalized_tags if tag and tag in normalized_message)

    def _should_include_shipping_info(
        self,
        workflow_analysis: WorkflowAnalysis,
        customer_message: str,
    ) -> bool:
        return (
            workflow_analysis.intent == "发货咨询"
            or "发货信息" in workflow_analysis.required_data
            or any(keyword in customer_message for keyword in ("发货", "物流", "多久到", "几天到"))
        )

    def _should_include_after_sale_doc(
        self,
        workflow_analysis: WorkflowAnalysis,
        customer_message: str,
    ) -> bool:
        return (
            workflow_analysis.intent == "售后咨询"
            or "售后规则" in workflow_analysis.required_data
            or workflow_analysis.customer_stage == "售后说明"
            or any(keyword in customer_message for keyword in ("售后", "退款", "退货", "质保", "赔付"))
        )

    def _tokenize_text(self, text: str) -> list[str]:
        normalized = self._normalize_text(text)
        if not normalized:
            return []

        ascii_terms: list[str] = []
        current_ascii_term: list[str] = []
        for character in normalized.lower():
            if character.isascii() and character.isalnum():
                current_ascii_term.append(character)
            else:
                if current_ascii_term:
                    ascii_terms.append("".join(current_ascii_term))
                    current_ascii_term = []
        if current_ascii_term:
            ascii_terms.append("".join(current_ascii_term))

        bigrams = [
            normalized[index : index + 2]
            for index in range(len(normalized) - 1)
        ]

        return [*ascii_terms, *bigrams]

    def _normalize_text(self, text: str) -> str:
        return "".join(
            character
            for character in text
            if not character.isspace() and character not in "，。！？；,.!?;:()（）[]【】-_"
        )

    def _shared_bigram_count(self, left_text: str, right_text: str) -> int:
        if len(left_text) < 2 or len(right_text) < 2:
            return 0
        left_bigrams = {
            left_text[index : index + 2]
            for index in range(len(left_text) - 1)
        }
        return sum(1 for bigram in left_bigrams if bigram in right_text)

    def _cosine_similarity(
        self,
        left: list[float] | None,
        right: list[float] | None,
    ) -> float:
        if left is None or right is None or not left or not right or len(left) != len(right):
            return 0.0
        left_norm = math.sqrt(sum(value * value for value in left))
        right_norm = math.sqrt(sum(value * value for value in right))
        if left_norm == 0 or right_norm == 0:
            return 0.0
        dot = sum(left_value * right_value for left_value, right_value in zip(left, right, strict=True))
        return dot / (left_norm * right_norm)
