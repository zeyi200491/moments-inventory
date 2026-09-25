from __future__ import annotations

import csv
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Self
import os
import secrets
import uuid

from fastapi import APIRouter, Cookie, Depends, File, Form, HTTPException, UploadFile
from fastapi import Response
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field, field_validator, model_validator
from PIL import Image, UnidentifiedImageError
from moments_inventory.showcase_web import bulk_service

from moments_inventory.showcase_web.auth import hash_password, verify_password
from moments_inventory.showcase_web.models import (
    ShowcaseGalleryAlbum,
    ShowcaseGalleryImage,
    ShowcaseAdminProductSearch,
    ShowcaseAdminProductSummary,
    ShowcaseProduct,
    ShowcaseProductImage,
    ShowcaseProductSearch,
    ShowcasePurchaseStep,
    ShowcaseSection,
    ShowcaseSectionItem,
)
from moments_inventory.showcase_web.repository import (
    SQLiteShowcaseRepository,
    list_sales_tags,
    product_sales_tags,
)
from moments_inventory.showcase_web.sample_images import (
    SampleImageAsset,
    SampleImageImportResult,
    SampleMatchingGroup,
    SampleMatchingProduct,
    SampleMatchingSummary,
    build_sample_matching_summary,
    import_sample_images,
    list_sample_image_assets,
    list_sample_matching_groups,
    list_sample_matching_products,
)


_MAX_UPLOAD_BYTES = 10 * 1024 * 1024
_MAX_IMAGE_PIXELS = 40_000_000
_IMAGE_SUFFIXES = {"JPEG": ".jpg", "PNG": ".png", "WEBP": ".webp"}
_CSV_FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r", "\n")


class _CsvLineSink:
    """让 csv.writer 直接返回单行文本，避免累积完整 CSV。"""

    @staticmethod
    def write(value: str) -> str:
        return value


def _safe_csv_text(value: str) -> str:
    """阻止电子表格把来自库存数据的文本识别为公式。"""
    if value.startswith(_CSV_FORMULA_PREFIXES):
        return f"'{value}"
    return value


async def _validated_image_upload(file: UploadFile, directory: Path) -> tuple[Path, str]:
    """限流写入临时文件并校验真实图片格式，调用方负责最终移动或清理。"""
    directory.mkdir(parents=True, exist_ok=True)
    temporary = directory / f".{uuid.uuid4().hex}.upload"
    written = 0
    try:
        with temporary.open("wb") as target:
            while chunk := await file.read(1024 * 1024):
                written += len(chunk)
                if written > _MAX_UPLOAD_BYTES:
                    raise HTTPException(413, "图片不能超过 10MB")
                target.write(chunk)
        if written == 0:
            raise HTTPException(400, "图片文件为空")
        try:
            with Image.open(temporary) as image:
                image_format = str(image.format or "").upper()
                width, height = image.size
                if image_format not in _IMAGE_SUFFIXES:
                    raise HTTPException(400, "仅支持 JPEG、PNG、WEBP 图片")
                if width <= 0 or height <= 0 or width * height > _MAX_IMAGE_PIXELS:
                    raise HTTPException(400, "图片像素尺寸过大")
                image.verify()
        except (UnidentifiedImageError, OSError) as error:
            raise HTTPException(400, "文件不是有效图片") from error
        return temporary, _IMAGE_SUFFIXES[image_format]
    except Exception:
        temporary.unlink(missing_ok=True)
        raise
    finally:
        await file.close()


def _image_url(path: str) -> str:
    if not path:
        return ""
    if path.startswith(("https://", "http://", "/")):
        return path
    return "/" + path


class PublicProductResponse(BaseModel):
    productId: str
    publicId: str = ""
    rowVersion: int = 0
    coverImageUrl: str = ""
    coverImageType: str = ""
    model: str
    brand: str
    displayPrice: int
    displayCopy: str
    coverImagePath: str
    publishedAt: str
    shortSellingPoint: str
    recommendTags: list[str] = Field(default_factory=list)

    @classmethod
    def from_product(
        cls,
        product: ShowcaseProduct,
        *,
        fallback_cover_image_path: str = "",
    ) -> "PublicProductResponse":
        return cls(
            productId=product.product_id,
            publicId=product.public_id,
            rowVersion=product.row_version,
            coverImageUrl=_image_url(product.cover_image_path or fallback_cover_image_path),
            coverImageType=(
                "sample"
                if (product.cover_image_path or fallback_cover_image_path).replace("\\", "/").startswith("sample-images/")
                else ("body" if product.cover_image_path else ("sample" if fallback_cover_image_path else ""))
            ),
            model=product.model,
            brand=product.brand,
            displayPrice=product.display_price,
            displayCopy=product.display_copy or product.raw_copy,
            coverImagePath=product.cover_image_path or fallback_cover_image_path,
            publishedAt=product.published_at,
            shortSellingPoint=product.short_selling_point,
            recommendTags=product_sales_tags(product),
        )


class PublicProductsResponse(BaseModel):
    products: list[PublicProductResponse] = Field(default_factory=list)
    total: int
    limit: int
    offset: int
    hasMore: bool
    catalogRevision: str = "0"


class PublicPricePresetResponse(BaseModel):
    label: str
    priceMin: int
    priceMax: int


class PublicFiltersResponse(BaseModel):
    brands: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    pricePresets: list[PublicPricePresetResponse] = Field(default_factory=list)


class PublicSectionProductResponse(PublicProductResponse):
    recommendNote: str


class PublicSectionResponse(BaseModel):
    sectionId: str
    title: str
    subtitle: str
    products: list[PublicSectionProductResponse] = Field(default_factory=list)


class PublicSectionsResponse(BaseModel):
    sections: list[PublicSectionResponse] = Field(default_factory=list)


class PublicGalleryImageResponse(BaseModel):
    imageId: str
    imagePath: str
    caption: str
    sortOrder: int

    @classmethod
    def from_image(cls, image: ShowcaseGalleryImage) -> "PublicGalleryImageResponse":
        return cls(
            imageId=image.image_id,
            imagePath=image.image_path,
            caption=image.caption,
            sortOrder=image.sort_order,
        )


class PublicGalleryAlbumResponse(BaseModel):
    albumId: str
    title: str
    description: str
    sortOrder: int
    images: list[PublicGalleryImageResponse] = Field(default_factory=list)


class PublicGalleryResponse(BaseModel):
    albums: list[PublicGalleryAlbumResponse] = Field(default_factory=list)


class PublicPurchaseStepResponse(BaseModel):
    stepId: str
    title: str
    description: str
    sortOrder: int

    @classmethod
    def from_step(cls, step: ShowcasePurchaseStep) -> "PublicPurchaseStepResponse":
        return cls(
            stepId=step.step_id,
            title=step.title,
            description=step.description,
            sortOrder=step.sort_order,
        )


class PublicPurchaseStepsResponse(BaseModel):
    steps: list[PublicPurchaseStepResponse] = Field(default_factory=list)


class CustomerAccessRequest(BaseModel):
    password: str = Field(min_length=1, max_length=256)


class CustomerAccessResponse(BaseModel):
    ok: bool


class CustomerAccessStatusResponse(BaseModel):
    requiresPassword: bool
    authorized: bool


class PublicPartnerResponse(BaseModel):
    partnerId: str
    name: str
    note: str


class PublicSettingsResponse(BaseModel):
    statementText: str
    shopIntroText: str
    watermarkText: str
    inventoryUpdatedAt: str
    partners: list[PublicPartnerResponse] = Field(default_factory=list)


class AdminProductResponse(PublicProductResponse):
    visible: bool
    sold: bool
    costPrice: int
    hasBodyImage: bool = False
    hasSampleImage: bool = False
    manualPrice: bool = False
    reviewState: str = ""
    sourceAvailable: bool = True
    overrideOrigin: str = ""
    sourceDisplayPrice: int = 0
    sourceDisplayCopy: str = ""
    sourceVisible: bool = True
    priceOverridden: bool = False
    copyOverridden: bool = False
    visibilityOverridden: bool = False

    @classmethod
    def from_product(cls, product: ShowcaseProduct) -> "AdminProductResponse":
        return cls(
            productId=product.product_id,
            publicId=product.public_id,
            rowVersion=product.row_version,
            coverImageUrl=_image_url(product.cover_image_path),
            coverImageType="body" if product.cover_image_path else "",
            model=product.model,
            brand=product.brand,
            displayPrice=product.display_price,
            displayCopy=product.display_copy or product.raw_copy,
            coverImagePath=product.cover_image_path,
            publishedAt=product.published_at,
            shortSellingPoint=product.short_selling_point,
            recommendTags=_split_tags(product.recommend_tags),
            visible=product.visible,
            sold=product.sold,
            costPrice=product.cost_price,
            hasBodyImage=bool(product.cover_image_path),
            hasSampleImage=False,
            manualPrice=product.price_override is not None,
            reviewState=product.review_state,
            sourceAvailable=product.source_available,
            overrideOrigin=product.override_origin,
            sourceDisplayPrice=product.source_display_price,
            sourceDisplayCopy=product.source_display_copy,
            sourceVisible=product.source_visible,
            priceOverridden=product.price_override is not None,
            copyOverridden=product.copy_override is not None,
            visibilityOverridden=product.visibility_override is not None,
        )

    @classmethod
    def from_summary(cls, summary: ShowcaseAdminProductSummary) -> "AdminProductResponse":
        response = cls.from_product(summary.product)
        response.hasBodyImage = summary.has_body_image
        response.hasSampleImage = summary.has_sample_image
        response.manualPrice = summary.manual_price
        return response


class AdminProductsResponse(BaseModel):
    products: list[AdminProductResponse] = Field(default_factory=list)
    total: int = 0
    limit: int = 80
    offset: int = 0
    hasMore: bool = False


class PublicProductImageResponse(BaseModel):
    imageId: str
    imagePath: str
    imageType: str
    sortOrder: int
    isCover: bool

    @classmethod
    def from_image(cls, image: ShowcaseProductImage) -> "PublicProductImageResponse":
        return cls(
            imageId=image.image_id,
            imagePath=image.image_path,
            imageType=image.image_type,
            sortOrder=image.sort_order,
            isCover=image.is_cover,
        )


class PublicProductDetailResponse(PublicProductResponse):
    rawCopy: str
    images: list[PublicProductImageResponse] = Field(default_factory=list)

    @classmethod
    def from_product_and_images(
        cls,
        product: ShowcaseProduct,
        images: list[ShowcaseProductImage],
    ) -> "PublicProductDetailResponse":
        base = PublicProductResponse.from_product(product)
        return cls(
            **base.model_dump(),
            rawCopy=product.raw_copy,
            images=[PublicProductImageResponse.from_image(image) for image in images[:9]],
        )


class AdminLoginRequest(BaseModel):
    password: str = Field(min_length=1, max_length=256)


class AdminLoginResponse(BaseModel):
    ok: bool


class AdminProductPatchRequest(BaseModel):
    expectedVersion: int = Field(ge=0)
    resetOverrides: list[str] = Field(default_factory=list, max_length=3)
    model: str | None = Field(default=None, max_length=160)
    brand: str | None = Field(default=None, max_length=80)
    displayPrice: int | None = Field(default=None, ge=0)
    displayCopy: str | None = Field(default=None, max_length=10000)
    shortSellingPoint: str | None = Field(default=None, max_length=500)
    recommendTags: list[str] | None = Field(default=None, max_length=20)
    visible: bool | None = None
    sold: bool | None = None


class AdminProductCreateRequest(BaseModel):
    productId: str = Field(min_length=1, max_length=160)
    model: str = Field(min_length=1, max_length=160)
    brand: str = Field(min_length=1, max_length=80)
    displayPrice: int = Field(ge=0)
    displayCopy: str = Field(default="", max_length=10000)
    shortSellingPoint: str = Field(default="", max_length=500)
    recommendTags: list[str] = Field(default_factory=list, max_length=20)
    visible: bool = True
    sectionIds: list[str] = Field(default_factory=list, max_length=20)
    sectionRecommendNote: str = Field(default="", max_length=500)
    sectionSortOrder: int = Field(default=0, ge=0)


