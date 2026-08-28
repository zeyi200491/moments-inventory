import subprocess
import sys

from moments_inventory.model_catalog import ModelCatalogAlias, ModelCatalogIndex
from moments_inventory.model_matcher import ModelMatcher
from moments_inventory.parser import parse_content


def _catalog_matcher() -> ModelMatcher:
    return ModelMatcher(
        ModelCatalogIndex(
            version=1,
            models=[],
            aliases_by_key={
                "佳能ixus100": [
                    ModelCatalogAlias(
                        alias="佳能IXUS100",
                        normalized_key="佳能ixus100",
                        brand="佳能",
                        brand_en="Canon",
                        canonical_model="IXUS 100 IS",
                        safe=True,
                        ambiguous=False,
                        source_row=2,
                    )
                ],
                "佳能ixus130": [
                    ModelCatalogAlias(
                        alias="佳能IXUS130",
                        normalized_key="佳能ixus130",
                        brand="佳能",
                        brand_en="Canon",
                        canonical_model="IXUS 130",
                        safe=True,
                        ambiguous=False,
                        source_row=3,
                    )
                ],
                "索尼wx300": [
                    ModelCatalogAlias(
                        alias="索尼WX300",
                        normalized_key="索尼wx300",
                        brand="索尼",
                        brand_en="Sony",
                        canonical_model="DSC-WX300",
                        safe=True,
                        ambiguous=False,
                        source_row=4,
                    )
                ],
            },
        )
    )


def _reference_only_catalog_matcher() -> ModelMatcher:
    return ModelMatcher(
        ModelCatalogIndex(
            version=1,
            models=[],
            aliases_by_key={
                "佳能ixus130": [
                    ModelCatalogAlias(
                        alias="佳能IXUS130",
                        normalized_key="佳能ixus130",
                        brand="佳能",
                        brand_en="Canon",
                        canonical_model="IXUS 130",
                        safe=True,
                        ambiguous=False,
                        source_row=3,
                    )
                ],
            },
        )
    )


def test_parse_content_extracts_model_price_and_serial():
    parsed = parse_content(
        "Canon IXUS 95 850 A12",
        model_keywords=["canon ixus 95", "sony t2"],
    )

    assert parsed.model == "canon ixus 95"
    assert parsed.price == 850
    assert parsed.serial_no == "A12"
    assert parsed.needs_manual is False


def test_parse_content_marks_manual_when_missing_price():
    parsed = parse_content(
        "sony t2 B88",
        model_keywords=["canon ixus 95", "sony t2"],
    )

    assert parsed.model == "sony t2"
    assert parsed.price is None
    assert parsed.needs_manual is True


def test_parse_content_supports_real_sales_copy():
    parsed = parse_content(
        "858 sony wx300 full set",
        model_keywords=["canon ixus 95", "sony t2", "sony wx300"],
    )

    assert parsed.model == "sony wx300"
    assert parsed.price == 858
    assert parsed.needs_manual is True


def test_parse_content_supports_price_when_money_symbol_is_before_digits():
    parsed = parse_content(
        "sony w130 410 H1973",
        model_keywords=["sony w130", "sony t2"],
    )

    assert parsed.model == "sony w130"
    assert parsed.price == 410
    assert parsed.serial_no == "H1973"
    assert parsed.needs_manual is False


def test_parse_content_supports_minolta_and_prairie_brands():
    minolta = parse_content(
        "228 minolta x31",
        model_keywords=["canon ixus 95", "sony t2", "minolta x31"],
    )
    prairie = parse_content(
        "128 prairie ts-4",
        model_keywords=["canon ixus 95", "sony t2", "prairie ts-4"],
    )

    assert minolta.model == "minolta x31"
    assert minolta.price == 228
    assert prairie.model == "prairie ts-4"
    assert prairie.price == 128


