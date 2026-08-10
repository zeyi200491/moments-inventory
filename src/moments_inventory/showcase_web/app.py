from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from moments_inventory.showcase_web.api import create_admin_router, create_public_router
from moments_inventory.showcase_web.repository import SQLiteShowcaseRepository


def create_showcase_app(
    *,
    repository: SQLiteShowcaseRepository | None = None,
    database_path: str | Path = "data/showcase.db",
    storage_dir: str | Path = "storage/showcase_images",
) -> FastAPI:
    repo = repository or SQLiteShowcaseRepository(database_path)
    repo.initialize()
    app = FastAPI(title="星星CCD库存展示系统")
    app.include_router(create_public_router(repo))
    app.include_router(create_admin_router(repo))

    static_dir = Path(__file__).with_name("static")
    storage_path = Path(storage_dir)
    storage_path.mkdir(parents=True, exist_ok=True)
    app.mount("/static", StaticFiles(directory=static_dir), name="showcase_static")
    app.mount("/storage/showcase_images", StaticFiles(directory=storage_path), name="showcase_images")

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