class AdminBatchPriceRequest(BaseModel):
    mode: str = Field(pattern="^(increment|set)$")
    amount: int = Field(ge=0)
    brand: str | None = Field(default=None, max_length=80)
    minPrice: int | None = Field(default=None, ge=0)
    maxPrice: int | None = Field(default=None, ge=0)
    query: str | None = Field(default=None, max_length=200)
    visibleOnly: bool = False


class AdminBatchPriceResponse(BaseModel):
    updatedCount: int


class AdminBulkProductFilters(BaseModel):
    query: str = Field(default="", max_length=200)
    model: str = Field(default="", max_length=160)
    brand: str = Field(default="", max_length=80)
    brands: list[str] = Field(default_factory=list, max_length=80)
    priceMin: int | None = Field(default=None, ge=0)
    priceMax: int | None = Field(default=None, ge=0)
    visible: bool | None = None
    sold: bool | None = None
    hasBodyImage: bool | None = None
    hasSampleImage: bool | None = None
    manualPrice: bool | None = None
    tags: list[str] = Field(default_factory=list, max_length=50)
    sectionId: str = Field(default="", max_length=200)
    updatedAfter: str = Field(default="", max_length=80)
    importId: str = Field(default="", max_length=200)
    reviewState: str = Field(default="", max_length=80)

    def has_narrowing_constraint(self) -> bool:
        return any((
            self.query.strip(),
            self.model.strip(),
            self.brand.strip(),
            any(brand.strip() for brand in self.brands),
            self.priceMin is not None,
            self.priceMax is not None,
            self.hasBodyImage is not None,
            self.hasSampleImage is not None,
            self.manualPrice is not None,
            any(tag.strip() for tag in self.tags),
            self.sectionId.strip(),
            self.updatedAfter.strip(),
            self.importId.strip(),
            self.reviewState.strip(),
        ))

    @model_validator(mode="after")
    def validate_price_range(self) -> Self:
        if self.priceMin is not None and self.priceMax is not None and self.priceMin > self.priceMax:
            raise ValueError("最低价不能高于最高价")
        return self


class AdminBulkOperationRequest(BaseModel):
    scope: str = Field(pattern="^(selected|filtered|all)$")
    operation: str = Field(pattern="^(price|hide|show)$")
    priceMode: str = Field(default="increment", pattern="^(increment|decrement|fixed_final)$")
    amount: int = Field(default=0, ge=0)
    productIds: list[str] = Field(default_factory=list, max_length=5000)
    publicIds: list[str] = Field(default_factory=list, max_length=5000)
    filters: AdminBulkProductFilters = Field(default_factory=AdminBulkProductFilters)

    @field_validator("productIds", "publicIds")
    @classmethod
    def normalize_product_references(cls, references: list[str]) -> list[str]:
        normalized = [reference.strip() for reference in references]
        if any(not reference for reference in normalized):
            raise ValueError("商品引用不能为空")
        return normalized

    @model_validator(mode="after")
    def validate_scope_and_price(self) -> Self:
        has_references = bool(self.productIds or self.publicIds)
        if self.scope == "selected" and not has_references:
            raise ValueError("选中商品范围必须至少提交一个商品引用")
        if self.scope != "selected" and has_references:
            raise ValueError("只有选中商品范围可以提交商品引用")
        if self.scope == "filtered" and not self.filters.has_narrowing_constraint():
            raise ValueError("筛选范围必须包含收窄条件；如需处理全部展示中未售商品，请选择全部库存")
        if self.operation == "price" and self.priceMode in {"increment", "decrement"} and self.amount <= 0:
            raise ValueError("加减价金额必须大于 0")
        return self


class AdminBulkPriceStatsResponse(BaseModel):
    minimum: int | None = None
    maximum: int | None = None
    totalDelta: int = 0


class AdminBulkPreviewItemResponse(BaseModel):
    productId: str
    publicId: str = ""
    rowVersion: int = 0
    model: str
    brand: str
    sourcePrice: int
    oldPrice: int
    newPrice: int
    delta: int
    oldVisible: bool
    newVisible: bool
    sold: bool
    changed: bool = False
    skippedReason: str = ""


class AdminBulkPreviewResponse(BaseModel):
    previewId: str = ""
    expiresAt: str = ""
    operation: str
    total: int
    matchedCount: int = 0
    changedCount: int = 0
    unchangedCount: int = 0
    skippedCount: int = 0
    skipReasons: dict[str, int] = Field(default_factory=dict)
    priceStats: AdminBulkPriceStatsResponse = Field(default_factory=AdminBulkPriceStatsResponse)
    displayedCount: int = 0
    truncated: bool = False
    items: list[AdminBulkPreviewItemResponse] = Field(default_factory=list)


class AdminBulkApplyRequest(BaseModel):
    previewId: str = Field(min_length=1, max_length=128)
    idempotencyKey: str = Field(min_length=1, max_length=128)


class AdminUndoRequest(BaseModel):
    idempotencyKey: str = Field(min_length=1, max_length=128)


class AdminBulkApplyResponse(BaseModel):
    ok: bool
    operationId: str
    updatedCount: int


class AdminOperationResponse(BaseModel):
    operationId: str
    operationType: str
    summary: str
    filterText: str
    updatedCount: int
    createdAt: str
    undoneAt: str


class AdminOperationsResponse(BaseModel):
    operations: list[AdminOperationResponse] = Field(default_factory=list)


class AdminDiagnosticsResponse(BaseModel):
    counts: dict[str, int] = Field(default_factory=dict)
    abnormalProducts: list[AdminProductResponse] = Field(default_factory=list)


class AdminBackupResponse(BaseModel):
    backupPath: str
    createdAt: str


class AdminSampleBindingRequest(BaseModel):
    productId: str = Field(default="", max_length=200)
    brand: str = Field(default="", max_length=80)
    modelKey: str = Field(default="", max_length=200)
    folderPath: str = Field(min_length=1, max_length=500)


class AdminSampleImportResultResponse(BaseModel):
    availableModelCount: int
    matchedProductCount: int
    insertedImageCount: int
    unmatchedProductCount: int

    @classmethod
    def from_result(cls, result: SampleImageImportResult) -> "AdminSampleImportResultResponse":
        return cls(
            availableModelCount=result.available_model_count,
            matchedProductCount=result.matched_product_count,
            insertedImageCount=result.inserted_image_count,
            unmatchedProductCount=result.unmatched_product_count,
        )


class AdminSampleBindingResponse(BaseModel):
    ok: bool
    bindingKey: str
    folderPath: str
    importResult: AdminSampleImportResultResponse | None = None


class AdminSampleMatchingSummaryResponse(BaseModel):
    totalProducts: int
    assetModelCount: int
    matchedProductCount: int
    missingProductCount: int
    lowConfidenceProductCount: int
    coverageRate: float


class AdminSampleMatchingRebuildResponse(BaseModel):
    ok: bool
    summary: AdminSampleMatchingSummaryResponse
    importResult: AdminSampleImportResultResponse


class AdminSampleMatchingAssetResponse(BaseModel):
    brand: str
    modelFolder: str
    folderPath: str
    modelKey: str
    imageCount: int

    @classmethod
    def from_asset(cls, asset: SampleImageAsset) -> "AdminSampleMatchingAssetResponse":
        return cls(
            brand=asset.brand,
            modelFolder=asset.model_folder,
            folderPath=asset.folder_path,
            modelKey=asset.model_key,
            imageCount=asset.image_count,
        )


class AdminSampleMatchingAssetsResponse(BaseModel):
    assets: list[AdminSampleMatchingAssetResponse] = Field(default_factory=list)


class AdminSampleMatchingProductResponse(BaseModel):
    productId: str
    model: str
    brand: str
    status: str
    confidence: int
    reason: str
    folderPath: str
    imageCount: int

    @classmethod
    def from_item(cls, item: SampleMatchingProduct) -> "AdminSampleMatchingProductResponse":
        return cls(
            productId=item.product_id,
            model=item.model,
            brand=item.brand,
            status=item.status,
            confidence=item.confidence,
            reason=item.reason,
            folderPath=item.folder_path,
            imageCount=item.image_count,
        )


class AdminSampleMatchingProductsResponse(BaseModel):
    products: list[AdminSampleMatchingProductResponse] = Field(default_factory=list)


class AdminSampleMatchingBindRequest(BaseModel):
    productId: str = Field(min_length=1, max_length=200)
    folderPath: str = Field(min_length=1, max_length=500)


class AdminSampleMatchingGroupResponse(BaseModel):
    brand: str
    model: str
    status: str
    confidence: int
    reason: str
    folderPath: str
    imageCount: int
    productCount: int
    productIds: list[str] = Field(default_factory=list)

    @classmethod
    def from_group(cls, group: SampleMatchingGroup) -> "AdminSampleMatchingGroupResponse":
        return cls(
            brand=group.brand,
            model=group.model,
            status=group.status,
            confidence=group.confidence,
            reason=group.reason,
            folderPath=group.folder_path,
            imageCount=group.image_count,
            productCount=group.product_count,
            productIds=group.product_ids,
        )


class AdminSampleMatchingGroupsResponse(BaseModel):
    groups: list[AdminSampleMatchingGroupResponse] = Field(default_factory=list)


class AdminSampleMatchingGroupBindRequest(BaseModel):
    productIds: list[str] = Field(min_length=1, max_length=5000)
    folderPath: str = Field(min_length=1, max_length=500)


class AdminSampleMatchingGroupBindResponse(BaseModel):
    ok: bool
    folderPath: str
    boundProductCount: int
    importResult: AdminSampleImportResultResponse


class AdminImportReportResponse(BaseModel):
    importId: str
    sourcePath: str
    importedAt: str
    insertedCount: int
    updatedCount: int
    missingCount: int
    unmatchedCount: int = 0
    missingImageCount: int = 0


class AdminImportReportsResponse(BaseModel):
    reports: list[AdminImportReportResponse] = Field(default_factory=list)


class AdminImageReorderRequest(BaseModel):
    imageIds: list[str] = Field(min_length=1, max_length=50)


class AdminImagesResponse(BaseModel):
    images: list[PublicProductImageResponse] = Field(default_factory=list)


class AdminGalleryAlbumCreateRequest(BaseModel):
    title: str = Field(min_length=1, max_length=120)
    description: str = Field(default="", max_length=500)
    sortOrder: int = Field(default=0, ge=0)
    isVisible: bool = True


class AdminGalleryAlbumPatchRequest(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=500)
    sortOrder: int | None = Field(default=None, ge=0)
    isVisible: bool | None = None


class AdminGalleryImagePatchRequest(BaseModel):
    caption: str | None = Field(default=None, max_length=500)
    sortOrder: int | None = Field(default=None, ge=0)
    isVisible: bool | None = None


class AdminGalleryImageReorderRequest(BaseModel):
    imageIds: list[str] = Field(min_length=1, max_length=100)


class AdminGalleryImageResponse(PublicGalleryImageResponse):
    isVisible: bool
    createdAt: str
    updatedAt: str

    @classmethod
    def from_image(cls, image: ShowcaseGalleryImage) -> "AdminGalleryImageResponse":
        return cls(
            **PublicGalleryImageResponse.from_image(image).model_dump(),
            isVisible=image.is_visible,
            createdAt=image.created_at,
            updatedAt=image.updated_at,
        )


class AdminGalleryAlbumResponse(BaseModel):
    albumId: str
    title: str
    description: str
    sortOrder: int
    isVisible: bool
    createdAt: str
    updatedAt: str
    images: list[AdminGalleryImageResponse] = Field(default_factory=list)


class AdminGalleryAlbumsResponse(BaseModel):
    albums: list[AdminGalleryAlbumResponse] = Field(default_factory=list)


class AdminPurchaseStepCreateRequest(BaseModel):
    title: str = Field(min_length=1, max_length=120)
    description: str = Field(default="", max_length=500)
    sortOrder: int = Field(default=0, ge=0)
    isVisible: bool = True


