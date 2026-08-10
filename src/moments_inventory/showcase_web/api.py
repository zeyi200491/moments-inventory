from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
import secrets
import uuid

from fastapi import APIRouter, Cookie, Depends, File, Form, HTTPException, UploadFile
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


class AdminProductResponse(PublicProductResponse):
    visible: bool
    sold: bool
    costPrice: int

    @classmethod
    def from_product(cls, product: ShowcaseProduct) -> "AdminProductResponse":
        base = PublicProductResponse.from_product(product)
        return cls(
            **base.model_dump(),
            visible=product.visible,
            sold=product.sold,
            costPrice=product.cost_price,
        )


class AdminProductsResponse(BaseModel):
    products: list[AdminProductResponse] = Field(default_factory=list)


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
    model: str | None = Field(default=None, max_length=160)
    brand: str | None = Field(default=None, max_length=80)
    displayPrice: int | None = Field(default=None, ge=0)
    displayCopy: str | None = Field(default=None, max_length=10000)
    visible: bool | None = None
    sold: bool | None = None


class AdminProductCreateRequest(BaseModel):
    productId: str = Field(min_length=1, max_length=160)
    model: str = Field(min_length=1, max_length=160)
    brand: str = Field(min_length=1, max_length=80)
    displayPrice: int = Field(ge=0)
    displayCopy: str = Field(default="", max_length=10000)
    visible: bool = True


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


class AdminImageReorderRequest(BaseModel):
    imageIds: list[str] = Field(min_length=1, max_length=50)


class AdminImagesResponse(BaseModel):
    images: list[PublicProductImageResponse] = Field(default_factory=list)


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
    *,
    storage_dir: str | Path = "storage/showcase_images",
) -> APIRouter:
    router = APIRouter(prefix="/api/admin")
    storage_path = Path(storage_dir)

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
        repo: SQLiteShowcaseRepository = Depends(get_repository),
    ) -> AdminProductsResponse:
        return AdminProductsResponse(
            products=[
                AdminProductResponse.from_product(product)
                for product in repo.list_products(include_hidden=True)
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
        )
        repo.upsert_product(product)
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
        product = repo.get_product(product_id)
        if product is None:
            raise HTTPException(status_code=404, detail="product not found")
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
            visible=request.visible if request.visible is not None else product.visible,
            sold=request.sold if request.sold is not None else product.sold,
            updated_at=datetime.now(timezone.utc).isoformat(),
        )
        repo.upsert_product(updated)
        return AdminProductResponse.from_product(updated)

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
        updated_count = 0
        for product in repo.list_products(include_hidden=True):
            if not _matches_batch_filter(product, request):
                continue
            new_price = (
                product.display_price + request.amount
                if request.mode == "increment"
                else request.amount
            )
            repo.upsert_product(
                replace(
                    product,
                    display_price=new_price,
                    updated_at=datetime.now(timezone.utc).isoformat(),
                )
            )
            updated_count += 1
        return AdminBatchPriceResponse(updatedCount=updated_count)

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
        suffix = Path(file.filename or "").suffix.lower()
        if suffix not in {".jpg", ".jpeg", ".png", ".webp"}:
            raise HTTPException(status_code=400, detail="unsupported image type")
        image_id = uuid.uuid4().hex
        product_dir = storage_path / product_id
        product_dir.mkdir(parents=True, exist_ok=True)
        destination = product_dir / f"{image_id}{suffix}"
        destination.write_bytes(await file.read())
        image_path = f"storage/showcase_images/{product_id}/{destination.name}"
        sort_order = len(repo.list_product_images(product_id))
        is_cover = not product.cover_image_path
        repo.add_product_image(
            image_id,
            product_id,
            image_path,
            imageType,
            sort_order,
            is_cover,
        )
        if is_cover:
            repo.upsert_product(replace(product, cover_image_path=image_path))
        image = repo.list_product_images(product_id)[-1]
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

    return router


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
