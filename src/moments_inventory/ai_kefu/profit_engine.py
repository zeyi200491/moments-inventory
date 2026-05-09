from __future__ import annotations

from dataclasses import dataclass
import re

from moments_inventory.ai_kefu.models import ProductRecord


LOW_PRICE_THRESHOLD = 600
LOW_PRICE_BASE_MARKUP = 150
LOW_PRICE_ADVANTAGE_MARKUP = 180
HIGH_PRICE_BASE_MARKUP = 180
HIGH_PRICE_ADVANTAGE_MARKUP = 230
OBVIOUS_COST_ADVANTAGE_DIFF = 20
MINIMUM_AVERAGE_BUNDLE_PROFIT = 150.0


@dataclass(slots=True, frozen=True)
class PricingRecommendation:
    base_markup: int
    recommended_markup: int
    sale_price: int
    profit_amount: int
    has_cost_advantage: bool


@dataclass(slots=True, frozen=True)
class BundleProfitAssessment:
    quantity: int
    total_discount: int
    total_profit_before_discount: int
    total_profit_after_discount: int
    average_profit_after_discount: float
    meets_minimum_average_profit: bool


def recommend_sale_price(
    cost_price: int,
    peer_cost_prices: list[int] | None = None,
) -> PricingRecommendation:
    base_markup, advantage_markup = _markup_rule(cost_price)
    has_cost_advantage = _has_obvious_cost_advantage(cost_price, peer_cost_prices or [])
    recommended_markup = advantage_markup if has_cost_advantage else base_markup
    return PricingRecommendation(
        base_markup=base_markup,
        recommended_markup=recommended_markup,
        sale_price=cost_price + recommended_markup,
        profit_amount=recommended_markup,
        has_cost_advantage=has_cost_advantage,
    )


def select_preferred_same_model_products(products: list[ProductRecord]) -> list[ProductRecord]:
    grouped: dict[tuple[str, str], ProductRecord] = {}
    ordered_keys: list[tuple[str, str]] = []
    for product in products:
        group_key = (product.brand, product.model_std)
        preferred = grouped.get(group_key)
        if preferred is None:
            grouped[group_key] = product
            ordered_keys.append(group_key)
            continue
        if _is_better_same_model_candidate(product, preferred):
            grouped[group_key] = product
    return [grouped[group_key] for group_key in ordered_keys]


def assess_bundle_profit(products: list[ProductRecord]) -> BundleProfitAssessment:
    quantity = len(products)
    total_profit_before_discount = sum(product.profit_amount for product in products)
    total_discount = _bundle_discount(quantity)
    total_profit_after_discount = total_profit_before_discount - total_discount
    average_profit_after_discount = (
        total_profit_after_discount / quantity if quantity > 0 else 0.0
    )
    return BundleProfitAssessment(
        quantity=quantity,
        total_discount=total_discount,
        total_profit_before_discount=total_profit_before_discount,
        total_profit_after_discount=total_profit_after_discount,
        average_profit_after_discount=average_profit_after_discount,
        meets_minimum_average_profit=average_profit_after_discount >= MINIMUM_AVERAGE_BUNDLE_PROFIT,
    )


def extract_bundle_quantity(message: str) -> int | None:
    normalized = "".join(message.split())
    numeric_match = re.search(r"(\d+)台", normalized)
    if numeric_match:
        quantity = int(numeric_match.group(1))
        return quantity if quantity >= 2 else None

    for keyword, quantity in (("两台", 2), ("二台", 2), ("三台", 3), ("四台", 4)):
        if keyword in normalized:
            return quantity
    return None


def _markup_rule(cost_price: int) -> tuple[int, int]:
    if cost_price <= LOW_PRICE_THRESHOLD:
        return LOW_PRICE_BASE_MARKUP, LOW_PRICE_ADVANTAGE_MARKUP
    return HIGH_PRICE_BASE_MARKUP, HIGH_PRICE_ADVANTAGE_MARKUP


def _has_obvious_cost_advantage(cost_price: int, peer_cost_prices: list[int]) -> bool:
    if not peer_cost_prices:
        return False
    lowest_peer_cost = min(peer_cost_prices)
    return cost_price + OBVIOUS_COST_ADVANTAGE_DIFF <= lowest_peer_cost


def _is_better_same_model_candidate(candidate: ProductRecord, current: ProductRecord) -> bool:
    return (
        candidate.cost_price,
        -candidate.profit_amount,
        candidate.product_id,
    ) < (
        current.cost_price,
        -current.profit_amount,
        current.product_id,
    )


def _bundle_discount(quantity: int) -> int:
    if quantity >= 4:
        return 50
    if quantity == 3:
        return 30
    if quantity == 2:
        return 20
    return 0