class AdminPurchaseStepPatchRequest(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=500)
    sortOrder: int | None = Field(default=None, ge=0)
    isVisible: bool | None = None


class AdminPurchaseStepResponse(PublicPurchaseStepResponse):
    isVisible: bool
    createdAt: str
    updatedAt: str

    @classmethod
    def from_step(cls, step: ShowcasePurchaseStep) -> "AdminPurchaseStepResponse":
        return cls(
            **PublicPurchaseStepResponse.from_step(step).model_dump(),
            isVisible=step.is_visible,
            createdAt=step.created_at,
            updatedAt=step.updated_at,
        )


class AdminPurchaseStepsResponse(BaseModel):
    steps: list[AdminPurchaseStepResponse] = Field(default_factory=list)


class AdminSettingsPatchRequest(BaseModel):
    statementText: str | None = Field(default=None, max_length=5000)
    shopIntroText: str | None = Field(default=None, max_length=5000)
    watermarkText: str | None = Field(default=None, max_length=80)
    customerPassword: str | None = Field(default=None, min_length=1, max_length=256)
    inventoryUpdatedAt: str | None = Field(default=None, max_length=80)


class AdminSettingsResponse(BaseModel):
    statementText: str
    shopIntroText: str
    watermarkText: str
    inventoryUpdatedAt: str
    hasCustomerPassword: bool


class AdminPartnerCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    note: str = Field(default="", max_length=1000)
    sortOrder: int = Field(default=0, ge=0)
    active: bool = True


class AdminPartnerPatchRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=160)
    note: str | None = Field(default=None, max_length=1000)
    sortOrder: int | None = Field(default=None, ge=0)
    active: bool | None = None


class AdminPartnerResponse(PublicPartnerResponse):
    sortOrder: int
    active: bool


class AdminSectionCreateRequest(BaseModel):
    title: str = Field(min_length=1, max_length=120)
    subtitle: str = Field(default="", max_length=500)
    active: bool = True
    sortOrder: int = Field(default=0, ge=0)


class AdminSectionPatchRequest(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=120)
    subtitle: str | None = Field(default=None, max_length=500)
    active: bool | None = None
    sortOrder: int | None = Field(default=None, ge=0)


class AdminSectionItemCreateRequest(BaseModel):
    productId: str = Field(min_length=1, max_length=200)
    sortOrder: int = Field(default=0, ge=0)
    recommendNote: str = Field(default="", max_length=500)


class AdminSectionItemPatchRequest(BaseModel):
    sortOrder: int | None = Field(default=None, ge=0)
    recommendNote: str | None = Field(default=None, max_length=500)


class AdminSectionItemResponse(BaseModel):
    itemId: str
    sectionId: str
    productId: str
    sortOrder: int
    recommendNote: str
    product: AdminProductResponse | None = None


class AdminSectionResponse(BaseModel):
    sectionId: str
    title: str
    subtitle: str
    active: bool
    sortOrder: int
    items: list[AdminSectionItemResponse] = Field(default_factory=list)


class AdminSectionsResponse(BaseModel):
    sections: list[AdminSectionResponse] = Field(default_factory=list)


def create_public_router(
    repository: SQLiteShowcaseRepository,
) -> APIRouter:
    router = APIRouter(prefix="/api/public")

    def get_repository() -> SQLiteShowcaseRepository:
        return repository

    def require_customer_access(
        showcase_customer_access: str | None = Cookie(default=None),
        repo: SQLiteShowcaseRepository = Depends(get_repository),
    ) -> None:
        password_hash = repo.get_setting("customer_password_hash")
        if not password_hash:
            return
        if not _has_valid_customer_session(repo, showcase_customer_access):
            raise HTTPException(status_code=401, detail="customer password required") from None

    @router.post("/access", response_model=CustomerAccessResponse)
    def customer_access(
        request: CustomerAccessRequest,
        response: Response,
        repo: SQLiteShowcaseRepository = Depends(get_repository),
    ) -> CustomerAccessResponse:
        password_hash = repo.get_setting("customer_password_hash")
        if not password_hash or not verify_password(request.password, password_hash):
            raise HTTPException(status_code=401, detail="invalid password")
        session_id = secrets.token_urlsafe(32)
        expires_at = datetime.now(timezone.utc) + timedelta(days=7)
        repo.save_customer_session(session_id, expires_at.isoformat())
        response.set_cookie(
            "showcase_customer_access",
            session_id,
            httponly=True,
            samesite="lax",
            max_age=7 * 24 * 60 * 60,
        )
        return CustomerAccessResponse(ok=True)

    @router.get("/access-status", response_model=CustomerAccessStatusResponse)
    def customer_access_status(
        showcase_customer_access: str | None = Cookie(default=None),
        repo: SQLiteShowcaseRepository = Depends(get_repository),
    ) -> CustomerAccessStatusResponse:
        password_hash = repo.get_setting("customer_password_hash")
        return CustomerAccessStatusResponse(
            requiresPassword=bool(password_hash),
            authorized=not password_hash
            or _has_valid_customer_session(repo, showcase_customer_access),
        )

    @router.get(
        "/products",
        response_model=PublicProductsResponse,
        dependencies=[Depends(require_customer_access)],
    )
    def list_public_products(
        query: str = "",
        brand: str = "",
        brands: str = "",
        priceMin: int | None = None,
        priceMax: int | None = None,
        tags: str = "",
        sort: str = "latest",
        limit: int = 80,
        offset: int = 0,
        expectedRevision: str = "",
        repo: SQLiteShowcaseRepository = Depends(get_repository),
    ) -> PublicProductsResponse:
        result = repo.search_products(
            ShowcaseProductSearch(
                query=query.strip(),
                brand=brand.strip(),
                brands=tuple(brand.strip() for brand in brands.split(",") if brand.strip()),
                price_min=priceMin,
                price_max=priceMax,
                tags=tuple(tag.strip() for tag in tags.split(",") if tag.strip()),
                sort=sort.strip() or "latest",
                limit=limit,
                offset=offset,
            )
        )
        sample_cover_paths = _sample_cover_paths_for_products(repo, result.products)
        if offset > 0 and expectedRevision and expectedRevision != result.catalog_revision:
            raise HTTPException(409, "库存已更新，请从第一页重新加载")
        return PublicProductsResponse(
            products=[
                PublicProductResponse.from_product(
                    product,
                    fallback_cover_image_path=sample_cover_paths.get(product.product_id, ""),
                )
                for product in result.products
            ],
            total=result.total,
            limit=result.limit,
            offset=result.offset,
            hasMore=result.has_more,
            catalogRevision=result.catalog_revision,
        )

    @router.get(
        "/filters",
        response_model=PublicFiltersResponse,
        dependencies=[Depends(require_customer_access)],
    )
    def list_public_filters(
        repo: SQLiteShowcaseRepository = Depends(get_repository),
    ) -> PublicFiltersResponse:
        return PublicFiltersResponse(
            brands=repo.list_public_brands(),
            tags=list_sales_tags(),
            pricePresets=[
                PublicPricePresetResponse(label="300以内", priceMin=0, priceMax=300),
                PublicPricePresetResponse(label="500以内", priceMin=0, priceMax=500),
                PublicPricePresetResponse(label="800以内", priceMin=0, priceMax=800),
                PublicPricePresetResponse(label="千元热门", priceMin=800, priceMax=1200),
                PublicPricePresetResponse(label="300-500 推荐", priceMin=300, priceMax=500),
            ],
        )

    @router.get(
        "/products/{product_id}",
        response_model=PublicProductDetailResponse,
        dependencies=[Depends(require_customer_access)],
    )
    def get_public_product(
        product_id: str,
        repo: SQLiteShowcaseRepository = Depends(get_repository),
    ) -> PublicProductDetailResponse:
        product = repo.get_product(product_id)
        if product is None or not product.visible or product.sold:
            raise HTTPException(status_code=404, detail="product not found")
        return PublicProductDetailResponse.from_product_and_images(
            product,
            repo.list_product_images(product_id),
        )

    @router.get("/product-lookup", response_model=PublicProductDetailResponse,
                dependencies=[Depends(require_customer_access)])
    def lookup_public_product(id: str, repo: SQLiteShowcaseRepository = Depends(get_repository)):
        return get_public_product(id, repo)

    @router.get("/settings", response_model=PublicSettingsResponse)
    def get_public_settings(
        repo: SQLiteShowcaseRepository = Depends(get_repository),
    ) -> PublicSettingsResponse:
        return PublicSettingsResponse(
            statementText=repo.get_setting("statement_text")
            or "本库存展示页归星星CCD所有，仅供星星CCD客户查看。",
            shopIntroText=repo.get_setting("shop_intro_text") or "",
            watermarkText=repo.get_setting("watermark_text") or "星星CCD",
            inventoryUpdatedAt=repo.get_setting("inventory_updated_at") or "",
            partners=[
                PublicPartnerResponse(
                    partnerId=partner.partner_id,
                    name=partner.name,
                    note=partner.note,
                )
                for partner in repo.list_authorized_partners(active_only=True)
            ],
        )

    @router.get(
        "/gallery",
        response_model=PublicGalleryResponse,
        dependencies=[Depends(require_customer_access)],
    )
    def list_public_gallery(
        repo: SQLiteShowcaseRepository = Depends(get_repository),
    ) -> PublicGalleryResponse:
        albums: list[PublicGalleryAlbumResponse] = []
        for album in repo.list_gallery_albums(include_hidden=False):
            images = repo.list_gallery_images(album.album_id, include_hidden=False)
            if not images:
                continue
            albums.append(
                PublicGalleryAlbumResponse(
                    albumId=album.album_id,
                    title=album.title,
                    description=album.description,
                    sortOrder=album.sort_order,
                    images=[PublicGalleryImageResponse.from_image(image) for image in images],
                )
            )
        return PublicGalleryResponse(albums=albums)

    @router.get(
        "/purchase-steps",
        response_model=PublicPurchaseStepsResponse,
        dependencies=[Depends(require_customer_access)],
    )
    def list_public_purchase_steps(
        repo: SQLiteShowcaseRepository = Depends(get_repository),
    ) -> PublicPurchaseStepsResponse:
        return PublicPurchaseStepsResponse(
            steps=[
                PublicPurchaseStepResponse.from_step(step)
                for step in repo.list_purchase_steps(include_hidden=False)
            ]
        )

    @router.get(
        "/sections",
        response_model=PublicSectionsResponse,
        dependencies=[Depends(require_customer_access)],
    )
    def list_public_sections(
        repo: SQLiteShowcaseRepository = Depends(get_repository),
    ) -> PublicSectionsResponse:
        section_items = [
            (section, repo.list_section_items(section.section_id))
            for section in repo.list_sections(include_hidden=False)
        ]
        products_by_id = repo.get_products_by_ids([
            item.product_id for _section, items in section_items for item in items
        ])
        section_sample_covers = _sample_cover_paths_for_products(
            repo,
            [product for product in products_by_id.values() if product.visible and not product.sold],
        )
        sections: list[PublicSectionResponse] = []
        for section, items in section_items:
            products = (
                _public_section_products_from_items(
                    repo,
                    items,
                    products_by_id=products_by_id,
                    sample_cover_paths=section_sample_covers,
                )
                if items
                else _public_section_fallback_products(repo, section)
            )
            if not products:
                continue
            sections.append(
                PublicSectionResponse(
                    sectionId=section.section_id,
                    title=section.title,
                    subtitle=section.subtitle,
                    products=products,
                )
            )
        return PublicSectionsResponse(sections=sections)

    return router


