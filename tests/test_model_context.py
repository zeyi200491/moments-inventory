from __future__ import annotations

from moments_inventory.model_context import choose_primary_model
from moments_inventory.model_matcher import ModelMatch


def _match(
    alias: str,
    model: str,
    start: int,
    end: int,
    brand: str = "佳能",
    safe: bool = True,
    ambiguous: bool = False,
) -> ModelMatch:
    return ModelMatch(
        alias=alias,
        normalized_key=alias.lower(),
        brand=brand,
        brand_en=brand,
        canonical_model=model,
        safe=safe,
        ambiguous=ambiguous,
        source_row=1,
        start=start,
        end=end,
    )


def test_choose_primary_ignores_reference_model_after_price_context():
    text = "980💰佳能ixus100 香槟色\n成色不错。平替佳能ixus130 拍人像也是绝绝子！"
    matches = [
        _match("佳能ixus100", "IXUS 100 IS", text.index("佳能ixus100"), text.index("佳能ixus100") + 9),
        _match("佳能ixus130", "IXUS 130", text.index("佳能ixus130"), text.index("佳能ixus130") + 9),
    ]

    selection = choose_primary_model(text, matches, price=980)

    assert selection.model == "IXUS 100 IS"
    assert selection.confidence == "high"
    assert selection.matched_alias == "佳能ixus100"
    assert [item.canonical_model for item in selection.ignored_reference_models] == ["IXUS 130"]
    assert selection.needs_manual is False


def test_choose_primary_can_skip_reference_model_before_product_with_price():
    text = "平替佳能ixus130，佳能ixus100 980💰"
    matches = [
        _match("佳能ixus130", "IXUS 130", text.index("佳能ixus130"), text.index("佳能ixus130") + 9),
        _match("佳能ixus100", "IXUS 100 IS", text.index("佳能ixus100"), text.index("佳能ixus100") + 9),
    ]

    selection = choose_primary_model(text, matches, price=980)

    assert selection.model == "IXUS 100 IS"
    assert selection.confidence == "high"
    assert [item.canonical_model for item in selection.ignored_reference_models] == ["IXUS 130"]


def test_choose_primary_ignores_negative_model():
    text = "佳能ixus100 980💰，不是佳能ixus130"
    matches = [
        _match("佳能ixus100", "IXUS 100 IS", text.index("佳能ixus100"), text.index("佳能ixus100") + 9),
        _match("佳能ixus130", "IXUS 130", text.index("佳能ixus130"), text.index("佳能ixus130") + 9),
    ]

    selection = choose_primary_model(text, matches, price=(10, 14))

    assert selection.model == "IXUS 100 IS"
    assert selection.confidence == "high"
    assert [item.canonical_model for item in selection.ignored_reference_models] == ["IXUS 130"]


def test_choose_primary_does_not_treat_pixel_description_as_reference():
    text = "佳能ixus100 像素很好 980💰"
    start = text.index("佳能ixus100")
    matches = [_match("佳能ixus100", "IXUS 100 IS", start, start + 9)]

    selection = choose_primary_model(text, matches, price=980)

    assert selection.model == "IXUS 100 IS"
    assert selection.confidence == "high"
    assert selection.ignored_reference_models == []


def test_choose_primary_does_not_treat_very_new_as_negative():
    text = "佳能ixus100 非常新 980💰"
    start = text.index("佳能ixus100")
    matches = [_match("佳能ixus100", "IXUS 100 IS", start, start + 9)]

    selection = choose_primary_model(text, matches, price=980)

    assert selection.model == "IXUS 100 IS"
    assert selection.confidence == "high"
    assert selection.ignored_reference_models == []


def test_choose_primary_does_not_treat_model_before_pingti_as_reference():
    text = "佳能ixus100 平替佳能ixus130 980💰"
    primary_start = text.index("佳能ixus100")
    ref_start = text.index("佳能ixus130")
    matches = [
        _match("佳能ixus100", "IXUS 100 IS", primary_start, primary_start + 9),
        _match("佳能ixus130", "IXUS 130", ref_start, ref_start + 9),
    ]

    selection = choose_primary_model(text, matches, price=980)

    assert selection.model == "IXUS 100 IS"
    assert [item.canonical_model for item in selection.ignored_reference_models] == ["IXUS 130"]


def test_choose_primary_marks_pure_comparison_without_price_ambiguous():
    text = "佳能ixus100/ixus130 对比"
    matches = [
        _match("佳能ixus100", "IXUS 100 IS", 0, 9),
        _match("ixus130", "IXUS 130", 10, 17),
    ]

    selection = choose_primary_model(text, matches, price=None)

    assert selection.model is None
    assert selection.confidence == "ambiguous"
    assert selection.needs_manual is True


def test_choose_primary_marks_same_span_ambiguous_candidates_manual():
    text = "a100 300💰"
    matches = [
        _match("a100", "A100", 0, 4, brand="爱国者", ambiguous=True),
        _match("a100", "Coolpix A100", 0, 4, brand="尼康", ambiguous=True),
    ]

    selection = choose_primary_model(text, matches, price=(5, 9))

    assert selection.model is None
    assert selection.confidence == "ambiguous"
    assert selection.needs_manual is True
