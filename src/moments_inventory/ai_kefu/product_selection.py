from __future__ import annotations

from dataclasses import dataclass
import re

from moments_inventory.ai_kefu.models import ProductRecord
from moments_inventory.ai_kefu.profit_engine import select_preferred_same_model_products


ACTIVE_PRODUCT_STATUSES = {"未售出", "未售卖"}
DEFAULT_RECOMMENDATION_LIMIT = 12


@dataclass(slots=True, frozen=True)
class BudgetConstraint:
    min_price: int
    max_price: int | None
    budget_text: str


@dataclass(slots=True, frozen=True)
class ProductPreference:
    brands: list[str]
    require_functional: bool
    require_inspection_video: bool
    require_sample_output: bool


def extract_budget_constraint(message: str) -> BudgetConstraint | None:
    normalized = "".join(message.split())

    range_match = re.search(r"(\d{2,5})\s*[-~到至]\s*(\d{2,5})", normalized)
    if range_match:
        min_price = int(range_match.group(1))
        max_price = int(range_match.group(2))
        if min_price > max_price:
            min_price, max_price = max_price, min_price
        return BudgetConstraint(
            min_price=min_price,
            max_price=max_price,
            budget_text=f"{min_price}-{max_price}",
        )

    around_match = re.search(r"(\d{2,5})左右", normalized)
    if around_match:
        center = int(around_match.group(1))
        return BudgetConstraint(
            min_price=max(center - 50, 0),
            max_price=center + 50,
            budget_text=f"{center}左右",
        )

    upper_match = re.search(r"(\d{2,5})(?:以内|以下)", normalized)
    if upper_match:
        max_price = int(upper_match.group(1))
        return BudgetConstraint(
            min_price=0,
            max_price=max_price,
            budget_text=f"{max_price}{'以内' if '以内' in normalized else '以下'}",
        )

    lower_match = re.search(r"(\d{2,5})以上", normalized)
    if lower_match:
        min_price = int(lower_match.group(1))
        return BudgetConstraint(
            min_price=min_price,
            max_price=None,
            budget_text=f"{min_price}以上",
        )

    return None


def extract_product_preference(message: str) -> ProductPreference | None:
    normalized = "".join(message.split())
    brands = [
        brand
        for brand in ("佳能", "索尼", "富士", "奥林巴斯", "柯达", "尼康", "卡西欧", "三星", "松下")
        if brand in normalized
    ]
    preference = ProductPreference(
        brands=brands,
        require_functional=("功能正常" in normalized),
        require_inspection_video=("验机视频" in normalized or "有视频" in normalized or "带视频" in normalized),
        require_sample_output=("出片图" in normalized or "样片" in normalized or "有图" in normalized),
    )
    if (
        not preference.brands
        and not preference.require_functional
        and not preference.require_inspection_video
        and not preference.require_sample_output
    ):
        return None
    return preference


def select_products_for_budget(
    products: list[ProductRecord],
    budget_constraint: BudgetConstraint,
    *,
    preference: ProductPreference | None = None,
    limit: int = DEFAULT_RECOMMENDATION_LIMIT,
) -> list[ProductRecord]:
    filtered_products = [
        product
        for product in products
        if product.sale_status in ACTIVE_PRODUCT_STATUSES
        and product.sale_price >= budget_constraint.min_price
        and (
            budget_constraint.max_price is None
            or product.sale_price <= budget_constraint.max_price
        )
    ]
    if preference is not None:
        filtered_products = [
            product
            for product in filtered_products
            if _matches_preference(product, preference)
        ]
    filtered_products = select_preferred_same_model_products(filtered_products)
    filtered_products.sort(
        key=lambda product: (
            -product.profit_amount,
            _budget_ceiling_gap(product, budget_constraint),
            product.sale_price,
            product.product_id,
        )
    )
    return filtered_products[:limit]


def _budget_ceiling_gap(product: ProductRecord, budget_constraint: BudgetConstraint) -> int:
    if budget_constraint.max_price is None:
        return 0
    return budget_constraint.max_price - product.sale_price


def _matches_preference(product: ProductRecord, preference: ProductPreference) -> bool:
    if preference.brands and product.brand not in preference.brands:
        return False
    if preference.require_functional and not product.is_functional:
        return False
    if preference.require_inspection_video and not product.has_inspection_video:
        return False
    if preference.require_sample_output and not product.has_sample_output:
        return False
    return True
