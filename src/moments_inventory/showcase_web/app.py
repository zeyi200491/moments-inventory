from __future__ import annotations

from pathlib import Path
from contextlib import asynccontextmanager
import time

from fastapi import FastAPI, HTTPException, Cookie, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from moments_inventory.showcase_web.api import create_admin_router, create_public_router, _has_valid_customer_session
from moments_inventory.showcase_web.repository import SQLiteShowcaseRepository
from moments_inventory.showcase_web.image_service import ImageVariantService
from moments_inventory.showcase_web.public_cache import PublicResponseCacheMiddleware
from PIL import UnidentifiedImageError


def create_showcase_app(
    *,
    repository: SQLiteShowcaseRepository | None = None,
    database_path: str | Path = "data/showcase.db",
    storage_dir: str | Path = "storage/showcase_images",
    sample_images_dir: str | Path = "output/ccdcpt",
) -> FastAPI:
    repo = repository or SQLiteShowcaseRepository(database_path)
    repo.initialize()
    @asynccontextmanager
    async def lifespan(app):
        yield
        if repository is None:
            repo.close()

    app = FastAPI(title="星星CCD库存展示系统", lifespan=lifespan)
    app.add_middleware(PublicResponseCacheMiddleware, repository=repo)
    media_access_state = {"checked_at": 0.0, "password_hash": ""}

    @app.middleware("http")
    async def protect_customer_media(request: Request, call_next):
        """客户口令开启时，原图与变体使用同一访问边界。"""
        if request.url.path.startswith(("/storage/showcase_images/", "/sample-images/")):
            now = time.monotonic()
            if now - media_access_state["checked_at"] >= 0.25:
                media_access_state["password_hash"] = repo.get_setting("customer_password_hash") or ""
                media_access_state["checked_at"] = now
            password_hash = media_access_state["password_hash"]
            session_id = request.cookies.get("showcase_customer_access")
            if password_hash and not _has_valid_customer_session(repo, session_id):
                return JSONResponse({"detail": "customer password required"}, status_code=401)
        response = await call_next(request)
        if request.url.path.startswith(("/storage/showcase_images/", "/sample-images/")):
            response.headers["Cache-Control"] = "private, max-age=3600"
        return response

    app.include_router(create_public_router(repo))
    app.include_router(
        create_admin_router(
            repo,
            storage_dir=storage_dir,
            sample_images_dir=sample_images_dir,
        )
    )

    static_dir = Path(__file__).with_name("static")
    storage_path = Path(storage_dir)
    sample_images_path = Path(sample_images_dir)
    storage_path.mkdir(parents=True, exist_ok=True)
    app.mount("/static", StaticFiles(directory=static_dir), name="showcase_static")
    app.mount("/storage/showcase_images", StaticFiles(directory=storage_path), name="showcase_images")
    app.mount("/sample-images", StaticFiles(directory=sample_images_path, check_dir=False), name="sample_images")

    variants = ImageVariantService(
        {"sample-images": sample_images_path, "storage/showcase_images": storage_path},
        storage_path.parent / "showcase_variants",
    )

    @app.get("/api/public/image-variant")
    def image_variant(path: str, width: int = 480, showcase_customer_access: str | None = Cookie(default=None)):
        if repo.get_setting("customer_password_hash") and not _has_valid_customer_session(repo, showcase_customer_access):
            raise HTTPException(401, "customer password required")
        try:
            variant = variants.get_variant(path, width)
        except FileNotFoundError:
            raise HTTPException(404, "图片不存在")
        except (ValueError, UnidentifiedImageError):
            raise HTTPException(400, "无效图片或尺寸")
        return FileResponse(variant, media_type="image/webp", headers={"Cache-Control": "private, max-age=3600"})

    @app.get("/")
    def index() -> FileResponse:
        return FileResponse(static_dir / "index.html")

    @app.get("/product")
    def product_detail() -> FileResponse:
        return FileResponse(static_dir / "product.html")

    @app.get("/admin-xingxing")
    def admin() -> FileResponse:
        return FileResponse(static_dir / "admin.html")

    return app