def _public_section_products_from_items(
    repo: SQLiteShowcaseRepository,
    items: list[ShowcaseSectionItem],
    *,
    products_by_id: dict[str, ShowcaseProduct] | None = None,
    sample_cover_paths: dict[str, str] | None = None,
) -> list[PublicSectionProductResponse]:
    product_notes: list[tuple[ShowcaseProduct, str]] = []
    for item in items:
        product = (
            products_by_id.get(item.product_id)
            if products_by_id is not None
            else repo.get_product(item.product_id)
        )
        if product is None or not product.visible or product.sold:
            continue
        product_notes.append((product, item.recommend_note))
    if sample_cover_paths is None:
        sample_cover_paths = _sample_cover_paths_for_products(
            repo,
            [product for product, _recommend_note in product_notes],
        )
    return [
        _public_section_product_response(
            product,
            sample_cover_paths,
            recommend_note=recommend_note,
        )
        for product, recommend_note in product_notes
    ]


def _public_section_fallback_products(
    repo: SQLiteShowcaseRepository,
    section: ShowcaseSection,
) -> list[PublicSectionProductResponse]:
    search = _fallback_search_for_section(section)
    if search is None:
        return []
    result = repo.search_products(search)
    sample_cover_paths = _sample_cover_paths_for_products(repo, result.products)
    return [
        _public_section_product_response(
            product,
            sample_cover_paths,
            recommend_note="",
        )
        for product in result.products
    ]


def _fallback_search_for_section(section: ShowcaseSection) -> ShowcaseProductSearch | None:
    section_key = section.section_id.lower()
    title = section.title
    if "budget-300-500" in section_key or "300-500" in title:
        return ShowcaseProductSearch(price_min=300, price_max=500, limit=6)
    if "beginner" in section_key or "新手" in title:
        return ShowcaseProductSearch(tags=("新手推荐",), limit=6)
    if "gift" in section_key or "礼盒" in title:
        return ShowcaseProductSearch(tags=("礼盒装",), limit=6)
    if "new" in section_key or "上新" in title:
        return ShowcaseProductSearch(limit=6)
    if "today" in section_key or "主推" in title or "推荐" in title:
        return ShowcaseProductSearch(limit=6)
    return None


def _sample_cover_paths_for_products(
    repo: SQLiteShowcaseRepository,
    products: list[ShowcaseProduct],
) -> dict[str, str]:
    return repo.list_first_image_paths_by_type_for_products(
        "sample",
        [product.product_id for product in products],
    )


def _public_section_product_response(
    product: ShowcaseProduct,
    sample_cover_paths: dict[str, str],
    *,
    recommend_note: str,
) -> PublicSectionProductResponse:
    base = PublicProductResponse.from_product(
        product,
        fallback_cover_image_path=sample_cover_paths.get(product.product_id, ""),
    )
    return PublicSectionProductResponse(
        **base.model_dump(),
        recommendNote=recommend_note,
    )