def test_parse_content_does_not_treat_date_as_price():
    parsed = parse_content(
        "5月18日 canon ixus 95 A12",
        model_keywords=["canon ixus 95"],
    )

    assert parsed.model == "canon ixus 95"
    assert parsed.price is None
    assert parsed.needs_manual is True


def test_parse_content_prefers_digits_adjacent_to_money_symbol_over_prefix_numbers():
    parsed = parse_content(
        "15新 宾得s55 319💰 编号H1",
        model_keywords=["宾得s55"],
    )

    assert parsed.model == "宾得s55"
    assert parsed.price == 319
    assert parsed.serial_no == "H1"


def test_parse_content_prefers_money_symbol_price_over_spec_numbers():
    parsed = parse_content(
        "索尼h70 1400万像素 509💰",
        model_keywords=["索尼h70"],
    )

    assert parsed.model == "索尼h70"
    assert parsed.price == 509


def test_parse_content_does_not_fallback_to_unrelated_numbers_when_money_symbol_has_no_adjacent_price():
    parsed = parse_content(
        "15新 宾得s55 💰 容后问 编号H1",
        model_keywords=["宾得s55"],
    )

    assert parsed.model == "宾得s55"
    assert parsed.price is None
    assert parsed.serial_no == "H1"


def test_parse_content_uses_catalog_matcher_and_ignores_pingti_reference_model():
    parsed = parse_content(
        "980💰佳能ixus100 香槟色\n成色不错。平替佳能ixus130 拍人像也是绝绝子！",
        model_keywords=[],
        model_matcher=_catalog_matcher(),
    )

    assert parsed.model == "IXUS 100 IS"
    assert parsed.price == 980
    assert parsed.model_confidence == "high"
    assert parsed.matched_alias == "佳能IXUS100"
    assert parsed.ignored_reference_models == ["IXUS 130"]


def test_parse_content_uses_catalog_matcher_for_models_missing_from_legacy_dict():
    parsed = parse_content(
        "索尼wx300 858💰 编号H12",
        model_keywords=[],
        model_matcher=_catalog_matcher(),
    )

    assert parsed.model == "DSC-WX300"
    assert parsed.price == 858
    assert parsed.serial_no == "H12"
    assert parsed.needs_manual is False


def test_parse_content_does_not_fallback_to_reference_catalog_match():
    parsed = parse_content(
        "平替佳能ixus130 980💰 编号H12",
        model_keywords=[],
        model_matcher=_catalog_matcher(),
    )

    assert parsed.model is None
    assert parsed.price == 980
    assert parsed.serial_no == "H12"
    assert parsed.needs_manual is True
    assert parsed.model_confidence == "ambiguous"
    assert parsed.ignored_reference_models == ["IXUS 130"]


def test_parse_content_falls_back_after_masking_reference_catalog_match():
    parsed = parse_content(
        "980💰佳能ixus100 香槟色\n成色不错。平替佳能ixus130 拍人像也是绝绝子！",
        model_keywords=[],
        model_matcher=_reference_only_catalog_matcher(),
    )

    assert parsed.model == "佳能ixus100"
    assert parsed.price == 980
    assert parsed.ignored_reference_models == ["IXUS 130"]


def test_parse_content_does_not_treat_spaced_catalog_model_number_as_price():
    parsed = parse_content(
        "佳能 ixus 100 编号A12",
        model_keywords=[],
        model_matcher=_catalog_matcher(),
    )

    assert parsed.model == "IXUS 100 IS"
    assert parsed.price is None
    assert parsed.serial_no == "A12"
    assert parsed.needs_manual is True


def test_parse_content_without_catalog_matcher_does_not_import_openpyxl():
    script = (
        "import sys;"
        "import moments_inventory.parser;"
        "print('openpyxl' in sys.modules)"
    )

    result = subprocess.run(
        [sys.executable, "-c", script],
        check=True,
        capture_output=True,
        text=True,
    )

    assert result.stdout.strip() == "False"
