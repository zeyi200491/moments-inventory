from __future__ import annotations

from moments_inventory.ai_kefu.models import ProductRecord
from moments_inventory.ai_kefu.product_selection import (
    BudgetConstraint,
    ProductPreference,
    extract_budget_constraint,
    extract_product_preference,
    select_products_for_budget,
)


def _build_product(
    *,
    product_id: str,
    sale_price: int,
    profit_amount: int,
) -> ProductRecord:
    return ProductRecord(
        product_id=product_id,
        source_record_id=product_id,
        brand="佳能",
        model_std=product_id,
        sale_status="未售卖",
        is_functional=True,
        has_inspection_video=True,
        has_sample_output=True,
        cost_price=sale_price - profit_amount,
        sale_price=sale_price,
        profit_amount=profit_amount,
        source_name="老王",
        source_wxid="wxid_a",
        published_at="2026-05-01T10:00:00+08:00",
        image_path="a.jpg",
        video_path="a.mp4",
        raw_copy="功能正常",
        manual_review_needed=False,
    )


def test_extract_budget_constraint_supports_common_budget_expressions():
    assert extract_budget_constraint("预算300-500，有什么推荐") == BudgetConstraint(
        min_price=300,
        max_price=500,
        budget_text="300-500",
    )
    assert extract_budget_constraint("500左右有什么机子") == BudgetConstraint(
        min_price=450,
        max_price=550,
        budget_text="500左右",
    )
    assert extract_budget_constraint("300以内推荐一下") == BudgetConstraint(
        min_price=0,
        max_price=300,
        budget_text="300以内",
    )
    assert extract_budget_constraint("800以下拍人像的有吗") == BudgetConstraint(
        min_price=0,
        max_price=800,
        budget_text="800以下",
    )
    assert extract_budget_constraint("800以上的推荐几台") == BudgetConstraint(
        min_price=800,
        max_price=None,
        budget_text="800以上",
    )


def test_select_products_for_budget_prefers_profit_then_budget_ceiling():
    products = [
        _build_product(product_id="p1", sale_price=450, profit_amount=150),
        _build_product(product_id="p2", sale_price=498, profit_amount=150),
        _build_product(product_id="p3", sale_price=490, profit_amount=180),
        _build_product(product_id="p4", sale_price=505, profit_amount=220),
        _build_product(product_id="p5", sale_price=499, profit_amount=180),
    ]

    selected = select_products_for_budget(
        products,
        BudgetConstraint(min_price=300, max_price=500, budget_text="300-500"),
    )

    assert [product.product_id for product in selected] == ["p5", "p3", "p2", "p1"]


def test_select_products_for_budget_limits_to_twelve_items():
    products = [
        _build_product(product_id=f"p{index:02d}", sale_price=400 + index, profit_amount=200 - index)
        for index in range(15)
    ]

    selected = select_products_for_budget(
        products,
        BudgetConstraint(min_price=300, max_price=500, budget_text="300-500"),
    )

    assert len(selected) == 12


def test_extract_product_preference_only_reads_explicit_customer_preferences():
    assert extract_product_preference("预算300-500，想要索尼，要功能正常，最好有验机视频") == ProductPreference(
        brands=["索尼"],
        require_functional=True,
        require_inspection_video=True,
        require_sample_output=False,
    )
    assert extract_product_preference("预算500左右，最好有出片图") == ProductPreference(
        brands=[],
        require_functional=False,
        require_inspection_video=False,
        require_sample_output=True,
    )
    assert extract_product_preference("预算300-500，有什么推荐") is None


def test_select_products_for_budget_applies_preferences_only_when_present():
    products = [
        ProductRecord(
            product_id="sony-video",
            source_record_id="sony-video",
            brand="索尼",
            model_std="w530",
            sale_status="未售卖",
            is_functional=True,
            has_inspection_video=True,
            has_sample_output=False,
            cost_price=300,
            sale_price=498,
            profit_amount=180,
            source_name="老王",
            source_wxid="wxid_a",
            published_at="2026-05-01T10:00:00+08:00",
            image_path="",
            video_path="a.mp4",
            raw_copy="功能正常",
            manual_review_needed=False,
        ),
        ProductRecord(
            product_id="sony-no-video",
            source_record_id="sony-no-video",
            brand="索尼",
            model_std="t99",
            sale_status="未售卖",
            is_functional=True,
            has_inspection_video=False,
            has_sample_output=True,
            cost_price=280,
            sale_price=490,
            profit_amount=190,
            source_name="老王",
            source_wxid="wxid_a",
            published_at="2026-05-01T10:00:00+08:00",
            image_path="a.jpg",
            video_path="",
            raw_copy="功能正常",
            manual_review_needed=False,
        ),
        ProductRecord(
            product_id="canon-video",
            source_record_id="canon-video",
            brand="佳能",
            model_std="ixus95",
            sale_status="未售卖",
            is_functional=True,
            has_inspection_video=True,
            has_sample_output=True,
            cost_price=260,
            sale_price=499,
            profit_amount=210,
            source_name="老王",
            source_wxid="wxid_a",
            published_at="2026-05-01T10:00:00+08:00",
            image_path="a.jpg",
            video_path="a.mp4",
            raw_copy="功能正常",
            manual_review_needed=False,
        ),
    ]

    selected = select_products_for_budget(
        products,
        BudgetConstraint(min_price=300, max_price=500, budget_text="300-500"),
        preference=ProductPreference(
            brands=["索尼"],
            require_functional=True,
            require_inspection_video=True,
            require_sample_output=False,
        ),
    )

    assert [product.product_id for product in selected] == ["sony-video"]


def test_select_products_for_budget_prefers_cheaper_inventory_within_same_model():
    products = [
        ProductRecord(
            product_id="canon-cheap",
            source_record_id="canon-cheap",
            brand="佳能",
            model_std="ixus95",
            sale_status="未售卖",
            is_functional=True,
            has_inspection_video=True,
            has_sample_output=True,
            cost_price=320,
            sale_price=500,
            profit_amount=180,
            source_name="老王",
            source_wxid="wxid_a",
            published_at="2026-05-01T10:00:00+08:00",
            image_path="a.jpg",
            video_path="a.mp4",
            raw_copy="功能正常",
            manual_review_needed=False,
        ),
        ProductRecord(
            product_id="canon-expensive",
            source_record_id="canon-expensive",
            brand="佳能",
            model_std="ixus95",
            sale_status="未售卖",
            is_functional=True,
            has_inspection_video=True,
            has_sample_output=True,
            cost_price=350,
            sale_price=500,
            profit_amount=150,
            source_name="老王",
            source_wxid="wxid_a",
            published_at="2026-05-01T10:00:00+08:00",
            image_path="a.jpg",
            video_path="a.mp4",
            raw_copy="功能正常",
            manual_review_needed=False,
        ),
        _build_product(product_id="sony-one", sale_price=499, profit_amount=180),
    ]

    selected = select_products_for_budget(
        products,
        BudgetConstraint(min_price=300, max_price=500, budget_text="300-500"),
    )

    assert [product.product_id for product in selected] == ["canon-cheap", "sony-one"]