def create_admin_router(
    repository: SQLiteShowcaseRepository,
    *,
    storage_dir: str | Path = "storage/showcase_images",
    sample_images_dir: str | Path = "output/ccdcpt",
) -> APIRouter:
    router = APIRouter(prefix="/api/admin")
    storage_path = Path(storage_dir)
    sample_images_path = Path(sample_images_dir)

    def get_repository() -> SQLiteShowcaseRepository:
        return repository

    def require_admin(
        showcase_admin_session: str | None = Cookie(default=None),
        repo: SQLiteShowcaseRepository = Depends(get_repository),
    ) -> None:
        if not showcase_admin_session:
            raise HTTPException(status_code=401, detail="admin login required")
        expires_at_raw = repo.get_admin_session_expires_at(showcase_admin_session)
        if not expires_at_raw:
            raise HTTPException(status_code=401, detail="admin login required")
        try:
            expires_at = datetime.fromisoformat(expires_at_raw)
        except ValueError:
            raise HTTPException(status_code=401, detail="admin login required") from None
        if expires_at <= datetime.now(timezone.utc):
            raise HTTPException(status_code=401, detail="admin login required")

    @router.post("/login", response_model=AdminLoginResponse)
    def admin_login(
        request: AdminLoginRequest,
        response: Response,
        repo: SQLiteShowcaseRepository = Depends(get_repository),
    ) -> AdminLoginResponse:
        password_hash = repo.get_setting("admin_password_hash")
        if not password_hash or not verify_password(request.password, password_hash):
            raise HTTPException(status_code=401, detail="invalid password")
        session_id = secrets.token_urlsafe(32)
        expires_at = datetime.now(timezone.utc) + timedelta(hours=12)
        repo.save_admin_session(session_id, expires_at.isoformat())
        response.set_cookie(
            "showcase_admin_session",
            session_id,
            httponly=True,
            samesite="lax",
            max_age=12 * 60 * 60,
        )
        return AdminLoginResponse(ok=True)

    @router.get(
        "/products",
        response_model=AdminProductsResponse,
        dependencies=[Depends(require_admin)],
    )
    def list_admin_products(
        query: str = "",
        model: str = "",
        brand: str = "",
        brands: str = "",
        priceMin: int | None = None,
        priceMax: int | None = None,
        visible: bool | None = None,
        sold: bool | None = None,
        hasBodyImage: bool | None = None,
        hasSampleImage: bool | None = None,
        manualPrice: bool | None = None,
        tags: str = "",
        sectionId: str = "",
        updatedAfter: str = "",
        importId: str = "",
        reviewState: str = "",
        limit: int = 80,
        offset: int = 0,
        repo: SQLiteShowcaseRepository = Depends(get_repository),
    ) -> AdminProductsResponse:
        search = ShowcaseAdminProductSearch(
            query=query.strip(),
            model=model.strip(),
            brands=_split_query_values(brands, extra=brand),
            price_min=priceMin,
            price_max=priceMax,
            visible=visible,
            sold=sold,
            has_body_image=hasBodyImage,
            has_sample_image=hasSampleImage,
            manual_price=manualPrice,
            tags=_split_query_values(tags),
            section_id=sectionId.strip(),
            updated_after=updatedAfter.strip(),
            review_state=reviewState.strip(),
            import_id=importId.strip(),
            limit=limit,
            offset=offset,
        )
        result = repo.search_admin_products(search)
        return AdminProductsResponse(
            products=[AdminProductResponse.from_summary(product) for product in result.products],
            total=result.total,
            limit=result.limit,
            offset=result.offset,
            hasMore=result.has_more,
        )

    @router.post(
        "/products/bulk-preview",
        response_model=AdminBulkPreviewResponse,
        dependencies=[Depends(require_admin)],
    )
    def preview_admin_bulk_operation(
        request: AdminBulkOperationRequest,
        showcase_admin_session: str = Cookie(default=""),
        repo: SQLiteShowcaseRepository = Depends(get_repository),
    ) -> AdminBulkPreviewResponse:
        preview = _bulk_preview_response(repo, request)
        request_snapshot = request.model_dump()
        request_snapshot["operationSummary"] = _bulk_operation_summary(
            request, preview.changedCount,
        )
        request_snapshot["filterText"] = _bulk_filter_text(request)
        preview_id, expires = bulk_service.save_preview(
            repo, showcase_admin_session, request_snapshot,
            [item.model_dump() for item in preview.items],
        )
        displayed_items = preview.items[:200]
        return preview.model_copy(update={
            "previewId": preview_id,
            "expiresAt": expires,
            "displayedCount": len(displayed_items),
            "truncated": len(displayed_items) < preview.total,
            "items": displayed_items,
        })

    @router.get(
        "/products/bulk-preview/{preview_id}/export",
        dependencies=[Depends(require_admin)],
    )
    def export_admin_bulk_preview(
        preview_id: str,
        showcase_admin_session: str = Cookie(default=""),
        repo: SQLiteShowcaseRepository = Depends(get_repository),
    ) -> StreamingResponse:
        items = bulk_service.load_preview_items(
            repo, showcase_admin_session, preview_id,
        )

        def iter_csv_rows():
            writer = csv.writer(_CsvLineSink(), lineterminator="\n")
            yield "\ufeff"
            yield writer.writerow([
                "商品ID", "型号", "品牌", "导入原价", "当前展示价", "新展示价",
                "变化金额", "是否修改", "跳过原因", "展示状态", "已售状态",
            ])
            for item in items:
                yield writer.writerow([
                    _safe_csv_text(item["productId"]),
                    _safe_csv_text(item["model"]),
                    _safe_csv_text(item["brand"]),
                    item["sourcePrice"],
                    item["oldPrice"],
                    item["newPrice"],
                    item["delta"],
                    "是" if item["changed"] else "否",
                    _safe_csv_text(item["skippedReason"]),
                    "展示" if item["oldVisible"] else "隐藏",
                    "已售" if item["sold"] else "未售",
                ])

        return StreamingResponse(
            iter_csv_rows(),
            media_type="text/csv; charset=utf-8",
            headers={
                "Content-Disposition": (
                    f'attachment; filename="ccd-bulk-preview-{preview_id}.csv"'
                ),
                "Cache-Control": "no-store",
                "X-Content-Type-Options": "nosniff",
            },
        )

    @router.post(
        "/products/bulk-apply",
        response_model=AdminBulkApplyResponse,
        dependencies=[Depends(require_admin)],
    )
    def apply_admin_bulk_operation(
        request: AdminBulkApplyRequest,
        showcase_admin_session: str = Cookie(default=""),
        repo: SQLiteShowcaseRepository = Depends(get_repository),
    ) -> AdminBulkApplyResponse:
        return AdminBulkApplyResponse(**bulk_service.execute(
            repo, showcase_admin_session, request.idempotencyKey, request.previewId))

    @router.get(
        "/operations",
        response_model=AdminOperationsResponse,
        dependencies=[Depends(require_admin)],
    )
    def list_admin_operations(
        repo: SQLiteShowcaseRepository = Depends(get_repository),
    ) -> AdminOperationsResponse:
        return AdminOperationsResponse(
            operations=[
                AdminOperationResponse(
                    operationId=operation.operation_id,
                    operationType=operation.operation_type,
                    summary=operation.summary,
                    filterText=operation.filter_text,
                    updatedCount=operation.updated_count,
                    createdAt=operation.created_at,
                    undoneAt=operation.undone_at,
                )
                for operation in repo.list_admin_operations()
            ]
        )

    @router.post(
        "/operations/{operation_id}/undo",
        response_model=AdminBulkApplyResponse,
        dependencies=[Depends(require_admin)],
    )
    def undo_admin_operation(
        operation_id: str,
        request: AdminUndoRequest,
        showcase_admin_session: str = Cookie(default=""),
        repo: SQLiteShowcaseRepository = Depends(get_repository),
    ) -> AdminBulkApplyResponse:
        return AdminBulkApplyResponse(**bulk_service.execute(
            repo, showcase_admin_session, request.idempotencyKey, operation_id, undo=True))

    @router.get(
        "/diagnostics",
        response_model=AdminDiagnosticsResponse,
        dependencies=[Depends(require_admin)],
    )
    def get_admin_diagnostics(
        repo: SQLiteShowcaseRepository = Depends(get_repository),
    ) -> AdminDiagnosticsResponse:
        summaries = repo.list_admin_products_for_bulk(ShowcaseAdminProductSearch(limit=100000))
        duplicate_models = _duplicate_model_counts(summaries)
        counts = {
            "priceZero": 0,
            "genericBrand": 0,
            "missingBodyImage": 0,
            "missingSampleImage": 0,
            "missingCopy": 0,
            "duplicateModel": 0,
        }
        abnormal: list[ShowcaseAdminProductSummary] = []
        for summary in summaries:
            product = summary.product
            problems = False
            if product.display_price == 0:
                counts["priceZero"] += 1
                problems = True
            if product.brand == "通用":
                counts["genericBrand"] += 1
                problems = True
            if not summary.has_body_image:
                counts["missingBodyImage"] += 1
                problems = True
            if not summary.has_sample_image:
                counts["missingSampleImage"] += 1
                problems = True
            if not (product.display_copy or product.raw_copy).strip():
                counts["missingCopy"] += 1
                problems = True
            if duplicate_models.get(product.model, 0) > 1:
                counts["duplicateModel"] += 1
                problems = True
            if problems:
                abnormal.append(summary)
        return AdminDiagnosticsResponse(
            counts=counts,
            abnormalProducts=[AdminProductResponse.from_summary(item) for item in abnormal[:200]],
        )

    @router.post(
        "/backups",
        response_model=AdminBackupResponse,
        dependencies=[Depends(require_admin)],
    )
    def create_admin_backup(
        repo: SQLiteShowcaseRepository = Depends(get_repository),
    ) -> AdminBackupResponse:
        raise HTTPException(
            status_code=410,
            detail="网页内仅备份数据库会遗漏图片；请运行 backup_showcase_db.bat 创建一致快照",
        )

    @router.get(
        "/sample-matching/summary",
        response_model=AdminSampleMatchingSummaryResponse,
        dependencies=[Depends(require_admin)],
    )
    def get_admin_sample_matching_summary(
        repo: SQLiteShowcaseRepository = Depends(get_repository),
    ) -> AdminSampleMatchingSummaryResponse:
        return _sample_matching_summary_response(
            build_sample_matching_summary(sample_images_path, repo)
        )

    @router.get(
        "/sample-matching/products",
        response_model=AdminSampleMatchingProductsResponse,
        dependencies=[Depends(require_admin)],
    )
    def list_admin_sample_matching_products(
        status: str = "needs_attention",
        limit: int = 100,
        repo: SQLiteShowcaseRepository = Depends(get_repository),
    ) -> AdminSampleMatchingProductsResponse:
        allowed_statuses = {"all", "needs_attention", "matched", "missing", "low_confidence", "auto_matched"}
        normalized_status = status if status in allowed_statuses else "needs_attention"
        normalized_limit = min(max(limit, 1), 500)
        return AdminSampleMatchingProductsResponse(
            products=[
                AdminSampleMatchingProductResponse.from_item(item)
                for item in list_sample_matching_products(
                    sample_images_path,
                    repo,
                    status=normalized_status,
                    limit=normalized_limit,
                )
            ]
        )

    @router.get(
        "/sample-matching/groups",
        response_model=AdminSampleMatchingGroupsResponse,
        dependencies=[Depends(require_admin)],
    )
    def list_admin_sample_matching_groups(
        limit: int = 100,
        repo: SQLiteShowcaseRepository = Depends(get_repository),
    ) -> AdminSampleMatchingGroupsResponse:
        normalized_limit = min(max(limit, 1), 500)
        return AdminSampleMatchingGroupsResponse(
            groups=[
                AdminSampleMatchingGroupResponse.from_group(group)
                for group in list_sample_matching_groups(
                    sample_images_path,
                    repo,
                    limit=normalized_limit,
                )
            ]
        )

    @router.get(
        "/sample-matching/assets",
        response_model=AdminSampleMatchingAssetsResponse,
        dependencies=[Depends(require_admin)],
    )
    def list_admin_sample_matching_assets(
        query: str = "",
        limit: int = 50,
    ) -> AdminSampleMatchingAssetsResponse:
        normalized_query = query.casefold().strip()
        normalized_limit = min(max(limit, 1), 200)
        assets = list_sample_image_assets(sample_images_path)
        if normalized_query:
            assets = [
                asset
                for asset in assets
                if normalized_query in asset.folder_path.casefold()
                or normalized_query in asset.model_folder.casefold()
                or normalized_query in asset.model_key.casefold()
                or normalized_query in asset.brand.casefold()
            ]
        return AdminSampleMatchingAssetsResponse(
            assets=[
                AdminSampleMatchingAssetResponse.from_asset(asset)
                for asset in assets[:normalized_limit]
            ]
        )

    @router.post(
        "/sample-matching/rebuild",
        response_model=AdminSampleMatchingRebuildResponse,
        dependencies=[Depends(require_admin)],
    )
    def rebuild_admin_sample_matching(
        repo: SQLiteShowcaseRepository = Depends(get_repository),
    ) -> AdminSampleMatchingRebuildResponse:
        result = _import_sample_images_or_400(sample_images_path, repo)
        return AdminSampleMatchingRebuildResponse(
            ok=True,
            summary=_sample_matching_summary_response(
                build_sample_matching_summary(sample_images_path, repo)
            ),
            importResult=AdminSampleImportResultResponse.from_result(result),
        )

    @router.post(
        "/sample-matching/bind",
        response_model=AdminSampleBindingResponse,
        dependencies=[Depends(require_admin)],
    )
    def bind_admin_sample_matching_product(
        request: AdminSampleMatchingBindRequest,
        repo: SQLiteShowcaseRepository = Depends(get_repository),
    ) -> AdminSampleBindingResponse:
        product = repo.get_product(request.productId)
        if product is None:
            raise HTTPException(status_code=404, detail="product not found")
        folder_path = request.folderPath.strip().replace("\\", "/").strip("/")
        _ensure_sample_folder_exists(sample_images_path, folder_path)
        now = datetime.now(timezone.utc).isoformat()
        binding_key = f"product:{product.product_id}"
        repo.save_sample_folder_binding(
            binding_key=binding_key,
            product_id=product.product_id,
            model_key=product.model,
            brand=product.brand,
            folder_path=folder_path,
            created_at=now,
            updated_at=now,
        )
        result = _import_sample_images_or_400(sample_images_path, repo, product_ids=[product.product_id])
        return AdminSampleBindingResponse(
            ok=True,
            bindingKey=binding_key,
            folderPath=folder_path,
            importResult=AdminSampleImportResultResponse.from_result(result),
        )

    @router.post(
        "/sample-matching/groups/bind",
        response_model=AdminSampleMatchingGroupBindResponse,
        dependencies=[Depends(require_admin)],
    )
    def bind_admin_sample_matching_group(
        request: AdminSampleMatchingGroupBindRequest,
        repo: SQLiteShowcaseRepository = Depends(get_repository),
    ) -> AdminSampleMatchingGroupBindResponse:
        folder_path = request.folderPath.strip().replace("\\", "/").strip("/")
        _ensure_sample_folder_exists(sample_images_path, folder_path)
        now = datetime.now(timezone.utc).isoformat()
        bound_product_count = 0
        target_ids = []
        for product_id in dict.fromkeys(item.strip() for item in request.productIds if item.strip()):
            product = repo.get_product(product_id)
            if product is None:
                continue
            repo.save_sample_folder_binding(
                binding_key=f"product:{product.product_id}",
                product_id=product.product_id,
                model_key=product.model,
                brand=product.brand,
                folder_path=folder_path,
                created_at=now,
                updated_at=now,
            )
            bound_product_count += 1
            target_ids.append(product.product_id)
        result = _import_sample_images_or_400(sample_images_path, repo, product_ids=target_ids)
        return AdminSampleMatchingGroupBindResponse(
            ok=True,
            folderPath=folder_path,
            boundProductCount=bound_product_count,
            importResult=AdminSampleImportResultResponse.from_result(result),
        )

    @router.post(
        "/sample-bindings",
        response_model=AdminSampleBindingResponse,
        dependencies=[Depends(require_admin)],
    )
    def create_admin_sample_binding(
        request: AdminSampleBindingRequest,
        repo: SQLiteShowcaseRepository = Depends(get_repository),
    ) -> AdminSampleBindingResponse:
        _ensure_sample_folder_exists(sample_images_path, request.folderPath)
        target_ids = None
        if request.productId:
            product = repo.get_product(request.productId)
            if product is None:
                raise HTTPException(404, "product not found")
            request = request.model_copy(update={"productId": product.product_id})
            target_ids = [product.product_id]
            binding_key = f"product:{product.product_id}"
        else:
            brand = request.brand.strip()
            model_key = request.modelKey.strip()
            if not brand or not model_key:
                raise HTTPException(status_code=400, detail="brand and modelKey required")
            binding_key = f"model:{brand}:{model_key}"
            target_ids = [p.product_id for p in repo.list_products(include_hidden=True)
                          if p.brand == brand and p.model == model_key]
        now = datetime.now(timezone.utc).isoformat()
        repo.save_sample_folder_binding(
            binding_key=binding_key,
            product_id=request.productId.strip(),
            model_key=request.modelKey.strip(),
            brand=request.brand.strip(),
            folder_path=request.folderPath.strip().replace("\\", "/"),
            created_at=now,
            updated_at=now,
        )
        result = _import_sample_images_or_400(sample_images_path, repo, product_ids=target_ids)
        return AdminSampleBindingResponse(
            ok=True,
            bindingKey=binding_key,
            folderPath=request.folderPath.strip().replace("\\", "/"),
            importResult=AdminSampleImportResultResponse.from_result(result),
        )

    @router.get(
        "/import-reports",
        response_model=AdminImportReportsResponse,
        dependencies=[Depends(require_admin)],
    )
    def list_admin_import_reports(
        repo: SQLiteShowcaseRepository = Depends(get_repository),
    ) -> AdminImportReportsResponse:
        return AdminImportReportsResponse(
            reports=[
                AdminImportReportResponse(
                    importId=str(report["import_id"]),
                    sourcePath=str(report["source_path"]),
                    importedAt=str(report["imported_at"]),
                    insertedCount=int(report["inserted_count"]),
                    updatedCount=int(report["updated_count"]),
                    missingCount=int(report["missing_count"]),
                    unmatchedCount=int(report["unmatched_count"]),
                    missingImageCount=int(report["missing_image_count"]),
                )
                for report in repo.list_import_logs()
            ]
        )

    @router.post(
        "/products",
        response_model=AdminProductResponse,
        status_code=201,
        dependencies=[Depends(require_admin)],
    )
    def create_admin_product(
        request: AdminProductCreateRequest,
        repo: SQLiteShowcaseRepository = Depends(get_repository),
    ) -> AdminProductResponse:
        if repo.get_product(request.productId) is not None:
            raise HTTPException(status_code=409, detail="product already exists")
        section_ids = list(dict.fromkeys(section_id.strip() for section_id in request.sectionIds if section_id.strip()))
        for section_id in section_ids:
            if repo.get_section(section_id) is None:
                raise HTTPException(status_code=404, detail="section not found")
        now = datetime.now(timezone.utc).isoformat()
        product = ShowcaseProduct(
            product_id=request.productId,
            model=request.model,
            brand=request.brand,
            cost_price=0,
            display_price=request.displayPrice,
            visible=request.visible,
            sold=False,
            published_at=now,
            raw_copy=request.displayCopy,
            display_copy=request.displayCopy,
            cover_image_path="",
            created_at=now,
            updated_at=now,
            last_seen_import_id="manual",
            short_selling_point=request.shortSellingPoint,
            recommend_tags=_join_tags(request.recommendTags),
            source_scope="manual",
            source_available=True,
            source_display_price=request.displayPrice,
            source_display_copy=request.displayCopy,
            source_visible=request.visible,
            last_seen_at=now,
            review_state="manual",
            last_verified_at=now,
        )
        repo.upsert_product(product)
        for section_id in section_ids:
            repo.upsert_section_item(
                ShowcaseSectionItem(
                    item_id=uuid.uuid4().hex,
                    section_id=section_id,
                    product_id=product.product_id,
                    sort_order=request.sectionSortOrder,
                    recommend_note=request.sectionRecommendNote,
                    created_at=now,
                    updated_at=now,
                )
            )
        return AdminProductResponse.from_product(product)

    @router.patch(
        "/products/{product_id}",
        response_model=AdminProductResponse,
        dependencies=[Depends(require_admin)],
    )
    def update_admin_product(
        product_id: str,
        request: AdminProductPatchRequest,
        repo: SQLiteShowcaseRepository = Depends(get_repository),
    ) -> AdminProductResponse:
        with repo._lock:
            product = repo.get_product(product_id)
            if product is None:
                raise HTTPException(status_code=404, detail="product not found")
            if request.expectedVersion is not None and product.row_version != request.expectedVersion:
                raise HTTPException(409, "商品已被修改，请刷新后重新保存")
            if request.visible is True and product.sold and request.sold is not False:
                raise HTTPException(409, "已售商品必须先明确恢复为在售")
            invalid = set(request.resetOverrides) - {"price", "copy", "visibility"}
            if invalid:
                raise HTTPException(422, "无效的覆盖字段")
            updated = replace(
                product,
                model=request.model if request.model is not None else product.model,
                brand=request.brand if request.brand is not None else product.brand,
                display_price=(
                    request.displayPrice
                    if request.displayPrice is not None
                    else product.display_price
                ),
                display_copy=(
                    request.displayCopy
                    if request.displayCopy is not None
                    else product.display_copy
                ),
                short_selling_point=(
                    request.shortSellingPoint
                    if request.shortSellingPoint is not None
                    else product.short_selling_point
                ),
                recommend_tags=(
                    _join_tags(request.recommendTags)
                    if request.recommendTags is not None
                    else product.recommend_tags
                ),
                visible=request.visible if request.visible is not None else product.visible,
                sold=request.sold if request.sold is not None else product.sold,
                updated_at=datetime.now(timezone.utc).isoformat(),
            )
            overrides = {}
            for field, value, override, source in (
                ("price", request.displayPrice, "price_override", "source_display_price"),
                ("copy", request.displayCopy, "copy_override", "source_display_copy"),
                ("visibility", request.visible, "visibility_override", "source_visible"),
            ):
                if field in request.resetOverrides:
                    overrides[override] = None
                    effective = {"price": "display_price", "copy": "display_copy", "visibility": "visible"}[field]
                    overrides[effective] = getattr(product, source)
                elif value is not None:
                    overrides[override] = value
            if overrides:
                updated = replace(updated, **overrides)
                updated = replace(
                    updated,
                    override_origin=(
                        "manual"
                        if any(
                            value is not None
                            for value in (
                                updated.price_override,
                                updated.copy_override,
                                updated.visibility_override,
                            )
                        )
                        else ""
                    ),
                )
            repo.upsert_product(updated)
            summary = repo.get_admin_product_summary(product.product_id)
            if summary is None:
                raise HTTPException(status_code=404, detail="product not found")
            return AdminProductResponse.from_summary(summary)

    @router.delete(
        "/products/{product_id}",
        response_model=AdminLoginResponse,
        dependencies=[Depends(require_admin)],
    )
    def delete_admin_product(
        product_id: str,
        repo: SQLiteShowcaseRepository = Depends(get_repository),
    ) -> AdminLoginResponse:
        if not repo.delete_product(product_id):
            raise HTTPException(status_code=404, detail="product not found")
        return AdminLoginResponse(ok=True)

    @router.post(
        "/products/batch-price",
        response_model=AdminBatchPriceResponse,
        dependencies=[Depends(require_admin)],
    )
    def batch_update_admin_product_prices(
        request: AdminBatchPriceRequest,
        repo: SQLiteShowcaseRepository = Depends(get_repository),
    ) -> AdminBatchPriceResponse:
        raise HTTPException(410, "请使用批量预览和确认接口，旧批量入口已停用")

    @router.get(
        "/products/{product_id}/images",
        response_model=AdminImagesResponse,
        dependencies=[Depends(require_admin)],
    )
    def list_admin_product_images(
        product_id: str,
        repo: SQLiteShowcaseRepository = Depends(get_repository),
    ) -> AdminImagesResponse:
        if repo.get_product(product_id) is None:
            raise HTTPException(status_code=404, detail="product not found")
        return AdminImagesResponse(
            images=[
                PublicProductImageResponse.from_image(image)
                for image in repo.list_product_images(product_id)
            ]
        )

    @router.post(
        "/products/{product_id}/images",
        response_model=PublicProductImageResponse,
        status_code=201,
        dependencies=[Depends(require_admin)],
    )
    async def upload_admin_product_image(
        product_id: str,
        imageType: str = Form(default="detail"),
        file: UploadFile = File(...),
        repo: SQLiteShowcaseRepository = Depends(get_repository),
    ) -> PublicProductImageResponse:
        product = repo.get_product(product_id)
        if product is None:
            raise HTTPException(status_code=404, detail="product not found")
        if imageType not in {"body", "detail", "sample"}:
            raise HTTPException(422, "无效图片分类")
        image_id = uuid.uuid4().hex
        product_dir = storage_path / product.public_id
        temporary, suffix = await _validated_image_upload(file, product_dir)
        destination = product_dir / f"{image_id}{suffix}"
        os.replace(temporary, destination)
        image_path = f"storage/showcase_images/{product.public_id}/{destination.name}"
        sort_order = max((image.sort_order for image in repo.list_product_images(product_id)), default=-1) + 1
        is_cover = not product.cover_image_path and imageType != "sample"
        try:
            repo.add_product_image(
                image_id,
                product_id,
                image_path,
                imageType,
                sort_order,
                is_cover,
            )
            if is_cover:
                repo.set_product_cover_image(product_id, image_id)
        except Exception:
            destination.unlink(missing_ok=True)
            # add 成功、设封面失败时也回收数据库记录。
            repo.delete_product_image(product_id, image_id)
            raise
        image = repo.get_product_image(image_id)
        return PublicProductImageResponse.from_image(image)

    @router.post(
        "/products/{product_id}/images/reorder",
        response_model=AdminLoginResponse,
        dependencies=[Depends(require_admin)],
    )
    def reorder_admin_product_images(
        product_id: str,
        request: AdminImageReorderRequest,
        repo: SQLiteShowcaseRepository = Depends(get_repository),
    ) -> AdminLoginResponse:
        if repo.get_product(product_id) is None:
            raise HTTPException(status_code=404, detail="product not found")
        repo.reorder_product_images(product_id, request.imageIds)
        return AdminLoginResponse(ok=True)

    @router.post(
        "/products/{product_id}/images/{image_id}/cover",
        response_model=AdminLoginResponse,
        dependencies=[Depends(require_admin)],
    )
    def set_admin_product_cover_image(
        product_id: str,
        image_id: str,
        repo: SQLiteShowcaseRepository = Depends(get_repository),
    ) -> AdminLoginResponse:
        if not repo.set_product_cover_image(product_id, image_id):
            raise HTTPException(status_code=404, detail="image not found")
        return AdminLoginResponse(ok=True)

    @router.delete(
        "/products/{product_id}/images/{image_id}",
        response_model=AdminLoginResponse,
        dependencies=[Depends(require_admin)],
    )
    def delete_admin_product_image(
        product_id: str,
        image_id: str,
        repo: SQLiteShowcaseRepository = Depends(get_repository),
    ) -> AdminLoginResponse:
        if not repo.delete_product_image(product_id, image_id):
            raise HTTPException(status_code=404, detail="image not found")
        return AdminLoginResponse(ok=True)

    @router.get(
        "/purchase-steps",
        response_model=AdminPurchaseStepsResponse,
        dependencies=[Depends(require_admin)],
    )
    def list_admin_purchase_steps(
        repo: SQLiteShowcaseRepository = Depends(get_repository),
    ) -> AdminPurchaseStepsResponse:
        return AdminPurchaseStepsResponse(
            steps=[
                AdminPurchaseStepResponse.from_step(step)
                for step in repo.list_purchase_steps(include_hidden=True)
            ]
        )

    @router.post(
        "/purchase-steps",
        response_model=AdminPurchaseStepResponse,
        status_code=201,
        dependencies=[Depends(require_admin)],
    )
    def create_admin_purchase_step(
        request: AdminPurchaseStepCreateRequest,
        repo: SQLiteShowcaseRepository = Depends(get_repository),
    ) -> AdminPurchaseStepResponse:
        now = datetime.now(timezone.utc).isoformat()
        step = ShowcasePurchaseStep(
            step_id=uuid.uuid4().hex,
            title=request.title,
            description=request.description,
            sort_order=request.sortOrder,
            is_visible=request.isVisible,
            created_at=now,
            updated_at=now,
        )
        repo.upsert_purchase_step(step)
        return AdminPurchaseStepResponse.from_step(step)

    @router.patch(
        "/purchase-steps/{step_id}",
        response_model=AdminPurchaseStepResponse,
        dependencies=[Depends(require_admin)],
    )
    def update_admin_purchase_step(
        step_id: str,
        request: AdminPurchaseStepPatchRequest,
        repo: SQLiteShowcaseRepository = Depends(get_repository),
    ) -> AdminPurchaseStepResponse:
        step = repo.get_purchase_step(step_id)
        if step is None:
            raise HTTPException(status_code=404, detail="purchase step not found")
        updated = ShowcasePurchaseStep(
            step_id=step.step_id,
            title=request.title if request.title is not None else step.title,
            description=(
                request.description
                if request.description is not None
                else step.description
            ),
            sort_order=request.sortOrder if request.sortOrder is not None else step.sort_order,
            is_visible=request.isVisible if request.isVisible is not None else step.is_visible,
            created_at=step.created_at,
            updated_at=datetime.now(timezone.utc).isoformat(),
        )
        repo.upsert_purchase_step(updated)
        return AdminPurchaseStepResponse.from_step(updated)

    @router.delete(
        "/purchase-steps/{step_id}",
        response_model=AdminLoginResponse,
        dependencies=[Depends(require_admin)],
    )
    def delete_admin_purchase_step(
        step_id: str,
        repo: SQLiteShowcaseRepository = Depends(get_repository),
    ) -> AdminLoginResponse:
        if not repo.delete_purchase_step(step_id):
            raise HTTPException(status_code=404, detail="purchase step not found")
        return AdminLoginResponse(ok=True)

    @router.get(
        "/gallery/albums",
        response_model=AdminGalleryAlbumsResponse,
        dependencies=[Depends(require_admin)],
    )
    def list_admin_gallery_albums(
        repo: SQLiteShowcaseRepository = Depends(get_repository),
    ) -> AdminGalleryAlbumsResponse:
        return AdminGalleryAlbumsResponse(
            albums=[
                _admin_gallery_album_response(repo, album)
                for album in repo.list_gallery_albums(include_hidden=True)
            ]
        )

    @router.post(
        "/gallery/albums",
        response_model=AdminGalleryAlbumResponse,
        status_code=201,
        dependencies=[Depends(require_admin)],
    )
    def create_admin_gallery_album(
        request: AdminGalleryAlbumCreateRequest,
        repo: SQLiteShowcaseRepository = Depends(get_repository),
    ) -> AdminGalleryAlbumResponse:
        now = datetime.now(timezone.utc).isoformat()
        album = ShowcaseGalleryAlbum(
            album_id=uuid.uuid4().hex,
            title=request.title,
            description=request.description,
            sort_order=request.sortOrder,
            is_visible=request.isVisible,
            created_at=now,
            updated_at=now,
        )
        repo.upsert_gallery_album(album)
        return _admin_gallery_album_response(repo, album)

    @router.patch(
        "/gallery/albums/{album_id}",
        response_model=AdminGalleryAlbumResponse,
        dependencies=[Depends(require_admin)],
    )
    def update_admin_gallery_album(
        album_id: str,
        request: AdminGalleryAlbumPatchRequest,
        repo: SQLiteShowcaseRepository = Depends(get_repository),
    ) -> AdminGalleryAlbumResponse:
        album = repo.get_gallery_album(album_id)
        if album is None:
            raise HTTPException(status_code=404, detail="gallery album not found")
        updated = ShowcaseGalleryAlbum(
            album_id=album.album_id,
            title=request.title if request.title is not None else album.title,
            description=(
                request.description
                if request.description is not None
                else album.description
            ),
            sort_order=request.sortOrder if request.sortOrder is not None else album.sort_order,
            is_visible=request.isVisible if request.isVisible is not None else album.is_visible,
            created_at=album.created_at,
            updated_at=datetime.now(timezone.utc).isoformat(),
        )
        repo.upsert_gallery_album(updated)
        return _admin_gallery_album_response(repo, updated)

    @router.delete(
        "/gallery/albums/{album_id}",
        response_model=AdminLoginResponse,
        dependencies=[Depends(require_admin)],
    )
    def delete_admin_gallery_album(
        album_id: str,
        repo: SQLiteShowcaseRepository = Depends(get_repository),
    ) -> AdminLoginResponse:
        if not repo.delete_gallery_album(album_id):
            raise HTTPException(status_code=404, detail="gallery album not found")
        return AdminLoginResponse(ok=True)

    @router.post(
        "/gallery/albums/{album_id}/images",
        response_model=AdminGalleryImageResponse,
        status_code=201,
        dependencies=[Depends(require_admin)],
    )
    async def upload_admin_gallery_image(
        album_id: str,
        caption: str = Form(default=""),
        isVisible: bool = Form(default=True),
        file: UploadFile = File(...),
        repo: SQLiteShowcaseRepository = Depends(get_repository),
    ) -> AdminGalleryImageResponse:
        if repo.get_gallery_album(album_id) is None:
            raise HTTPException(status_code=404, detail="gallery album not found")
        image_id = uuid.uuid4().hex
        album_dir = storage_path / "gallery" / album_id
        temporary, suffix = await _validated_image_upload(file, album_dir)
        destination = album_dir / f"{image_id}{suffix}"
        os.replace(temporary, destination)
        now = datetime.now(timezone.utc).isoformat()
        image = ShowcaseGalleryImage(
            image_id=image_id,
            album_id=album_id,
            image_path=f"storage/showcase_images/gallery/{album_id}/{destination.name}",
            caption=caption.strip(),
            sort_order=len(repo.list_gallery_images(album_id, include_hidden=True)),
            is_visible=isVisible,
            created_at=now,
            updated_at=now,
        )
        try:
            repo.add_gallery_image(image)
        except Exception:
            destination.unlink(missing_ok=True)
            raise
        return AdminGalleryImageResponse.from_image(image)

    @router.patch(
        "/gallery/images/{image_id}",
        response_model=AdminGalleryImageResponse,
        dependencies=[Depends(require_admin)],
    )
    def update_admin_gallery_image(
        image_id: str,
        request: AdminGalleryImagePatchRequest,
        repo: SQLiteShowcaseRepository = Depends(get_repository),
    ) -> AdminGalleryImageResponse:
        image = repo.get_gallery_image(image_id)
        if image is None:
            raise HTTPException(status_code=404, detail="gallery image not found")
        updated = ShowcaseGalleryImage(
            image_id=image.image_id,
            album_id=image.album_id,
            image_path=image.image_path,
            caption=request.caption if request.caption is not None else image.caption,
            sort_order=request.sortOrder if request.sortOrder is not None else image.sort_order,
            is_visible=request.isVisible if request.isVisible is not None else image.is_visible,
            created_at=image.created_at,
            updated_at=datetime.now(timezone.utc).isoformat(),
        )
        repo.add_gallery_image(updated)
        return AdminGalleryImageResponse.from_image(updated)

    @router.delete(
        "/gallery/images/{image_id}",
        response_model=AdminLoginResponse,
        dependencies=[Depends(require_admin)],
    )
    def delete_admin_gallery_image(
        image_id: str,
        repo: SQLiteShowcaseRepository = Depends(get_repository),
    ) -> AdminLoginResponse:
        if not repo.delete_gallery_image(image_id):
            raise HTTPException(status_code=404, detail="gallery image not found")
        return AdminLoginResponse(ok=True)

    @router.post(
        "/gallery/albums/{album_id}/images/reorder",
        response_model=AdminLoginResponse,
        dependencies=[Depends(require_admin)],
    )
    def reorder_admin_gallery_images(
        album_id: str,
        request: AdminGalleryImageReorderRequest,
        repo: SQLiteShowcaseRepository = Depends(get_repository),
    ) -> AdminLoginResponse:
        if repo.get_gallery_album(album_id) is None:
            raise HTTPException(status_code=404, detail="gallery album not found")
        repo.reorder_gallery_images(album_id, request.imageIds)
        return AdminLoginResponse(ok=True)

    @router.patch(
        "/settings",
        response_model=AdminLoginResponse,
        dependencies=[Depends(require_admin)],
    )
    def update_admin_settings(
        request: AdminSettingsPatchRequest,
        repo: SQLiteShowcaseRepository = Depends(get_repository),
    ) -> AdminLoginResponse:
        if request.statementText is not None:
            repo.set_setting("statement_text", request.statementText)
        if request.shopIntroText is not None:
            repo.set_setting("shop_intro_text", request.shopIntroText)
        if request.watermarkText is not None:
            repo.set_setting("watermark_text", request.watermarkText)
        if request.customerPassword is not None:
            repo.set_setting("customer_password_hash", hash_password(request.customerPassword))
        if request.inventoryUpdatedAt is not None:
            repo.set_setting("inventory_updated_at", request.inventoryUpdatedAt)
        return AdminLoginResponse(ok=True)

    @router.get(
        "/settings",
        response_model=AdminSettingsResponse,
        dependencies=[Depends(require_admin)],
    )
    def get_admin_settings(
        repo: SQLiteShowcaseRepository = Depends(get_repository),
    ) -> AdminSettingsResponse:
        return AdminSettingsResponse(
            statementText=repo.get_setting("statement_text") or "",
            shopIntroText=repo.get_setting("shop_intro_text") or "",
            watermarkText=repo.get_setting("watermark_text") or "星星CCD",
            inventoryUpdatedAt=repo.get_setting("inventory_updated_at") or "",
            hasCustomerPassword=bool(repo.get_setting("customer_password_hash")),
        )

    @router.get(
        "/sections",
        response_model=AdminSectionsResponse,
        dependencies=[Depends(require_admin)],
    )
    def list_admin_sections(
        repo: SQLiteShowcaseRepository = Depends(get_repository),
    ) -> AdminSectionsResponse:
        return AdminSectionsResponse(
            sections=[
                _admin_section_response(repo, section)
                for section in repo.list_sections(include_hidden=True)
            ]
        )

    @router.post(
        "/sections",
        response_model=AdminSectionResponse,
        status_code=201,
        dependencies=[Depends(require_admin)],
    )
    def create_admin_section(
        request: AdminSectionCreateRequest,
        repo: SQLiteShowcaseRepository = Depends(get_repository),
    ) -> AdminSectionResponse:
        now = datetime.now(timezone.utc).isoformat()
        section = ShowcaseSection(
            section_id=uuid.uuid4().hex,
            title=request.title,
            subtitle=request.subtitle,
            active=request.active,
            sort_order=request.sortOrder,
            created_at=now,
            updated_at=now,
        )
        repo.upsert_section(section)
        return _admin_section_response(repo, section)

    @router.patch(
        "/sections/{section_id}",
        response_model=AdminSectionResponse,
        dependencies=[Depends(require_admin)],
    )
    def update_admin_section(
        section_id: str,
        request: AdminSectionPatchRequest,
        repo: SQLiteShowcaseRepository = Depends(get_repository),
    ) -> AdminSectionResponse:
        section = repo.get_section(section_id)
        if section is None:
            raise HTTPException(status_code=404, detail="section not found")
        updated = ShowcaseSection(
            section_id=section.section_id,
            title=request.title if request.title is not None else section.title,
            subtitle=request.subtitle if request.subtitle is not None else section.subtitle,
            active=request.active if request.active is not None else section.active,
            sort_order=request.sortOrder if request.sortOrder is not None else section.sort_order,
            created_at=section.created_at,
            updated_at=datetime.now(timezone.utc).isoformat(),
        )
        repo.upsert_section(updated)
        return _admin_section_response(repo, updated)

    @router.delete(
        "/sections/{section_id}",
        response_model=AdminLoginResponse,
        dependencies=[Depends(require_admin)],
    )
    def delete_admin_section(
        section_id: str,
        repo: SQLiteShowcaseRepository = Depends(get_repository),
    ) -> AdminLoginResponse:
        if not repo.delete_section(section_id):
            raise HTTPException(status_code=404, detail="section not found")
        return AdminLoginResponse(ok=True)

    @router.post(
        "/sections/{section_id}/items",
        response_model=AdminSectionItemResponse,
        status_code=201,
        dependencies=[Depends(require_admin)],
    )
    def create_admin_section_item(
        section_id: str,
        request: AdminSectionItemCreateRequest,
        repo: SQLiteShowcaseRepository = Depends(get_repository),
    ) -> AdminSectionItemResponse:
        if repo.get_section(section_id) is None:
            raise HTTPException(status_code=404, detail="section not found")
        if repo.get_product(request.productId) is None:
            raise HTTPException(status_code=404, detail="product not found")
        now = datetime.now(timezone.utc).isoformat()
        item = ShowcaseSectionItem(
            item_id=uuid.uuid4().hex,
            section_id=section_id,
            product_id=repo.get_product(request.productId).product_id,
            sort_order=request.sortOrder,
            recommend_note=request.recommendNote,
            created_at=now,
            updated_at=now,
        )
        repo.upsert_section_item(item)
        return _admin_section_item_response(repo, item)

    @router.patch(
        "/sections/{section_id}/items/{item_id}",
        response_model=AdminSectionItemResponse,
        dependencies=[Depends(require_admin)],
    )
    def update_admin_section_item(
        section_id: str,
        item_id: str,
        request: AdminSectionItemPatchRequest,
        repo: SQLiteShowcaseRepository = Depends(get_repository),
    ) -> AdminSectionItemResponse:
        item = repo.get_section_item(item_id)
        if item is None or item.section_id != section_id:
            raise HTTPException(status_code=404, detail="section item not found")
        updated = ShowcaseSectionItem(
            item_id=item.item_id,
            section_id=item.section_id,
            product_id=item.product_id,
            sort_order=request.sortOrder if request.sortOrder is not None else item.sort_order,
            recommend_note=(
                request.recommendNote
                if request.recommendNote is not None
                else item.recommend_note
            ),
            created_at=item.created_at,
            updated_at=datetime.now(timezone.utc).isoformat(),
        )
        repo.upsert_section_item(updated)
        return _admin_section_item_response(repo, updated)

    @router.delete(
        "/sections/{section_id}/items/{item_id}",
        response_model=AdminLoginResponse,
        dependencies=[Depends(require_admin)],
    )
    def delete_admin_section_item(
        section_id: str,
        item_id: str,
        repo: SQLiteShowcaseRepository = Depends(get_repository),
    ) -> AdminLoginResponse:
        item = repo.get_section_item(item_id)
        if item is None or item.section_id != section_id:
            raise HTTPException(status_code=404, detail="section item not found")
        repo.delete_section_item(item_id)
        return AdminLoginResponse(ok=True)

    @router.get(
        "/partners",
        response_model=list[AdminPartnerResponse],
        dependencies=[Depends(require_admin)],
    )
    def list_admin_partners(
        repo: SQLiteShowcaseRepository = Depends(get_repository),
    ) -> list[AdminPartnerResponse]:
        return [
            AdminPartnerResponse(
                partnerId=partner.partner_id,
                name=partner.name,
                note=partner.note,
                sortOrder=partner.sort_order,
                active=partner.active,
            )
            for partner in repo.list_authorized_partners(active_only=False)
        ]

    @router.post(
        "/partners",
        response_model=AdminPartnerResponse,
        status_code=201,
        dependencies=[Depends(require_admin)],
    )
    def create_admin_partner(
        request: AdminPartnerCreateRequest,
        repo: SQLiteShowcaseRepository = Depends(get_repository),
    ) -> AdminPartnerResponse:
        partner_id = uuid.uuid4().hex
        repo.add_authorized_partner(
            partner_id,
            request.name,
            request.note,
            request.sortOrder,
            request.active,
        )
        return AdminPartnerResponse(
            partnerId=partner_id,
            name=request.name,
            note=request.note,
            sortOrder=request.sortOrder,
            active=request.active,
        )

    @router.patch(
        "/partners/{partner_id}",
        response_model=AdminPartnerResponse,
        dependencies=[Depends(require_admin)],
    )
    def update_admin_partner(
        partner_id: str,
        request: AdminPartnerPatchRequest,
        repo: SQLiteShowcaseRepository = Depends(get_repository),
    ) -> AdminPartnerResponse:
        partner = repo.get_authorized_partner(partner_id)
        if partner is None:
            raise HTTPException(status_code=404, detail="partner not found")
        repo.add_authorized_partner(
            partner_id,
            request.name if request.name is not None else partner.name,
            request.note if request.note is not None else partner.note,
            request.sortOrder if request.sortOrder is not None else partner.sort_order,
            request.active if request.active is not None else partner.active,
        )
        updated = repo.get_authorized_partner(partner_id)
        assert updated is not None
        return AdminPartnerResponse(
            partnerId=updated.partner_id,
            name=updated.name,
            note=updated.note,
            sortOrder=updated.sort_order,
            active=updated.active,
        )

    @router.delete(
        "/partners/{partner_id}",
        response_model=AdminLoginResponse,
        dependencies=[Depends(require_admin)],
    )
    def delete_admin_partner(
        partner_id: str,
        repo: SQLiteShowcaseRepository = Depends(get_repository),
    ) -> AdminLoginResponse:
        if not repo.delete_authorized_partner(partner_id):
            raise HTTPException(status_code=404, detail="partner not found")
        return AdminLoginResponse(ok=True)

    return router


