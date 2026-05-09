from __future__ import annotations

from dataclasses import dataclass, field

from moments_inventory.ai_kefu.models import KnowledgeChunk, KnowledgeTier, ProductRecord, VALID_KNOWLEDGE_TIERS
from moments_inventory.ai_kefu.workflow import WorkflowAnalysis


STYLE_KNOWLEDGE_CATEGORY = "回复风格"
MASTER_RULE_KNOWLEDGE_CATEGORIES = {"主规则", "服务流程", "流程规则"}
FIXED_REPLY_KNOWLEDGE_CATEGORIES = {"固定话术", "锁定话术"}
PRODUCT_MATERIAL_CATEGORY_KEYWORDS = (
    "商品资料",
    "商品文案",
    "产品",
    "参数",
    "配件",
    "电池",
    "续航",
    "验机",
    "视频",
    "导出",
)
PRODUCT_MATERIAL_REQUIRED_DATA = {"商品文案", "验机视频", "配件说明", "电池说明", "导出说明"}
PRODUCT_MATERIAL_STAGES = {"验机"}
PRODUCT_MATERIAL_INTENTS = {"验机视频", "瑕疵咨询", "配件咨询", "续航咨询", "导出照片"}
SHIPPING_CATEGORY_KEYWORDS = ("供应链", "仓", "supplier:")
AFTER_SALE_CATEGORY_KEYWORDS = ("正式售后", "售后文件", "售后政策", "售后边界", "质保文件")


@dataclass(slots=True)
class KnowledgeLayers:
    master_rule_chunks: list[KnowledgeChunk] = field(default_factory=list)
    fixed_reply_chunks: list[KnowledgeChunk] = field(default_factory=list)
    faq_chunks: list[KnowledgeChunk] = field(default_factory=list)
    product_inventory_chunks: list[KnowledgeChunk] = field(default_factory=list)
    product_material_chunks: list[KnowledgeChunk] = field(default_factory=list)
    shipping_info_chunks: list[KnowledgeChunk] = field(default_factory=list)
    after_sale_doc_chunks: list[KnowledgeChunk] = field(default_factory=list)
    style_chunks: list[KnowledgeChunk] = field(default_factory=list)


def classify_knowledge_tier(chunk: KnowledgeChunk) -> KnowledgeTier:
    if chunk.knowledge_tier in VALID_KNOWLEDGE_TIERS:
        return chunk.knowledge_tier
    if chunk.category in MASTER_RULE_KNOWLEDGE_CATEGORIES:
        return "master_rule"
    if chunk.category in FIXED_REPLY_KNOWLEDGE_CATEGORIES:
        return "fixed_reply"
    if chunk.category == STYLE_KNOWLEDGE_CATEGORY:
        return "style_sample"
    if _matches_after_sale_doc(chunk):
        return "after_sale_doc"
    if _matches_shipping_info(chunk):
        return "shipping_info"
    if _matches_product_material(chunk):
        return "product_material"
    return "faq"


def partition_knowledge_chunks(chunks: list[KnowledgeChunk]) -> KnowledgeLayers:
    layers = KnowledgeLayers()
    for chunk in chunks:
        tier = classify_knowledge_tier(chunk)
        if tier == "master_rule":
            layers.master_rule_chunks.append(chunk)
        elif tier == "fixed_reply":
            layers.fixed_reply_chunks.append(chunk)
        elif tier == "style_sample":
            layers.style_chunks.append(chunk)
        elif tier == "product_inventory":
            layers.product_inventory_chunks.append(chunk)
        elif tier == "product_material":
            layers.product_material_chunks.append(chunk)
        elif tier == "shipping_info":
            layers.shipping_info_chunks.append(chunk)
        elif tier == "after_sale_doc":
            layers.after_sale_doc_chunks.append(chunk)
        else:
            layers.faq_chunks.append(chunk)
    return layers


def should_include_product_docs(
    workflow_analysis: WorkflowAnalysis,
    selected_products: list[ProductRecord],
) -> bool:
    if workflow_analysis.customer_stage in PRODUCT_MATERIAL_STAGES:
        return True
    if workflow_analysis.intent in PRODUCT_MATERIAL_INTENTS:
        return True
    if PRODUCT_MATERIAL_REQUIRED_DATA.intersection(workflow_analysis.required_data):
        return True
    return bool(selected_products) and workflow_analysis.reply_type == "需查询后回答"


def _matches_product_material(chunk: KnowledgeChunk) -> bool:
    values = [chunk.category, chunk.source_name, *chunk.tags]
    normalized_values = [value.lower() for value in values]
    return any(
        keyword.lower() in value
        for keyword in PRODUCT_MATERIAL_CATEGORY_KEYWORDS
        for value in normalized_values
    )


def _matches_shipping_info(chunk: KnowledgeChunk) -> bool:
    values = [chunk.category, chunk.source_name, *chunk.tags]
    normalized_values = [value.lower() for value in values]
    return any(
        keyword.lower() in value
        for keyword in SHIPPING_CATEGORY_KEYWORDS
        for value in normalized_values
    )


def _matches_after_sale_doc(chunk: KnowledgeChunk) -> bool:
    values = [chunk.category, chunk.source_name, *chunk.tags]
    normalized_values = [value.lower() for value in values]
    return any(
        keyword.lower() in value
        for keyword in AFTER_SALE_CATEGORY_KEYWORDS
        for value in normalized_values
    )
