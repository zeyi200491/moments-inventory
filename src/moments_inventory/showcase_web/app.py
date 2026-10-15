from __future__ import annotations

from pathlib import Path
from contextlib import asynccontextmanager
from datetime import datetime, timezone

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from moments_inventory.showcase_web.api import create_admin_router, create_public_router, _has_valid_customer_session
from moments_inventory.showcase_web.auth import LoginAttemptLimiter
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
    admin_login_path: str = "/admin-xingxing",
    customer_access_cookie_days: int = 7,
    login_limiter: LoginAttemptLimiter | None = None,
) -> FastAPI:
    repo = repository or SQLiteShowcaseRepository(database_path)
    repo.initialize()
    limiter = login_limiter or LoginAttemptLimiter()
    @asynccontextmanager
    async def lifespan(app):
        yield
        if repository is None:
            repo.close()

    app = FastAPI(title="星星CCD库存展示系统", lifespan=lifespan)
    app.add_middleware(PublicResponseCacheMiddleware, repository=repo)

    def _is_admin_session(session_id: str | None) -> bool:
        expires_at_raw = repo.get_admin_session_expires_at(session_id) if session_id else None
        try:
            expiration = datetime.fromisoformat(expires_at_raw) if expires_at_raw else None
            if expiration is not None and expiration.tzinfo is None:
                expiration = expiration.replace(tzinfo=timezone.utc)
            return expiration is not None and expiration > datetime.now(timezone.utc)
        except (TypeError, ValueError):
            return False

    def _media_path_from_url(url_path: str) -> str | None:
        for prefix in ("storage/showcase_images", "sample-images"):
            url_prefix = f"/{prefix}/"
            if not url_path.startswith(url_prefix):
                continue
            relative_path = url_path[len(url_prefix):]
            if not relative_path or any(part == ".." for part in relative_path.replace("\\", "/").split("/")):
                return None
            return f"{prefix}/{relative_path}"
        return None

    def _media_access_error(request: Request, media_path: str | None) -> tuple[int, str] | None:
        if _is_admin_session(request.cookies.get("showcase_admin_session")):
            return None
        password_hash = repo.get_setting("customer_password_hash") or ""
        if password_hash and not _has_valid_customer_session(
            repo,
            request.cookies.get("showcase_customer_access"),
        ):
            return 401, "customer password required"
        if media_path is None or not repo.is_media_path_public(media_path):
            return 404, "图片不存在"
        return None

    @app.middleware("http")
    async def protect_customer_media(request: Request, call_next):
        """客户口令与公开引用共同控制原图访问，避免隐藏后直链继续有效。"""
        media_path = _media_path_from_url(request.url.path)
        if request.url.path.startswith(("/storage/showcase_images/", "/sample-images/")):
            access_error = _media_access_error(request, media_path)
            response = (
                JSONResponse(
                    {"detail": access_error[1]},
                    status_code=access_error[0],
                    headers={"Cache-Control": "private, no-store"},
                )
                if access_error is not None
                else await call_next(request)
            )
            response.headers["Cache-Control"] = "private, no-store"
            return response
        response = await call_next(request)
        return response

    app.include_router(create_public_router(repo, customer_access_cookie_days, limiter))
    app.include_router(
        create_admin_router(
            repo,
            storage_dir=storage_dir,
            sample_images_dir=sample_images_dir,
            login_limiter=limiter,
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
    def image_variant(path: str, request: Request, width: int = 480):
        access_error = _media_access_error(request, path)
        if access_error is not None:
            raise HTTPException(access_error[0], access_error[1], headers={"Cache-Control": "private, no-store"})
        try:
            variant = variants.get_variant(path, width)
        except FileNotFoundError:
            raise HTTPException(404, "图片不存在", headers={"Cache-Control": "private, no-store"})
        except (ValueError, UnidentifiedImageError):
            raise HTTPException(400, "无效图片或尺寸", headers={"Cache-Control": "private, no-store"})
        return FileResponse(variant, media_type="image/webp", headers={"Cache-Control": "private, no-store"})

    @app.get("/")
    def index() -> FileResponse:
        return FileResponse(static_dir / "index.html")

    @app.get("/product")
    def product_detail() -> FileResponse:
        return FileResponse(static_dir / "product.html")

    @app.get(admin_login_path)
    def admin() -> FileResponse:
        return FileResponse(static_dir / "admin.html")

    return app