def _has_valid_customer_session(
    repo: SQLiteShowcaseRepository,
    session_id: str | None,
) -> bool:
    if not session_id:
        return False
    expires_at_raw = repo.get_customer_session_expires_at(session_id)
    if not expires_at_raw:
        return False
    try:
        expires_at = datetime.fromisoformat(expires_at_raw)
    except ValueError:
        return False
    return expires_at > datetime.now(timezone.utc)


def _split_query_values(value: str, *, extra: str = "") -> tuple[str, ...]:
    values: list[str] = []
    seen: set[str] = set()
    for raw_value in (extra, *str(value or "").replace("，", ",").split(",")):
        item = raw_value.strip()
        if item and item not in seen:
            seen.add(item)
            values.append(item)
    return tuple(values)


def _sample_matching_summary_response(
    summary: SampleMatchingSummary,
) -> AdminSampleMatchingSummaryResponse:
    return AdminSampleMatchingSummaryResponse(
        totalProducts=summary.total_products,
        assetModelCount=summary.asset_model_count,
        matchedProductCount=summary.matched_product_count,
        missingProductCount=summary.missing_product_count,
        lowConfidenceProductCount=summary.low_confidence_product_count,
        coverageRate=summary.coverage_rate,
    )


def _ensure_sample_folder_exists(sample_images_path: Path, folder_path: str) -> None:
    normalized = folder_path.replace("\\", "/").strip("/")
    if not normalized or normalized.startswith("../") or "/../" in normalized:
        raise HTTPException(status_code=400, detail="invalid folder path")
    if not any(asset.folder_path == normalized for asset in list_sample_image_assets(sample_images_path)):
        raise HTTPException(status_code=404, detail="sample folder not found")


