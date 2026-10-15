from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class ShowcaseImportReviewStatus(str, Enum):
    """导入身份复核批次或记录的持久化状态。"""

    PENDING = "pending"
    COMMITTED = "committed"
    DISCARDED = "discarded"


class ShowcaseImportReviewDecision(str, Enum):
    """复核记录的身份处理决定。"""

    LINK = "link"
    CREATE = "create"
    SKIP = "skip"


@dataclass(slots=True)
class ShowcaseImportReviewBatch:
    batch_id: str
    source_scope: str
    status: ShowcaseImportReviewStatus
    created_at: str
    mode: str = "incremental"
    complete: bool = False
    source_path: str = ""
    source_label: str = ""
    source_fingerprint: str = ""
    parsed_row_count: int = 0
    missing_count: int = 0
    idempotency_key: str = ""
    result_json: str = "{}"
    completed_at: str = ""


@dataclass(slots=True)
class ShowcaseImportReviewRow:
    review_row_id: str
    batch_id: str
    row_number: int
    source_key: str
    status: ShowcaseImportReviewStatus
    snapshot_json: str
    created_at: str
    decision: ShowcaseImportReviewDecision | None = None
    product_id: str | None = None
    updated_at: str = ""


@dataclass(slots=True)
class ShowcaseSourceIdentityAlias:
    alias_id: str
    source_scope: str
    source_key: str
    product_id: str
    created_at: str


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
    short_selling_point: str = ""
    recommend_tags: str = ""
    public_id: str = ""
    row_version: int = 0
    source_scope: str = "default"
    source_available: bool = True
    source_display_price: int = 0
    source_display_copy: str = ""
    source_visible: bool = True
    last_seen_at: str = ""
    price_override: int | None = None
    copy_override: str | None = None
    visibility_override: bool | None = None
    override_origin: str = ""
    review_state: str = ""
    last_verified_at: str = ""


@dataclass(frozen=True, slots=True)
class ShowcaseProductSearch:
    query: str = ""
    brand: str = ""
    brands: tuple[str, ...] = ()
    price_min: int | None = None
    price_max: int | None = None
    tags: tuple[str, ...] = ()
    sort: str = "latest"
    limit: int = 80
    offset: int = 0


@dataclass(frozen=True, slots=True)
class ShowcaseProductSearchResult:
    products: list[ShowcaseProduct]
    total: int
    limit: int
    offset: int
    catalog_revision: str = "0"

    @property
    def has_more(self) -> bool:
        return self.offset + len(self.products) < self.total


@dataclass(frozen=True, slots=True)
class ShowcaseAdminProductSearch:
    query: str = ""
    model: str = ""
    brands: tuple[str, ...] = ()
    price_min: int | None = None
    price_max: int | None = None
    visible: bool | None = None
    sold: bool | None = None
    has_body_image: bool | None = None
    has_sample_image: bool | None = None
    manual_price: bool | None = None
    tags: tuple[str, ...] = ()
    section_id: str = ""
    updated_after: str = ""
    import_id: str = ""
    review_state: str = ""
    limit: int = 80
    offset: int = 0


@dataclass(frozen=True, slots=True)
class ShowcaseAdminProductSummary:
    product: ShowcaseProduct
    has_body_image: bool
    has_sample_image: bool
    manual_price: bool


@dataclass(frozen=True, slots=True)
class ShowcaseAdminProductSearchResult:
    products: list[ShowcaseAdminProductSummary]
    total: int
    limit: int
    offset: int

    @property
    def has_more(self) -> bool:
        return self.offset + len(self.products) < self.total


@dataclass(frozen=True, slots=True)
class ShowcaseAdminOperationLog:
    operation_id: str
    operation_type: str
    summary: str
    filter_text: str
    updated_count: int
    created_at: str
    undone_at: str


@dataclass(slots=True)
class ShowcaseProductImage:
    image_id: str
    product_id: str
    image_path: str
    image_type: str
    sort_order: int
    is_cover: bool
    source: str = "manual_upload"


@dataclass(slots=True)
class ShowcaseGalleryAlbum:
    album_id: str
    title: str
    description: str
    sort_order: int
    is_visible: bool
    created_at: str
    updated_at: str


@dataclass(slots=True)
class ShowcaseGalleryImage:
    image_id: str
    album_id: str
    image_path: str
    caption: str
    sort_order: int
    is_visible: bool
    created_at: str
    updated_at: str


@dataclass(slots=True)
class ShowcasePurchaseStep:
    step_id: str
    title: str
    description: str
    sort_order: int
    is_visible: bool
    created_at: str
    updated_at: str


@dataclass(slots=True)
class ShowcaseSettings:
    statement_text: str
    watermark_text: str
    customer_password_hash: str
    inventory_updated_at: str


@dataclass(slots=True)
class ShowcaseImportResult:
    import_id: str
    inserted_count: int
    updated_count: int
    missing_count: int


@dataclass(slots=True)
class ShowcaseAuthorizedPartner:
    partner_id: str
    name: str
    note: str
    sort_order: int
    active: bool


@dataclass(slots=True)
class ShowcaseSection:
    section_id: str
    title: str
    subtitle: str
    active: bool
    sort_order: int
    created_at: str
    updated_at: str


@dataclass(slots=True)
class ShowcaseSectionItem:
    item_id: str
    section_id: str
    product_id: str
    sort_order: int
    recommend_note: str
    created_at: str
    updated_at: str
