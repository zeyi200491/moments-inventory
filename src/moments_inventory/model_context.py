from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from moments_inventory.model_matcher import ModelMatch


REFERENCE_WORDS = (
    "平替",
    "替代",
    "对标",
    "类似",
    "媲美",
    "参考",
    "同款感觉",
    "拍人像也是",
)
NEGATIVE_WORDS = ("不是", "不要", "不等于", "不是那款")
ACCESSORY_WORDS = ("适用", "兼容", "电池适配", "充电器适配", "配件")
COMPARISON_WORDS = ("对比", "区别", "比较")

PREFIX_WINDOW = 14
SUFFIX_WINDOW = 9
BRAND_WINDOW = 10
CONTEXT_SEPARATORS = "，,。.;；\n\r"
PRICE_SPAN_PATTERN = re.compile(
    r"(?P<prefix>\d{1,5}\s*💰)|(?P<suffix>💰\s*\d{1,5})|(?P<unit>\d{1,5}\s*(?:元|包邮))"
)


@dataclass(slots=True)
class ModelSelection:
    model: str | None
    confidence: str
    matched_alias: str | None = None
    model_candidates: list[ModelMatch] = field(default_factory=list)
    ignored_reference_models: list[ModelMatch] = field(default_factory=list)
    needs_manual: bool = False


@dataclass(slots=True)
class _Candidate:
    match: ModelMatch
    score: float


def choose_primary_model(
    text: str,
    matches: list[ModelMatch],
    *,
    price: Any,
) -> ModelSelection:
    if not matches:
        return ModelSelection(model=None, confidence="low", needs_manual=True)

    ignored: list[ModelMatch] = []
    primary_candidates: list[ModelMatch] = []
    for match in matches:
        if _is_ignored_context(text, match):
            ignored.append(match)
        else:
            primary_candidates.append(match)

    if not primary_candidates:
        return ModelSelection(
            model=None,
            confidence="low",
            model_candidates=[],
            ignored_reference_models=list(ignored),
            needs_manual=True,
        )

    if _has_same_span_conflict(primary_candidates):
        return ModelSelection(
            model=None,
            confidence="ambiguous",
            model_candidates=list(primary_candidates),
            ignored_reference_models=list(ignored),
            needs_manual=True,
        )

    if price is None and _is_pure_comparison_context(text, primary_candidates):
        return ModelSelection(
            model=None,
            confidence="ambiguous",
            model_candidates=list(primary_candidates),
            ignored_reference_models=list(ignored),
            needs_manual=True,
        )

    price_span = _coerce_price_span(text, price)
    ranked = sorted(
        (_Candidate(match=match, score=_score_match(text, match, price_span)) for match in primary_candidates),
        key=lambda candidate: (
            candidate.score,
            len(candidate.match.alias),
            -candidate.match.start,
        ),
        reverse=True,
    )
    best = ranked[0]
    confidence = _confidence(best, ranked, price_span)

    return ModelSelection(
        model=best.match.canonical_model,
        confidence=confidence,
        matched_alias=best.match.alias,
        model_candidates=list(primary_candidates),
        ignored_reference_models=list(ignored),
        needs_manual=confidence == "ambiguous",
    )


def _is_ignored_context(text: str, match: ModelMatch) -> bool:
    prefix = _prefix_segment(text[max(0, match.start - PREFIX_WINDOW) : match.start])
    suffix = _suffix_segment(text[match.end : min(len(text), match.end + SUFFIX_WINDOW)])
    return (
        _has_context_word(prefix, suffix, NEGATIVE_WORDS)
        or _has_context_word(prefix, suffix, ACCESSORY_WORDS)
        or _has_reference_context(prefix)
    )


def _prefix_segment(prefix: str) -> str:
    last_separator = max(prefix.rfind(separator) for separator in CONTEXT_SEPARATORS)
    if last_separator < 0:
        return prefix
    return prefix[last_separator + 1 :]


