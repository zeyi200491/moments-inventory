from __future__ import annotations

from moments_inventory.model_catalog import ModelCatalogAlias, ModelCatalogIndex
from moments_inventory.model_matcher import ModelMatcher


def _alias(
    alias: str,
    key: str,
    model: str,
    brand: str = "佳能",
    safe: bool = True,
    ambiguous: bool = False,
    source_row: int = 1,
) -> ModelCatalogAlias:
    return ModelCatalogAlias(
        alias=alias,
        normalized_key=key,
        brand=brand,
        brand_en=brand,
        canonical_model=model,
        safe=safe,
        ambiguous=ambiguous,
        source_row=source_row,
    )


def test_model_matcher_finds_multiple_models_with_positions():
    index = ModelCatalogIndex(
        version=1,
        models=[],
        aliases_by_key={
            "佳能ixus100": [_alias("佳能IXUS100", "佳能ixus100", "IXUS 100 IS")],
            "佳能ixus130": [_alias("佳能IXUS130", "佳能ixus130", "IXUS 130")],
        },
    )
    matcher = ModelMatcher(index)

    matches = matcher.find("980💰佳能ixus100 香槟色。平替佳能ixus130")

    assert [match.alias for match in matches] == ["佳能IXUS100", "佳能IXUS130"]
    assert [match.canonical_model for match in matches] == ["IXUS 100 IS", "IXUS 130"]
    assert matches[0].start < matches[1].start


def test_model_matcher_keeps_longest_overlapping_match():
    index = ModelCatalogIndex(
        version=1,
        models=[],
        aliases_by_key={
            "ixus100": [_alias("ixus100", "ixus100", "IXUS 100 IS")],
            "佳能ixus100": [_alias("佳能ixus100", "佳能ixus100", "IXUS 100 IS")],
        },
    )
    matcher = ModelMatcher(index)

    matches = matcher.find("佳能ixus100 980💰")

    assert [match.alias for match in matches] == ["佳能ixus100"]
    assert matches[0].start == 0
    assert matches[0].end == 9


def test_model_matcher_preserves_ambiguous_aliases_for_context_layer():
    index = ModelCatalogIndex(
        version=1,
        models=[],
        aliases_by_key={
            "a100": [
                _alias("a100", "a100", "A100", brand="爱国者", ambiguous=True),
                _alias("a100", "a100", "Coolpix A100", brand="尼康", ambiguous=True),
            ],
        },
    )
    matcher = ModelMatcher(index)

    matches = matcher.find("a100 300💰")

    assert len(matches) == 2
    assert {match.brand for match in matches} == {"爱国者", "尼康"}
    assert all(match.ambiguous for match in matches)


def test_model_matcher_preserves_same_model_alias_candidates_on_same_span():
    index = ModelCatalogIndex(
        version=1,
        models=[],
        aliases_by_key={
            "ixus100": [
                _alias("IXUS 100", "ixus100", "IXUS 100 IS", source_row=1),
                _alias("IXUS-100", "ixus100", "IXUS 100 IS", source_row=2),
            ],
        },
    )
    matcher = ModelMatcher(index)

    matches = matcher.find("ixus100")

    assert [(match.alias, match.source_row) for match in matches] == [
        ("IXUS 100", 1),
        ("IXUS-100", 2),
    ]
    assert {(match.start, match.end) for match in matches} == {(0, 7)}