def _import_sample_images_or_400(sample_images_path: Path, repo, **kwargs):
    try:
        return import_sample_images(sample_images_path, repo, **kwargs)
    except (ValueError, FileNotFoundError, PermissionError) as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


def _admin_search_from_bulk_filters(filters: AdminBulkProductFilters) -> ShowcaseAdminProductSearch:
    brands = list(filters.brands)
    if filters.brand:
        brands.insert(0, filters.brand)
    return ShowcaseAdminProductSearch(
        query=filters.query.strip(),
        model=filters.model.strip(),
        brands=tuple(brand.strip() for brand in brands if brand.strip()),
        price_min=filters.priceMin,
        price_max=filters.priceMax,
        visible=filters.visible,
        sold=filters.sold,
        has_body_image=filters.hasBodyImage,
        has_sample_image=filters.hasSampleImage,
        manual_price=filters.manualPrice,
        tags=tuple(tag.strip() for tag in filters.tags if tag.strip()),
        section_id=filters.sectionId.strip(),
        updated_after=filters.updatedAfter.strip(),
        import_id=filters.importId.strip(),
        review_state=filters.reviewState.strip(),
        limit=100000,
        offset=0,
    )


def _bulk_preview_response(
    repo: SQLiteShowcaseRepository,
    request: AdminBulkOperationRequest,
) -> AdminBulkPreviewResponse:
    search = _admin_search_from_bulk_filters(request.filters)
    product_ids = None
    if request.scope == "selected":
        product_references = [*request.productIds, *request.publicIds]
        product_ids = repo.resolve_product_references(product_references)
    summaries = repo.list_admin_products_for_bulk(
        replace(search, visible=None, sold=None),
        product_ids=product_ids,
    )
    items: list[AdminBulkPreviewItemResponse] = []
    changed_count = 0
    unchanged_count = 0
    skip_reasons: dict[str, int] = {}
    changed_prices: list[int] = []
    total_delta = 0
    for summary in sorted(
        summaries,
        key=lambda item: (-item.product.display_price, item.product.product_id),
    ):
        product = summary.product
        new_price = product.display_price
        new_visible = product.visible
        skipped_reason = _bulk_skip_reason(product, request)
        if not skipped_reason:
            if request.operation == "price":
                candidate_price = _bulk_new_price(product.display_price, request)
                if candidate_price < 0:
                    skipped_reason = "减价后低于 0 元"
                else:
                    new_price = candidate_price
            elif request.operation == "hide":
                new_visible = False
            elif request.operation == "show":
                new_visible = True
        changed = not skipped_reason and (
            new_price != product.display_price or new_visible != product.visible
        )
        if skipped_reason:
            skip_reasons[skipped_reason] = skip_reasons.get(skipped_reason, 0) + 1
        elif changed:
            changed_count += 1
            if new_price != product.display_price:
                changed_prices.append(new_price)
                total_delta += new_price - product.display_price
        else:
            unchanged_count += 1
        items.append(
            AdminBulkPreviewItemResponse(
                productId=product.product_id,
                publicId=product.public_id,
                rowVersion=product.row_version,
                model=product.model,
                brand=product.brand,
                sourcePrice=product.source_display_price,
                oldPrice=product.display_price,
                newPrice=new_price,
                delta=new_price - product.display_price,
                oldVisible=product.visible,
                newVisible=new_visible,
                sold=product.sold,
                changed=changed,
                skippedReason=skipped_reason,
            )
        )
    matched_count = len(items)
    return AdminBulkPreviewResponse(
        operation=request.operation,
        total=matched_count,
        matchedCount=matched_count,
        changedCount=changed_count,
        unchangedCount=unchanged_count,
        skippedCount=sum(skip_reasons.values()),
        skipReasons=skip_reasons,
        priceStats=AdminBulkPriceStatsResponse(
            minimum=min(changed_prices) if changed_prices else None,
            maximum=max(changed_prices) if changed_prices else None,
            totalDelta=total_delta,
        ),
        items=items,
    )


