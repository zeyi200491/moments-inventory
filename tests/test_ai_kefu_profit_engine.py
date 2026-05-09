from __future__ import annotations

from moments_inventory.ai_kefu.models import ProductRecord
from moments_inventory.ai_kefu.profit_engine import (
    BundleProfitAssessment,
    PricingRecommendation,
    assess_bundle_profit,
    extract_bundle_quantity,
    recommend_sale_price,
    select_preferred_same_model_products,
)


def _build_product(
    *,
    product_id: str,
    brand: str,
    model_std: str,
    cost_price: int,
    sale_price: int,
    profit_amount: int,
) -> ProductRecord:
    return ProductRecord(
        product_id=product_id,
        source_record_id=product_id,
        brand=brand,
        model_std=model_std,
        sale_status="未售卖",
        is_functional=True,
        has_inspection_video=True,
        has_sample_output=True,
        cost_price=cost_price,
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


def test_recommend_sale_price_uses_normal_markup_without_same_model_advantage():
    assert recommend_sale_price(520) == PricingRecommendation(
        base_markup=150,
        recommended_markup=150,
        sale_price=670,
        profit_amount=150,
        has_cost_advantage=False,
    )


def test_recommend_sale_price_uses_higher_markup_when_same_model_cost_advantage_is_obvious():
    assert recommend_sale_price(520, peer_cost_prices=[560, 580]) == PricingRecommendation(
        base_markup=150,
        recommended_markup=180,
        sale_price=700,
        profit_amount=180,
        has_cost_advantage=True,
    )
    assert recommend_sale_price(780, peer_cost_prices=[820, 860]) == PricingRecommendation(
        base_markup=180,
        recommended_markup=230,
        sale_price=1010,
        profit_amount=230,
        has_cost_advantage=True,
    )


def test_select_preferred_same_model_products_keeps_cheaper_inventory_for_same_model():
    products = [
        _build_product(
            product_id="canon-cheap",
            brand="佳能",
            model_std="ixus95",
            cost_price=320,
            sale_price=500,
            profit_amount=180,
        ),
        _build_product(
            product_id="canon-expensive",
            brand="佳能",
            model_std="ixus95",
            cost_price=350,
            sale_price=530,
            profit_amount=180,
        ),
        _build_product(
            product_id="sony-one",
            brand="索尼",
            model_std="w530",
            cost_price=310,
            sale_price=490,
            profit_amount=180,
        ),
    ]

    preferred = select_preferred_same_model_products(products)

    assert [product.product_id for product in preferred] == ["canon-cheap", "sony-one"]


def test_assess_bundle_profit_applies_discount_schedule_and_checks_average_profit_floor():
    valid = assess_bundle_profit(
        [
            _build_product(
                product_id="p1",
                brand="佳能",
                model_std="ixus95",
                cost_price=300,
                sale_price=480,
                profit_amount=180,
            ),
            _build_product(
                product_id="p2",
                brand="索尼",
                model_std="w530",
                cost_price=320,
                sale_price=490,
                profit_amount=170,
            ),
        ]
    )
    invalid = assess_bundle_profit(
        [
            _build_product(
                product_id="p1",
                brand="佳能",
                model_std="ixus95",
                cost_price=300,
                sale_price=460,
                profit_amount=160,
            ),
            _build_product(
                product_id="p2",
                brand="索尼",
                model_std="w530",
                cost_price=320,
                sale_price=480,
                profit_amount=160,
            ),
            _build_product(
                product_id="p3",
                brand="富士",
                model_std="j10",
                cost_price=330,
                sale_price=490,
                profit_amount=160,
            ),
            _build_product(
                product_id="p4",
                brand="尼康",
                model_std="s3100",
                cost_price=340,
                sale_price=500,
                profit_amount=160,
            ),
        ]
    )

    assert valid == BundleProfitAssessment(
        quantity=2,
        total_discount=20,
        total_profit_before_discount=350,
        total_profit_after_discount=330,
        average_profit_after_discount=165.0,
        meets_minimum_average_profit=True,
    )
    assert invalid == BundleProfitAssessment(
        quantity=4,
        total_discount=50,
        total_profit_before_discount=640,
        total_profit_after_discount=590,
        average_profit_after_discount=147.5,
        meets_minimum_average_profit=False,
    )


def test_extract_bundle_quantity_supports_common_multi_buy_expressions():
    assert extract_bundle_quantity("想买两台，有优惠吗") == 2
    assert extract_bundle_quantity("买3台的话怎么优惠") == 3
    assert extract_bundle_quantity("如果四台一起拿呢") == 4
    assert extract_bundle_quantity("先看看一台") is None
