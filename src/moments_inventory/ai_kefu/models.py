from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from moments_inventory.ai_kefu.risk import RiskLevel


KnowledgeTier = Literal[
    "master_rule",
    "fixed_reply",
    "faq",
    "product_inventory",
    "product_material",
    "shipping_info",
    "after_sale_doc",
    "style_sample",
]

VALID_KNOWLEDGE_TIERS: tuple[KnowledgeTier, ...] = (
    "master_rule",
    "fixed_reply",
    "faq",
    "product_inventory",
    "product_material",
    "shipping_info",
    "after_sale_doc",
    "style_sample",
)

LibraryType = Literal[
    "master_rule_bundle",
    "product_inventory_excel",
    "product_material_excel",
    "shipping_info_excel",
    "style_sample_md",
]


@dataclass(slots=True)
class KnowledgeChunk:
    chunk_id: str
    source_name: str
    category: str
    text: str
    knowledge_tier: KnowledgeTier | None = None
    tags: list[str] = field(default_factory=list)
    embedding: list[float] | None = None


@dataclass(slots=True)
class ConversationDraft:
    conversation_id: str
    customer_message: str
    final_reply: str
    risk_level: RiskLevel = "L1"
    used_chunk_ids: list[str] = field(default_factory=list)


@dataclass(slots=True)
class ProductRecord:
    product_id: str
    source_record_id: str
    brand: str
    model_std: str
    sale_status: str
    is_functional: bool
    has_inspection_video: bool
    has_sample_output: bool
    cost_price: int
    sale_price: int
    profit_amount: int
    source_name: str
    source_wxid: str
    published_at: str
    image_path: str
    video_path: str
    raw_copy: str
    manual_review_needed: bool = False


@dataclass(slots=True)
class LibraryStateRecord:
    library_type: LibraryType
    source_name: str
    original_filename: str
    imported_count: int
    skipped_count: int
    status: str
    uploaded_at: str
