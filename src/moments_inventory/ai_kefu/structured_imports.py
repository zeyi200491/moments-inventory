from __future__ import annotations

from typing import Mapping

from moments_inventory.ai_kefu.models import KnowledgeTier


SUPPORTED_STRUCTURED_TIERS: set[KnowledgeTier] = {
    "product_material",
    "shipping_info",
    "after_sale_doc",
}


def build_structured_import_content(
    *,
    knowledge_tier: KnowledgeTier,
    fields: Mapping[str, str],
) -> tuple[str, list[str]]:
    normalized_fields = {
        key: str(value).strip()
        for key, value in fields.items()
        if str(value).strip()
    }
    if not normalized_fields:
        return "", []

    if knowledge_tier == "product_material":
        return _build_product_material_content(normalized_fields)
    if knowledge_tier == "shipping_info":
        return _build_shipping_info_content(normalized_fields)
    if knowledge_tier == "after_sale_doc":
        return _build_after_sale_doc_content(normalized_fields)
    return "", []


def _build_product_material_content(fields: Mapping[str, str]) -> tuple[str, list[str]]:
    lines = [
        "商品素材条目",
        _line("型号", fields.get("product_model")),
        _line("素材类型", fields.get("material_type")),
        _line("使用场景", fields.get("usage_scene")),
        _line("素材亮点", fields.get("highlights")),
        _line("文件线索", fields.get("file_refs")),
        _line("补充备注", fields.get("notes")),
    ]
    tags = _collect_tags(
        fields.get("product_model"),
        fields.get("material_type"),
        fields.get("usage_scene"),
    )
    return _join_lines(lines), tags


def _build_shipping_info_content(fields: Mapping[str, str]) -> tuple[str, list[str]]:
    lines = [
        "供应链发货条目",
        _line("供应商", fields.get("supplier_name")),
        _line("仓库位置", fields.get("warehouse_location")),
        _line("发货时效", fields.get("dispatch_sla")),
        _line("配送范围", fields.get("delivery_scope")),
        _line("异常说明", fields.get("exceptions")),
        _line("联系时间", fields.get("contact_window")),
        _line("补充备注", fields.get("notes")),
    ]
    tags = _collect_tags(
        fields.get("supplier_name"),
        fields.get("warehouse_location"),
        fields.get("dispatch_sla"),
    )
    return _join_lines(lines), tags


def _build_after_sale_doc_content(fields: Mapping[str, str]) -> tuple[str, list[str]]:
    lines = [
        "正式售后条目",
        _line("规则名称", fields.get("policy_name")),
        _line("适用范围", fields.get("applicable_scope")),
        _line("必备凭证", fields.get("required_evidence")),
        _line("处理时效", fields.get("processing_timeline")),
        _line("不覆盖情况", fields.get("non_covered_cases")),
        _line("升级条件", fields.get("escalation_rule")),
        _line("补充备注", fields.get("notes")),
    ]
    tags = _collect_tags(
        fields.get("policy_name"),
        fields.get("applicable_scope"),
        fields.get("required_evidence"),
    )
    return _join_lines(lines), tags


def _line(label: str, value: str | None) -> str:
    return f"{label}：{value}" if value else ""


def _join_lines(lines: list[str]) -> str:
    return "\n".join(line for line in lines if line)


def _collect_tags(*values: str | None) -> list[str]:
    tags: list[str] = []
    seen: set[str] = set()
    for value in values:
        tag = (value or "").strip()
        if not tag or tag in seen:
            continue
        seen.add(tag)
        tags.append(tag)
    return tags
