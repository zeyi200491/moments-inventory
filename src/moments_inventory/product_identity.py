from __future__ import annotations

from dataclasses import dataclass
import hashlib
import re

from moments_inventory.models import InventoryRecord
from moments_inventory.utils import normalize_text


PRICE_PATTERNS = [
    re.compile(r"\d{2,6}\s*(?:💰|元|块|rmb|￥|¥)", re.IGNORECASE),
    re.compile(r"(?:💰|￥|¥|rmb)\s*\d{2,6}", re.IGNORECASE),
]


@dataclass(frozen=True, slots=True)
class ProductIdentity:
    key: str
    reason: str


def normalize_listing_text(text: str) -> str:
    cleaned = text or ""
    for pattern in PRICE_PATTERNS:
        cleaned = pattern.sub(" ", cleaned)
    return " ".join(normalize_text(cleaned).split())


def _digest(parts: list[str]) -> str:
    payload = "\n".join(part for part in parts if part)
    return hashlib.sha1(payload.encode("utf-8")).hexdigest()[:20]


def _media_key(record: InventoryRecord) -> str:
    media = sorted(set(record.image_urls + record.video_urls))
    return _digest(media) if media else ""


def build_product_key(record: InventoryRecord) -> ProductIdentity:
    wxid = record.wxid or ""
    media = _media_key(record)
    if wxid and media:
        return ProductIdentity(key=f"media:{_digest([wxid, media])}", reason="wxid+media")

    text = normalize_listing_text(record.content_text)
    model = normalize_text(record.model or "")
    serial = normalize_text(record.serial_no or "")
    if wxid and model and text:
        return ProductIdentity(
            key=f"text:{_digest([wxid, model, serial, text])}",
            reason="wxid+model+text_without_price",
        )

    return ProductIdentity(
        key=f"record:{_digest([record.record_key, wxid, text])}",
        reason="record_fallback",
    )
