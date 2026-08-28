from __future__ import annotations

from dataclasses import dataclass
import hashlib
import re

from moments_inventory.models import InventoryRecord
from moments_inventory.product_identity import build_product_key, normalize_listing_text
from moments_inventory.utils import normalize_text


SOLD_KEYWORDS = (
    "已出",
    "已售",
    "售出",
    "出了",
    "卖掉",
    "卖了",
    "没了",
    "无了",
    "下架",
    "暂不出",
    "暂停出售",
    "sold",
)

CHINESE_SOLD_KEYWORDS = tuple(keyword for keyword in SOLD_KEYWORDS if keyword != "sold")
NEGATED_PREFIXES = ("不是", "没有", "未", "非")


@dataclass(slots=True)
class LifecycleClassification:
    status: str
    lifecycle_status: str
    risk_flags: list[str]


@dataclass(slots=True)
class LifecycleMergeResult:
    current_records: list[InventoryRecord]
    review_records: list[InventoryRecord]


def classify_lifecycle(record: InventoryRecord) -> LifecycleClassification:
    risk_flags = list(record.risk_flags)

    if _has_sold_signal(record.content_text):
        return LifecycleClassification(
            status="已售",
            lifecycle_status="sold",
            risk_flags=_append_unique(risk_flags, ["sold_keyword"]),
        )

    return LifecycleClassification(
        status=record.status,
        lifecycle_status="current",
        risk_flags=risk_flags,
    )


def merge_product_lifecycle(records: list[InventoryRecord], observed_at: str | None = None) -> LifecycleMergeResult:
    """原地丰富传入的 InventoryRecord，并返回这些记录对象的 current/review 分组。"""
    groups: dict[str, list[InventoryRecord]] = {}
    for record in records:
        _ensure_product_identity(record)
        groups.setdefault(record.product_key or record.record_key, []).append(record)

    current_records: list[InventoryRecord] = []
    review_records: list[InventoryRecord] = []
    for group_records in groups.values():
        ordered_records = sorted(group_records, key=lambda item: item.published_at)
        classifications = {record.record_key: classify_lifecycle(record) for record in ordered_records}
        has_sold_record = any(
            classification.lifecycle_status == "sold" for classification in classifications.values()
        )

        primary = ordered_records[-1]
        _merge_common_fields(primary, ordered_records)
        merged_flags = _merged_risk_flags(ordered_records, classifications)
        merged_flags = _append_unique(merged_flags, _price_change_flags(ordered_records))

        if observed_at is not None:
            primary.last_seen_at = observed_at

        if has_sold_record:
            primary.status = "已售"
            primary.lifecycle_status = "sold"
            primary.risk_flags = _append_unique(merged_flags, ["sold_keyword"])
            review_records.append(primary)
        else:
            current_classification = classifications[primary.record_key]
            primary.status = current_classification.status
            primary.lifecycle_status = "current"
            primary.risk_flags = merged_flags
            current_records.append(primary)

    return LifecycleMergeResult(current_records=current_records, review_records=review_records)


def _ensure_product_identity(record: InventoryRecord) -> None:
    if record.product_key:
        if not record.fingerprint_reason:
            record.fingerprint_reason = "existing_product_key"
        return

    identity = _build_lifecycle_product_key(record)
    if identity is not None:
        record.product_key = identity[0]
        record.fingerprint_reason = identity[1]
        return

    identity = build_product_key(record)
    record.product_key = identity.key
    record.fingerprint_reason = identity.reason


def _build_lifecycle_product_key(record: InventoryRecord) -> tuple[str, str] | None:
    if record.image_urls or record.video_urls:
        return None

    wxid = record.wxid or ""
    model = normalize_text(record.model or "")
    text = _normalize_lifecycle_identity_text(record.content_text)
    serial = normalize_text(record.serial_no or "")
    if not wxid or not model or not text:
        return None

    return f"text:{_digest([wxid, model, serial, text])}", "wxid+model+text_without_price_lifecycle"


def _normalize_lifecycle_identity_text(text: str) -> str:
    normalized = normalize_listing_text(text)
    normalized = re.sub(r"\b(?:sold)\b", " ", normalized, flags=re.IGNORECASE)
    for keyword in sorted(CHINESE_SOLD_KEYWORDS, key=len, reverse=True):
        normalized = normalized.replace(keyword, " ")
    return " ".join(normalize_text(normalized).split())


def _has_sold_signal(text: str) -> bool:
    content = text or ""
    lowered = content.lower()
    if re.search(r"\bsold\b", lowered) and not re.search(r"\bnot\s+sold\b", lowered):
        return True

    for keyword in sorted(CHINESE_SOLD_KEYWORDS, key=len, reverse=True):
        start = 0
        while True:
            index = content.find(keyword, start)
            if index == -1:
                break
            if not _is_negated_or_non_status_context(content, keyword, index):
                return True
            start = index + len(keyword)
    return False


def _is_negated_or_non_status_context(content: str, keyword: str, index: int) -> bool:
    prefix = content[max(0, index - 4) : index]
    suffix = content[index + len(keyword) : index + len(keyword) + 4]
    if any(prefix.endswith(negated_prefix) for negated_prefix in NEGATED_PREFIXES):
        return True
    if keyword == "下架" and (prefix.endswith("可") or suffix.startswith("包邮")):
        return True
    return False


def _merge_common_fields(primary: InventoryRecord, records: list[InventoryRecord]) -> None:
    primary.source_moment_ids = _merge_source_moment_ids(records)
    primary.image_urls = sorted({url for record in records for url in record.image_urls})
    primary.video_urls = sorted({url for record in records for url in record.video_urls})
    primary.price_history = _merge_price_history(records)


def _merge_source_moment_ids(records: list[InventoryRecord]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for record in records:
        ids = record.source_moment_ids or [record.record_key]
        for moment_id in ids:
            if moment_id not in seen:
                seen.add(moment_id)
                result.append(moment_id)
    return result


def _merge_price_history(records: list[InventoryRecord]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for record in records:
        if record.price is None:
            continue
        entry = f"{record.published_at.isoformat()}|{record.price}"
        if entry not in seen:
            seen.add(entry)
            result.append(entry)
    return result


def _merged_risk_flags(
    records: list[InventoryRecord],
    classifications: dict[str, LifecycleClassification],
) -> list[str]:
    flags: list[str] = []
    for record in records:
        flags = _append_unique(flags, record.risk_flags)
        flags = _append_unique(flags, classifications[record.record_key].risk_flags)
    return flags


def _price_change_flags(records: list[InventoryRecord]) -> list[str]:
    prices = [record.price for record in records if record.price is not None]
    if len(records) <= 1 or len(set(prices)) <= 1:
        return []

    if prices[-1] < prices[0]:
        return ["price_drop_repost"]
    return ["price_changed_repost"]


def _append_unique(values: list[str], additions: list[str]) -> list[str]:
    seen = set(values)
    result = list(values)
    for value in additions:
        if value not in seen:
            seen.add(value)
            result.append(value)
    return result


def _digest(parts: list[str]) -> str:
    payload = "\n".join(part for part in parts if part)
    return hashlib.sha1(payload.encode("utf-8")).hexdigest()[:20]
