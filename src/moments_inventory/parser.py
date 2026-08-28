from __future__ import annotations

import re
from typing import TYPE_CHECKING

from moments_inventory.models import ParsedFields
from moments_inventory.utils import normalize_text

if TYPE_CHECKING:
    from moments_inventory.model_matcher import ModelMatch, ModelMatcher


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
    matches = _pick_model_candidates(text, model_keywords)
    if matches:
        return matches[0]
    match = MODEL_PATTERN.search(text)
    if not match:
        return None
    return f"{match.group(1)}{match.group(2)}"


def _pick_model_candidates(text: str, model_keywords: list[str]) -> list[str]:
    seen: set[str] = set()
    matches: list[str] = []
    for keyword in sorted(model_keywords, key=len, reverse=True):
        if keyword in text and keyword not in seen:
            seen.add(keyword)
            matches.append(keyword)
    if matches:
        return matches

    for match in MODEL_PATTERN.finditer(text):
        model = f"{match.group(1)}{match.group(2)}"
        if model not in seen:
            seen.add(model)
            matches.append(model)
    return matches


def _pick_price(
    text: str,
    model: str | None,
    excluded_spans: list[tuple[int, int]] | None = None,
) -> int | None:
    money_matches: list[tuple[int, int]] = []
    for pattern in PRICE_PATTERNS[:2]:
        for match in pattern.finditer(text):
            money_matches.append((match.start(), int(match.group(1))))
    if money_matches:
        money_matches.sort(key=lambda item: item[0])
        return money_matches[0][1]
    if "💰" in text:
        return None

    for index, pattern in enumerate(PRICE_PATTERNS[2:], start=2):
        matches = pattern.findall(text)
        if not matches:
            continue
        if index == len(PRICE_PATTERNS) - 1:
            filtered_matches = [
                int(item)
                for item in matches
                if not _looks_like_date_number(text, item)
                and not _is_model_number(text, model, item)
                and not _is_number_in_spans(text, item, excluded_spans or [])
            ]
            if not filtered_matches:
                continue
            return filtered_matches[0]
        return int(matches[0])
    return None


def _looks_like_date_number(text: str, raw_number: str) -> bool:
    for match in re.finditer(re.escape(raw_number), text):
        before = text[max(0, match.start() - 2) : match.start()]
        after = text[match.end() : match.end() + 2]
        if ("月" in before and "日" in after) or after.startswith("日"):
            return True
    return False


def _is_model_number(text: str, model: str | None, raw_number: str) -> bool:
    if not model:
        return False
    model_spans = [match.span() for match in re.finditer(re.escape(model), text, re.IGNORECASE)]
    if not model_spans:
        return False
    for match in re.finditer(re.escape(raw_number), text):
        for start, end in model_spans:
            if start <= match.start() and match.end() <= end:
                return True
    return False


def _is_number_in_spans(
    text: str,
    raw_number: str,
    spans: list[tuple[int, int]],
) -> bool:
    if not spans:
        return False
    for match in re.finditer(re.escape(raw_number), text):
        if any(start <= match.start() and match.end() <= end for start, end in spans):
            return True
    return False


def _pick_serial(text: str) -> str | None:
    for pattern in SERIAL_PATTERNS:
        matches = pattern.findall(text)
        if not matches:
            continue
        return matches[-1].upper()
    return None


def _canonical_models(matches: list["ModelMatch"]) -> list[str]:
    models: list[str] = []
    seen: set[str] = set()
    for match in matches:
        if match.canonical_model in seen:
            continue
        seen.add(match.canonical_model)
        models.append(match.canonical_model)
    return models


def _mask_spans(text: str, spans: list[tuple[int, int]]) -> str:
    if not spans:
        return text
    chars = list(text)
    for start, end in spans:
        safe_start = max(0, start)
        safe_end = min(len(chars), end)
        for index in range(safe_start, safe_end):
            chars[index] = " "
    return "".join(chars)


def parse_content(
    content: str,
    model_keywords: list[str],
    model_matcher: "ModelMatcher | None" = None,
) -> ParsedFields:
    normalized = normalize_text(content)

    if model_matcher is not None:
        from moments_inventory.model_context import choose_primary_model

        matches = model_matcher.find(content)
        if matches:
            excluded_spans = [(match.start, match.end) for match in matches]
            price = _pick_price(content, None, excluded_spans)
            selection = choose_primary_model(content, matches, price=price)
            if selection.model:
                model = selection.model
                serial_no = _pick_serial(content)
                needs_manual = selection.needs_manual or any(
                    value is None for value in (model, price, serial_no)
                )
                return ParsedFields(
                    model=model,
                    price=price,
                    serial_no=serial_no,
                    note="",
                    needs_manual=needs_manual,
                    model_confidence=selection.confidence,
                    matched_alias=selection.matched_alias,
                    model_candidates=_canonical_models(selection.model_candidates),
                    ignored_reference_models=_canonical_models(
                        selection.ignored_reference_models
                    ),
                )
            serial_no = _pick_serial(content)
            confidence = (
                "ambiguous"
                if selection.confidence == "low" and selection.ignored_reference_models
                else selection.confidence
            )
            masked_content = _mask_spans(
                content,
                [(match.start, match.end) for match in selection.ignored_reference_models],
            )
            masked_normalized = normalize_text(masked_content)
            fallback_model = _pick_model(masked_normalized, model_keywords)
            if fallback_model:
                serial_no = _pick_serial(content)
                needs_manual = any(
                    value is None for value in (fallback_model, price, serial_no)
                )
                return ParsedFields(
                    model=fallback_model,
                    price=price,
                    serial_no=serial_no,
                    note="",
                    needs_manual=needs_manual,
                    model_confidence="medium",
                    matched_alias=fallback_model,
                    model_candidates=[fallback_model],
                    ignored_reference_models=_canonical_models(
                        selection.ignored_reference_models
                    ),
                )
            return ParsedFields(
                model=None,
                price=price,
                serial_no=serial_no,
                note="",
                needs_manual=True,
                model_confidence=confidence,
                matched_alias=selection.matched_alias,
                model_candidates=_canonical_models(selection.model_candidates),
                ignored_reference_models=_canonical_models(selection.ignored_reference_models),
            )

    model_candidates = _pick_model_candidates(normalized, model_keywords)
    model = model_candidates[0] if model_candidates else None
    price = _pick_price(normalized, model)
    serial_no = _pick_serial(content)
    needs_manual = any(value is None for value in (model, price, serial_no))
    return ParsedFields(
        model=model,
        price=price,
        serial_no=serial_no,
        note="",
        needs_manual=needs_manual,
        model_confidence="ambiguous" if len(model_candidates) > 1 else ("medium" if model else "low"),
        matched_alias=model,
        model_candidates=model_candidates,
    )