def _suffix_segment(suffix: str) -> str:
    separator_positions = [
        suffix.find(separator)
        for separator in CONTEXT_SEPARATORS
        if suffix.find(separator) >= 0
    ]
    if not separator_positions:
        return suffix
    return suffix[: min(separator_positions)]


def _has_context_word(prefix: str, suffix: str, words: tuple[str, ...]) -> bool:
    return any(word in prefix or word in suffix for word in words)


def _has_reference_context(prefix: str) -> bool:
    return any(word in prefix for word in REFERENCE_WORDS)


def _is_pure_comparison_context(text: str, matches: list[ModelMatch]) -> bool:
    if not any(word in text for word in COMPARISON_WORDS):
        return False
    return len(_unique_models(matches)) > 1


def _has_same_span_conflict(matches: list[ModelMatch]) -> bool:
    span_models: dict[tuple[int, int], set[tuple[str, str]]] = {}
    for match in matches:
        span_models.setdefault((match.start, match.end), set()).add(
            (match.brand, match.canonical_model)
        )
    return any(len(models) > 1 for models in span_models.values())


def _score_match(
    text: str,
    match: ModelMatch,
    price_span: tuple[int, int] | None,
) -> float:
    score = 0.0
    if _is_first_line(text, match):
        score += 18
    if price_span is not None:
        score += max(0, 60 - _span_distance((match.start, match.end), price_span))
    if _alias_contains_brand(match):
        score += 14
    if match.safe:
        score += 10
    if _nearby_brand(text, match):
        score += 8
    score += min(12, match.end - match.start)
    if match.ambiguous:
        score -= 30
    return score


def _confidence(
    best: _Candidate,
    ranked: list[_Candidate],
    price_span: tuple[int, int] | None,
) -> str:
    if best.match.ambiguous:
        return "ambiguous"
    if len(ranked) > 1 and ranked[1].score >= best.score - 8:
        return "ambiguous"
    if price_span is not None and best.score >= 70:
        return "high"
    return "medium"


def _coerce_price_span(text: str, price: Any) -> tuple[int, int] | None:
    if price is None:
        return None
    if isinstance(price, tuple | list) and len(price) == 2:
        start, end = price
        if isinstance(start, int) and isinstance(end, int):
            return (start, end)
    if hasattr(price, "start") and hasattr(price, "end"):
        start = getattr(price, "start")
        end = getattr(price, "end")
        if isinstance(start, int) and isinstance(end, int):
            return (start, end)
    if isinstance(price, int):
        return _find_price_value_span(text, price)
    if isinstance(price, str):
        start = text.find(price)
        if start >= 0:
            return (start, start + len(price))
    return None


def _find_price_value_span(text: str, price: int) -> tuple[int, int] | None:
    price_text = str(price)
    for match in PRICE_SPAN_PATTERN.finditer(text):
        if price_text in match.group(0):
            return match.span()
    return None


def _span_distance(a: tuple[int, int], b: tuple[int, int]) -> int:
    if a[1] < b[0]:
        return b[0] - a[1]
    if b[1] < a[0]:
        return a[0] - b[1]
    return 0


def _is_first_line(text: str, match: ModelMatch) -> bool:
    first_newline = text.find("\n")
    return first_newline < 0 or match.start < first_newline


def _alias_contains_brand(match: ModelMatch) -> bool:
    alias = match.alias.lower()
    return bool(
        (match.brand and match.brand.lower() in alias)
        or (match.brand_en and match.brand_en.lower() in alias)
    )


def _nearby_brand(text: str, match: ModelMatch) -> bool:
    start = max(0, match.start - BRAND_WINDOW)
    end = min(len(text), match.end + BRAND_WINDOW)
    context = text[start:end].lower()
    return bool(
        (match.brand and match.brand.lower() in context)
        or (match.brand_en and match.brand_en.lower() in context)
    )


def _unique_models(matches: list[ModelMatch]) -> list[str]:
    models: list[str] = []
    seen: set[str] = set()
    for match in matches:
        if match.canonical_model in seen:
            continue
        seen.add(match.canonical_model)
        models.append(match.canonical_model)
    return models
