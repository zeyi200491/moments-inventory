from moments_inventory.parser import parse_content


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
