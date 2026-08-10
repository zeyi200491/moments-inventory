from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class ShowcaseProduct:
    product_id: str
    model: str
    brand: str
    cost_price: int
    display_price: int
    visible: bool
    sold: bool
    published_at: str
    raw_copy: str
    display_copy: str
    cover_image_path: str
    created_at: str
    updated_at: str
    last_seen_import_id: str


@dataclass(slots=True)
class ShowcaseProductImage:
    image_id: str
    product_id: str
    image_path: str
    image_type: str
    sort_order: int
    is_cover: bool


@dataclass(slots=True)
class ShowcaseSettings:
    statement_text: str
    watermark_text: str
    customer_password_hash: str
    inventory_updated_at: str