def _bulk_skip_reason(product: ShowcaseProduct, request: AdminBulkOperationRequest) -> str:
    if request.operation == "show" and product.sold:
        return "已售商品不能直接显示"
    if request.filters.sold is not None and product.sold != request.filters.sold:
        return "已售" if product.sold else "未售"
    if request.filters.visible is not None and product.visible != request.filters.visible:
        return "展示中" if product.visible else "已隐藏"
    return ""


def _bulk_new_price(old_price: int, request: AdminBulkOperationRequest) -> int:
    if request.priceMode == "fixed_final":
        return request.amount
    if request.priceMode == "decrement":
        return old_price - request.amount
    return old_price + request.amount


def _bulk_price_range_text(filters: AdminBulkProductFilters) -> str:
    if filters.priceMin is not None and filters.priceMax is not None:
        return f"{filters.priceMin}～{filters.priceMax} 元"
    if filters.priceMin is not None:
        return f"{filters.priceMin}元以上"
    if filters.priceMax is not None:
        return f"{filters.priceMax}元以内"
    return "全部价格"


def _bulk_operation_summary(request: AdminBulkOperationRequest, changed_count: int) -> str:
    scope_text = {
        "selected": "已勾选商品",
        "filtered": "当前筛选结果",
        "all": "全部库存",
    }[request.scope]
    if request.operation == "hide":
        action_text = "批量隐藏"
    elif request.operation == "show":
        action_text = "批量显示"
    elif request.priceMode == "fixed_final":
        action_text = f"固定为{request.amount}元"
    elif request.priceMode == "decrement":
        action_text = f"减价{request.amount}元"
    else:
        action_text = f"加价{request.amount}元"
    return (
        f"{scope_text} · {_bulk_price_range_text(request.filters)} · "
        f"{action_text} · 修改 {changed_count} 台"
    )


def _bulk_filter_text(request: AdminBulkOperationRequest) -> str:
    values: list[tuple[str, object]] = [("scope", request.scope)]
    values.extend(request.filters.model_dump().items())
    parts: list[str] = []
    for key, value in values:
        if value is None or value == "" or value == []:
            continue
        if isinstance(value, bool):
            text = str(value).lower()
        elif isinstance(value, list):
            text = ",".join(str(item) for item in value)
        else:
            text = str(value)
        parts.append(f"{key}={text}")
    return "; ".join(parts)


def _duplicate_model_counts(
    summaries: list[ShowcaseAdminProductSummary],
) -> dict[str, int]:
    counts: dict[str, int] = {}
    for summary in summaries:
        model = summary.product.model.strip()
        if not model:
            continue
        counts[model] = counts.get(model, 0) + 1
    return counts


def _matches_batch_filter(
    product: ShowcaseProduct,
    request: AdminBatchPriceRequest,
) -> bool:
    if request.brand and product.brand != request.brand:
        return False
    if request.visibleOnly and not product.visible:
        return False
    if request.minPrice is not None and product.display_price < request.minPrice:
        return False
    if request.maxPrice is not None and product.display_price > request.maxPrice:
        return False
    if request.query:
        query = request.query.strip().lower()
        haystack = " ".join(
            [product.model, product.brand, product.display_copy, product.raw_copy]
        ).lower()
        if query and query not in haystack:
            return False
    return True


def _admin_section_response(
    repo: SQLiteShowcaseRepository,
    section: ShowcaseSection,
) -> AdminSectionResponse:
    return AdminSectionResponse(
        sectionId=section.section_id,
        title=section.title,
        subtitle=section.subtitle,
        active=section.active,
        sortOrder=section.sort_order,
        items=[
            _admin_section_item_response(repo, item)
            for item in repo.list_section_items(section.section_id)
        ],
    )


def _admin_section_item_response(
    repo: SQLiteShowcaseRepository,
    item: ShowcaseSectionItem,
) -> AdminSectionItemResponse:
    product = repo.get_product(item.product_id)
    return AdminSectionItemResponse(
        itemId=item.item_id,
        sectionId=item.section_id,
        productId=item.product_id,
        sortOrder=item.sort_order,
        recommendNote=item.recommend_note,
        product=AdminProductResponse.from_product(product) if product is not None else None,
    )


def _admin_gallery_album_response(
    repo: SQLiteShowcaseRepository,
    album: ShowcaseGalleryAlbum,
) -> AdminGalleryAlbumResponse:
    return AdminGalleryAlbumResponse(
        albumId=album.album_id,
        title=album.title,
        description=album.description,
        sortOrder=album.sort_order,
        isVisible=album.is_visible,
        createdAt=album.created_at,
        updatedAt=album.updated_at,
        images=[
            AdminGalleryImageResponse.from_image(image)
            for image in repo.list_gallery_images(album.album_id, include_hidden=True)
        ],
    )


def _split_tags(raw_tags: str) -> list[str]:
    tags: list[str] = []
    seen: set[str] = set()
    for raw_tag in raw_tags.split(","):
        tag = raw_tag.strip()
        if not tag or tag in seen:
            continue
        seen.add(tag)
        tags.append(tag)
    return tags


def _join_tags(tags: list[str]) -> str:
    normalized: list[str] = []
    seen: set[str] = set()
    for raw_tag in tags:
        tag = raw_tag.strip()
        if not tag or tag in seen:
            continue
        seen.add(tag)
        normalized.append(tag)
    return ",".join(normalized)
