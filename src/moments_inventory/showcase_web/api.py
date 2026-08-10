from __future__ import annotations

from datetime import datetime, timedelta, timezone
import secrets

from fastapi import APIRouter, Depends, HTTPException
from fastapi import Response
from pydantic import BaseModel, Field

from moments_inventory.showcase_web.auth import verify_password
from moments_inventory.showcase_web.models import ShowcaseProduct, ShowcaseProductImage
from moments_inventory.showcase_web.repository import SQLiteShowcaseRepository


class PublicProductResponse(BaseModel):
    productId: str
    model: str
    brand: str
    displayPrice: int
    displayCopy: str
    coverImagePath: str
    publishedAt: str

    @classmethod
    def from_product(cls, product: ShowcaseProduct) -> "PublicProductResponse":
        return cls(
            productId=product.product_id,
            model=product.model,
            brand=product.brand,
            displayPrice=product.display_price,
            displayCopy=product.display_copy or product.raw_copy,
            coverImagePath=product.cover_image_path,
            publishedAt=product.published_at,
        )


class PublicProductsResponse(BaseModel):
    products: list[PublicProductResponse] = Field(default_factory=list)


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


def create_public_router(
    repository: SQLiteShowcaseRepository,
) -> APIRouter:
    router = APIRouter(prefix="/api/public")

    def get_repository() -> SQLiteShowcaseRepository:
        return repository

    @router.get("/products", response_model=PublicProductsResponse)
    def list_public_products(
        repo: SQLiteShowcaseRepository = Depends(get_repository),
    ) -> PublicProductsResponse:
        products = [
            product
            for product in repo.list_products(include_hidden=False)
            if not product.sold
        ]
        return PublicProductsResponse(
            products=[PublicProductResponse.from_product(product) for product in products]
        )

    @router.get("/products/{product_id}", response_model=PublicProductDetailResponse)
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

    return router


def create_admin_router(
    repository: SQLiteShowcaseRepository,
) -> APIRouter:
    router = APIRouter(prefix="/api/admin")

    def get_repository() -> SQLiteShowcaseRepository:
        return repository

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

    return router
