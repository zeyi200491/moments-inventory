from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
import json
from pathlib import Path

from moments_inventory.logging_utils import get_logger
from moments_inventory.model_catalog import (
    ModelCatalogAlias,
    ModelCatalogIndex,
    load_model_catalog_index,
    normalize_model_key,
)


LOGGER = get_logger(__name__)


@dataclass(slots=True)
class ModelMatch:
    alias: str
    normalized_key: str
    brand: str
    brand_en: str
    canonical_model: str
    safe: bool
    ambiguous: bool
    source_row: int
    start: int
    end: int


@dataclass(slots=True)
class _Node:
    children: dict[str, int] = field(default_factory=dict)
    failure: int = 0
    outputs: list[str] = field(default_factory=list)


class ModelMatcher:
    def __init__(self, index: ModelCatalogIndex) -> None:
        self._aliases_by_key: dict[str, list[ModelCatalogAlias]] = {}
        self._nodes = [_Node()]

        for key, aliases in index.aliases_by_key.items():
            normalized_key = normalize_model_key(key)
            if not normalized_key:
                continue
            self._aliases_by_key.setdefault(normalized_key, []).extend(aliases)
            self._insert(normalized_key)

        self._build_failures()

    def find(self, text: str) -> list[ModelMatch]:
        normalized_text, positions = _normalize_text_with_positions(text)
        if not normalized_text:
            return []

        matches: list[ModelMatch] = []
        state = 0
        for normalized_index, char in enumerate(normalized_text):
            while state and char not in self._nodes[state].children:
                state = self._nodes[state].failure
            state = self._nodes[state].children.get(char, 0)

            for key in self._nodes[state].outputs:
                start_index = normalized_index - len(key) + 1
                start = positions[start_index]
                end = positions[normalized_index] + 1
                for alias in self._aliases_by_key.get(key, []):
                    matches.append(
                        ModelMatch(
                            alias=alias.alias,
                            normalized_key=alias.normalized_key,
                            brand=alias.brand,
                            brand_en=alias.brand_en,
                            canonical_model=alias.canonical_model,
                            safe=alias.safe,
                            ambiguous=alias.ambiguous,
                            source_row=alias.source_row,
                            start=start,
                            end=end,
                        )
                    )

        return _filter_overlapping_matches(_dedupe_matches(matches))

    def _insert(self, key: str) -> None:
        state = 0
        for char in key:
            next_state = self._nodes[state].children.get(char)
            if next_state is None:
                next_state = len(self._nodes)
                self._nodes[state].children[char] = next_state
                self._nodes.append(_Node())
            state = next_state
        if key not in self._nodes[state].outputs:
            self._nodes[state].outputs.append(key)

    def _build_failures(self) -> None:
        queue: deque[int] = deque()
        for child in self._nodes[0].children.values():
            queue.append(child)

        while queue:
            state = queue.popleft()
            for char, child in self._nodes[state].children.items():
                failure = self._nodes[state].failure
                while failure and char not in self._nodes[failure].children:
                    failure = self._nodes[failure].failure
                self._nodes[child].failure = self._nodes[failure].children.get(char, 0)
                for key in self._nodes[self._nodes[child].failure].outputs:
                    if key not in self._nodes[child].outputs:
                        self._nodes[child].outputs.append(key)
                queue.append(child)


def _normalize_text_with_positions(text: str) -> tuple[str, list[int]]:
    chars: list[str] = []
    positions: list[int] = []
    for position, char in enumerate(text):
        normalized = normalize_model_key(char)
        for normalized_char in normalized:
            chars.append(normalized_char)
            positions.append(position)
    return "".join(chars), positions


def _dedupe_matches(matches: list[ModelMatch]) -> list[ModelMatch]:
    deduped: list[ModelMatch] = []
    seen: set[tuple[int, int, str, str, str, int]] = set()
    for match in matches:
        key = (
            match.start,
            match.end,
            match.brand,
            match.canonical_model,
            match.alias,
            match.source_row,
        )
        if key in seen:
            continue
        seen.add(key)
        deduped.append(match)
    return deduped


def _filter_overlapping_matches(matches: list[ModelMatch]) -> list[ModelMatch]:
    span_matches: dict[tuple[int, int], list[ModelMatch]] = {}
    for match in matches:
        span_matches.setdefault((match.start, match.end), []).append(match)

    accepted: list[tuple[int, int]] = []
    for span in sorted(span_matches):
        overlapping = [
            accepted_span for accepted_span in accepted if _spans_overlap(span, accepted_span)
        ]
        if not overlapping:
            accepted.append(span)
            continue

        span_length = span[1] - span[0]
        if all(span_length > accepted_span[1] - accepted_span[0] for accepted_span in overlapping):
            accepted = [
                accepted_span
                for accepted_span in accepted
                if not _spans_overlap(span, accepted_span)
            ]
            accepted.append(span)

    results: list[ModelMatch] = []
    for span in sorted(accepted):
        results.extend(span_matches[span])
    return results


def _spans_overlap(a: tuple[int, int], b: tuple[int, int]) -> bool:
    return not (a[1] <= b[0] or b[1] <= a[0])


def build_matcher_from_index_path(path: str | Path) -> ModelMatcher | None:
    try:
        return ModelMatcher(load_model_catalog_index(path))
    except FileNotFoundError:
        return None
    except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
        LOGGER.warning(
            "model catalog index load failed; falling back to legacy model matching",
            extra={"path": str(path), "error": str(exc)},
        )
        return None
