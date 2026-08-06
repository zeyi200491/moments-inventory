from moments_inventory.showcase import normalize_showcase_model_key


def test_normalize_showcase_model_key_collapses_spacing_and_brand_aliases() -> None:
    assert normalize_showcase_model_key("三星 A40") == "三星a40"
    assert normalize_showcase_model_key("samsung-a40") == "三星a40"
    assert normalize_showcase_model_key("佳能 IXUS 95") == "佳能ixus95"
    assert normalize_showcase_model_key("Canon_ixus95") == "佳能ixus95"
