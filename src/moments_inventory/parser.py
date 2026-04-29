from __future__ import annotations

import re

from moments_inventory.models import ParsedFields
from moments_inventory.utils import normalize_text


PRICE_PATTERNS = [
    re.compile(r"\b(\d{2,5})\s*💰"),
    re.compile(r"💰\s*(\d{2,5})"),
    re.compile(r"(?:价格[:：]?|仅需)\s*(\d{2,5})(?:元|包邮)?"),
    re.compile(r"\b(\d{2,5})(?:元|包邮)\b"),
    re.compile(r"(?<![A-Za-z0-9])(\d{2,5})(?![A-Za-z0-9])"),
]
MODEL_PATTERN = re.compile(
    r"(佳能|索尼|富士|尼康|卡西欧|奥林巴斯|三星|松下|柯达|宾得|理光|徕卡|惠普|欧达|美能达|拍得丽)\s*([A-Za-z0-9][A-Za-z0-9/+.-]*)",
    re.IGNORECASE,
)
SERIAL_PATTERNS = [
    re.compile(r"编号[:：]?\s*([A-Za-z]?\d{1,4})", re.IGNORECASE),
    re.compile(r"\b([A-Za-z]\d{1,4})\b"),
    re.compile(r"(\d{1,4})号"),
]


def _pick_model(text: str, model_keywords: list[str]) -> str | None:
    matches = [keyword for keyword in model_keywords if keyword in text]
    if matches:
        return sorted(matches, key=len, reverse=True)[0]
    match = MODEL_PATTERN.search(text)
    if not match:
        return None
    return f"{match.group(1)}{match.group(2)}"


def _pick_price(text: str) -> int | None:
    for index, pattern in enumerate(PRICE_PATTERNS):
        matches = pattern.findall(text)
        if not matches:
            continue
        if index == len(PRICE_PATTERNS) - 1:
            return max(int(item) for item in matches)
        return int(matches[0])
    return None


def _pick_serial(text: str) -> str | None:
    for pattern in SERIAL_PATTERNS:
        matches = pattern.findall(text)
        if not matches:
            continue
        return matches[-1].upper()
    return None


def parse_content(content: str, model_keywords: list[str]) -> ParsedFields:
    normalized = normalize_text(content)
    model = _pick_model(normalized, model_keywords)
    price = _pick_price(normalized)
    serial_no = _pick_serial(content)
    needs_manual = any(value is None for value in (model, price, serial_no))
    return ParsedFields(
        model=model,
        price=price,
        serial_no=serial_no,
        note="",
        needs_manual=needs_manual,
    )
