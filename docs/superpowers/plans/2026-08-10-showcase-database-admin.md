# CCD Showcase Database Admin Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a database-backed CCD showcase system with customer display pages, single-admin management, Excel import, price editing, visibility control, image management, statement/partner/password management, and Windows bat startup.

**Architecture:** Add a new `moments_inventory.showcase_web` package that owns the database-backed showcase app. SQLite stores products, images, settings, authorized partners, admin session data, and import logs. FastAPI serves public customer pages/API and protected admin pages/API; existing static-site generation remains available as a separate lightweight path until this database version replaces it.

**Tech Stack:** Python, FastAPI, SQLite, pytest, openpyxl-compatible existing workbook reader, plain HTML/CSS/JavaScript, Windows `.bat`, local filesystem image storage.

---

## Scope

This plan covers the confirmed database version:

- SQLite product tables.
- Import from `manual/客户展示库存.xlsx`.
- Customer display pages read from database.
- Product hide/show.
- Single product price edit.
- Batch price adjustment.
- Admin login.
- Product list/add/delete/edit.
- Image upload and ordering.
- Statement management.
- Authorized partner management.
- Customer access password management.
- Bat startup for local/server use.

This plan does not add multi-admin roles, payment, customer accounts, analytics dashboards, cloud object storage, or automatic public deployment. Those are excluded from this implementation.

## File Structure

- Create `src/moments_inventory/showcase_web/models.py`
  - Dataclasses for database records and request/response DTO helpers.
- Create `src/moments_inventory/showcase_web/repository.py`
  - SQLite schema initialization and all product/image/settings/partner/import-log persistence.
- Create `src/moments_inventory/showcase_web/importer.py`
  - Imports `manual/客户展示库存.xlsx` into SQLite while preserving manual DB edits.
- Create `src/moments_inventory/showcase_web/auth.py`
  - Password hashing, admin session token creation, and cookie helpers.
- Create `src/moments_inventory/showcase_web/api.py`
  - FastAPI routes for public display and admin CRUD.
- Create `src/moments_inventory/showcase_web/app.py`
  - App factory wiring repository, static files, and routers.
- Create `src/moments_inventory/showcase_web/static/index.html`
  - Customer list page.
- Create `src/moments_inventory/showcase_web/static/product.html`
  - Customer product detail page.
- Create `src/moments_inventory/showcase_web/static/admin.html`
  - Admin interface.
- Create `src/moments_inventory/showcase_web/static/showcase.css`
  - Shared customer/admin styles including whole-page slanted watermark.
- Create `src/moments_inventory/showcase_web/static/showcase.js`
  - Customer list/detail behavior.
- Create `src/moments_inventory/showcase_web/static/admin.js`
  - Admin login, product management, batch price, image upload, settings.
- Modify `src/moments_inventory/cli.py`
  - Add `showcase-db-init`, `showcase-db-import`, `showcase-server`, and `showcase-db-backup`.
- Create `config/showcase.yaml`
  - Default local database path, storage path, host, port, admin route.
- Create `start_showcase_server.bat`
  - Starts the FastAPI showcase management system.
- Create `import_showcase_excel.bat`
  - Imports the manual Excel file into SQLite.
- Create `backup_showcase_db.bat`
  - Backs up SQLite database and image storage.
- Create tests:
  - `tests/test_showcase_web_repository.py`
  - `tests/test_showcase_web_importer.py`
  - `tests/test_showcase_web_api_public.py`
  - `tests/test_showcase_web_api_admin.py`
  - `tests/test_showcase_web_auth.py`
  - `tests/test_cli_showcase_web.py`

---

### Task 1: Database Models And Repository

**Files:**
- Create: `src/moments_inventory/showcase_web/__init__.py`
- Create: `src/moments_inventory/showcase_web/models.py`
- Create: `src/moments_inventory/showcase_web/repository.py`
- Test: `tests/test_showcase_web_repository.py`

- [ ] **Step 1: Write failing repository initialization test**

```python
from pathlib import Path

from moments_inventory.showcase_web.repository import SQLiteShowcaseRepository


def test_initialize_creates_showcase_tables(tmp_path: Path) -> None:
    repo = SQLiteShowcaseRepository(tmp_path / "showcase.db")
    repo.initialize()

    tables = repo.list_table_names()

    assert "showcase_products" in tables
    assert "showcase_product_images" in tables
    assert "showcase_settings" in tables
    assert "showcase_authorized_partners" in tables
    assert "showcase_import_logs" in tables
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_showcase_web_repository.py::test_initialize_creates_showcase_tables -q`

Expected: FAIL with `ModuleNotFoundError: No module named 'moments_inventory.showcase_web'`.

- [ ] **Step 3: Implement models and repository initialization**

Create `models.py` with:

```python
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
```

Create `repository.py` with `SQLiteShowcaseRepository.initialize()` creating:

```sql
create table if not exists showcase_products (
  product_id text primary key,
  model text not null,
  brand text not null,
  cost_price integer not null,
  display_price integer not null,
  visible integer not null,
  sold integer not null,
  published_at text not null,
  raw_copy text not null,
  display_copy text not null,
  cover_image_path text not null,
  created_at text not null,
  updated_at text not null,
  last_seen_import_id text not null
)
```

Also create:

```sql
create table if not exists showcase_product_images (
  image_id text primary key,
  product_id text not null,
  image_path text not null,
  image_type text not null,
  sort_order integer not null,
  is_cover integer not null,
  foreign key(product_id) references showcase_products(product_id)
)
```

```sql
create table if not exists showcase_settings (
  setting_key text primary key,
  setting_value text not null
)
```

```sql
create table if not exists showcase_authorized_partners (
  partner_id text primary key,
  name text not null,
  note text not null,
  sort_order integer not null,
  active integer not null
)
```

```sql
create table if not exists showcase_import_logs (
  import_id text primary key,
  source_path text not null,
  imported_at text not null,
  inserted_count integer not null,
  updated_count integer not null,
  missing_count integer not null
)
```

Add `list_table_names()` for tests.

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_showcase_web_repository.py::test_initialize_creates_showcase_tables -q`

Expected: PASS.

- [ ] **Step 5: Add product upsert/list test**

```python
from moments_inventory.showcase_web.models import ShowcaseProduct


def test_upsert_product_preserves_and_lists_product(tmp_path: Path) -> None:
    repo = SQLiteShowcaseRepository(tmp_path / "showcase.db")
    repo.initialize()
    product = ShowcaseProduct(
        product_id="p1",
        model="佳能ixus80",
        brand="佳能",
        cost_price=500,
        display_price=558,
        visible=True,
        sold=False,
        published_at="2026-08-10T10:00:00+08:00",
        raw_copy="原文",
        display_copy="展示文案",
        cover_image_path="storage/showcase_images/p1/body.jpg",
        created_at="2026-08-10T10:01:00+08:00",
        updated_at="2026-08-10T10:01:00+08:00",
        last_seen_import_id="import-1",
    )

    repo.upsert_product(product)

    assert repo.get_product("p1") == product
    assert repo.list_products(include_hidden=True)[0] == product
```

- [ ] **Step 6: Implement product persistence**

Add `upsert_product()`, `get_product()`, and `list_products(include_hidden: bool = False)`.

- [ ] **Step 7: Verify repository tests pass**

Run: `python -m pytest tests/test_showcase_web_repository.py -q`

Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add src/moments_inventory/showcase_web tests/test_showcase_web_repository.py
git commit -m "feat: add showcase database repository"
```

---

### Task 2: Excel Import Into SQLite

**Files:**
- Create: `src/moments_inventory/showcase_web/importer.py`
- Modify: `src/moments_inventory/showcase_web/repository.py`
- Test: `tests/test_showcase_web_importer.py`

- [ ] **Step 1: Write failing import test**

```python
from pathlib import Path

from moments_inventory.exporter import _write_workbook
from moments_inventory.showcase import SHOWCASE_HEADERS
from moments_inventory.showcase_web.importer import import_showcase_workbook
from moments_inventory.showcase_web.repository import SQLiteShowcaseRepository


def test_import_showcase_workbook_inserts_visible_product(tmp_path: Path) -> None:
    workbook = tmp_path / "客户展示库存.xlsx"
    _write_workbook(
        workbook,
        [
            SHOWCASE_HEADERS,
            [
                "p1", "佳能ixus80", "佳能", 500, 558, "是",
                "2026-08-10T10:00:00+08:00", "晨曦", "原文", "展示文案",
                "output/media/p1/body.jpg", "", "佳能ixus80", "",
            ],
        ],
    )
    repo = SQLiteShowcaseRepository(tmp_path / "showcase.db")
    repo.initialize()

    result = import_showcase_workbook(workbook, repo)

    product = repo.get_product("p1")
    assert result.inserted_count == 1
    assert product is not None
    assert product.display_price == 558
    assert product.visible is True
    assert product.cover_image_path == "output/media/p1/body.jpg"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_showcase_web_importer.py::test_import_showcase_workbook_inserts_visible_product -q`

Expected: FAIL because `import_showcase_workbook` does not exist.

- [ ] **Step 3: Implement importer**

Use existing `read_xlsx_rows_from_bytes()` and `SHOWCASE_HEADERS`. Convert `是否展示 == "是"` to `visible=True`. Insert body image as both `cover_image_path` and first image row when a path exists.

- [ ] **Step 4: Verify insert test passes**

Run: `python -m pytest tests/test_showcase_web_importer.py::test_import_showcase_workbook_inserts_visible_product -q`

Expected: PASS.

- [ ] **Step 5: Write preservation test for manual DB edits**

```python
def test_import_preserves_existing_admin_price_and_visibility(tmp_path: Path) -> None:
    workbook = tmp_path / "客户展示库存.xlsx"
    _write_workbook(
        workbook,
        [
            SHOWCASE_HEADERS,
            ["p1", "佳能ixus80", "佳能", 500, 558, "是", "", "晨曦", "原文新", "展示文案新", "", "", "佳能ixus80", ""],
        ],
    )
    repo = SQLiteShowcaseRepository(tmp_path / "showcase.db")
    repo.initialize()
    import_showcase_workbook(workbook, repo)
    repo.update_product_price("p1", 688)
    repo.set_product_visibility("p1", False)

    import_showcase_workbook(workbook, repo)

    product = repo.get_product("p1")
    assert product is not None
    assert product.display_price == 688
    assert product.visible is False
    assert product.raw_copy == "原文新"
```

- [ ] **Step 6: Implement preservation behavior**

When a product already exists, update model/brand/cost/raw copy/published/image/last_seen, but preserve `display_price`, `visible`, `sold`, and admin-edited `display_copy` unless it is blank.

- [ ] **Step 7: Verify importer tests pass**

Run: `python -m pytest tests/test_showcase_web_importer.py -q`

Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add src/moments_inventory/showcase_web/importer.py src/moments_inventory/showcase_web/repository.py tests/test_showcase_web_importer.py
git commit -m "feat: import showcase workbook into database"
```

---

### Task 3: Public Display API And Customer Pages

**Files:**
- Create: `src/moments_inventory/showcase_web/api.py`
- Create: `src/moments_inventory/showcase_web/app.py`
- Create: `src/moments_inventory/showcase_web/static/index.html`
- Create: `src/moments_inventory/showcase_web/static/product.html`
- Create: `src/moments_inventory/showcase_web/static/showcase.css`
- Create: `src/moments_inventory/showcase_web/static/showcase.js`
- Test: `tests/test_showcase_web_api_public.py`

- [ ] **Step 1: Write failing public list API test**

```python
from fastapi.testclient import TestClient

from moments_inventory.showcase_web.app import create_showcase_app
from moments_inventory.showcase_web.models import ShowcaseProduct
from moments_inventory.showcase_web.repository import SQLiteShowcaseRepository


def _product(
    product_id: str,
    *,
    visible: bool,
    display_price: int,
    brand: str = "佳能",
) -> ShowcaseProduct:
    return ShowcaseProduct(
        product_id=product_id,
        model=f"{brand}测试型号",
        brand=brand,
        cost_price=300,
        display_price=display_price,
        visible=visible,
        sold=False,
        published_at="2026-08-10T10:00:00+08:00",
        raw_copy="原文",
        display_copy="展示文案",
        cover_image_path="",
        created_at="2026-08-10T10:01:00+08:00",
        updated_at="2026-08-10T10:01:00+08:00",
        last_seen_import_id="import-1",
    )


def test_public_products_api_returns_only_visible_products(tmp_path: Path) -> None:
    repo = SQLiteShowcaseRepository(tmp_path / "showcase.db")
    repo.initialize()
    repo.upsert_product(_product("visible", visible=True, display_price=558))
    repo.upsert_product(_product("hidden", visible=False, display_price=588))
    client = TestClient(create_showcase_app(repository=repo))

    response = client.get("/api/public/products")

    assert response.status_code == 200
    assert [item["productId"] for item in response.json()["products"]] == ["visible"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_showcase_web_api_public.py::test_public_products_api_returns_only_visible_products -q`

Expected: FAIL because `create_showcase_app` does not exist.

- [ ] **Step 3: Implement app factory and public products route**

Add `create_showcase_app(repository: SQLiteShowcaseRepository | None = None, database_path: str | Path = "data/showcase.db")`. Add `GET /api/public/products` returning visible and unsold products.

- [ ] **Step 4: Verify list API test passes**

Run: `python -m pytest tests/test_showcase_web_api_public.py::test_public_products_api_returns_only_visible_products -q`

Expected: PASS.

- [ ] **Step 5: Write product detail API test**

```python
def test_public_product_detail_returns_up_to_nine_images(tmp_path: Path) -> None:
    repo = SQLiteShowcaseRepository(tmp_path / "showcase.db")
    repo.initialize()
    repo.upsert_product(_product("p1", visible=True, display_price=558))
    for index in range(12):
        repo.add_product_image("p1", f"storage/showcase_images/p1/{index}.jpg", "detail", index, index == 0)
    client = TestClient(create_showcase_app(repository=repo))

    response = client.get("/api/public/products/p1")

    assert response.status_code == 200
    assert len(response.json()["images"]) == 9
```

- [ ] **Step 6: Implement product detail route**

Add `GET /api/public/products/{product_id}`. Return 404 for hidden/sold/missing products. Return images sorted by `sort_order` and capped at 9.

- [ ] **Step 7: Create customer pages**

`index.html` loads `/api/public/products` and renders search/brand/price filters. `product.html?id=p1` loads `/api/public/products/p1` and renders detail text plus up to 9 images. CSS includes `.site-watermark` with low opacity and slanted repeated `星星CCD`.

- [ ] **Step 8: Verify public API tests pass**

Run: `python -m pytest tests/test_showcase_web_api_public.py -q`

Expected: PASS.

- [ ] **Step 9: Commit**

```bash
git add src/moments_inventory/showcase_web tests/test_showcase_web_api_public.py
git commit -m "feat: serve database showcase pages"
```

---

### Task 4: Admin Authentication

**Files:**
- Create: `src/moments_inventory/showcase_web/auth.py`
- Modify: `src/moments_inventory/showcase_web/api.py`
- Modify: `src/moments_inventory/showcase_web/repository.py`
- Test: `tests/test_showcase_web_auth.py`
- Test: `tests/test_showcase_web_api_admin.py`

- [ ] **Step 1: Write password hash test**

```python
from moments_inventory.showcase_web.auth import hash_password, verify_password


def test_hash_password_does_not_store_plaintext_and_verifies() -> None:
    hashed = hash_password("admin-pass")

    assert hashed != "admin-pass"
    assert verify_password("admin-pass", hashed) is True
    assert verify_password("wrong", hashed) is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_showcase_web_auth.py::test_hash_password_does_not_store_plaintext_and_verifies -q`

Expected: FAIL because `auth.py` does not exist.

- [ ] **Step 3: Implement auth hashing**

Use `hashlib.pbkdf2_hmac("sha256", password, salt, 200_000)` and store `pbkdf2_sha256$iterations$salt_b64$digest_b64`.

- [ ] **Step 4: Verify auth hash test passes**

Run: `python -m pytest tests/test_showcase_web_auth.py::test_hash_password_does_not_store_plaintext_and_verifies -q`

Expected: PASS.

- [ ] **Step 5: Write admin login route test**

```python
def test_admin_login_sets_session_cookie(tmp_path: Path) -> None:
    repo = SQLiteShowcaseRepository(tmp_path / "showcase.db")
    repo.initialize()
    repo.set_setting("admin_password_hash", hash_password("admin-pass"))
    client = TestClient(create_showcase_app(repository=repo))

    response = client.post("/api/admin/login", json={"password": "admin-pass"})

    assert response.status_code == 200
    assert "showcase_admin_session" in response.cookies
```

- [ ] **Step 6: Implement admin login**

Add `POST /api/admin/login`. Use a signed random session token stored in SQLite table `showcase_admin_sessions(session_id, expires_at)`. Set HttpOnly cookie `showcase_admin_session`.

- [ ] **Step 7: Verify admin auth tests pass**

Run: `python -m pytest tests/test_showcase_web_auth.py tests/test_showcase_web_api_admin.py::test_admin_login_sets_session_cookie -q`

Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add src/moments_inventory/showcase_web tests/test_showcase_web_auth.py tests/test_showcase_web_api_admin.py
git commit -m "feat: add showcase admin login"
```

---

### Task 5: Admin Product Management

**Files:**
- Modify: `src/moments_inventory/showcase_web/api.py`
- Modify: `src/moments_inventory/showcase_web/repository.py`
- Create/Modify: `src/moments_inventory/showcase_web/static/admin.html`
- Create/Modify: `src/moments_inventory/showcase_web/static/admin.js`
- Test: `tests/test_showcase_web_api_admin.py`

- [ ] **Step 1: Add admin API test fixtures and write single price update test**

```python
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from moments_inventory.showcase_web.app import create_showcase_app
from moments_inventory.showcase_web.auth import hash_password
from moments_inventory.showcase_web.models import ShowcaseProduct
from moments_inventory.showcase_web.repository import SQLiteShowcaseRepository


def _product(
    product_id: str,
    *,
    visible: bool,
    display_price: int,
    brand: str = "佳能",
) -> ShowcaseProduct:
    return ShowcaseProduct(
        product_id=product_id,
        model=f"{brand}测试型号",
        brand=brand,
        cost_price=300,
        display_price=display_price,
        visible=visible,
        sold=False,
        published_at="2026-08-10T10:00:00+08:00",
        raw_copy="原文",
        display_copy="展示文案",
        cover_image_path="",
        created_at="2026-08-10T10:01:00+08:00",
        updated_at="2026-08-10T10:01:00+08:00",
        last_seen_import_id="import-1",
    )


@pytest.fixture
def repo(tmp_path: Path) -> SQLiteShowcaseRepository:
    repository = SQLiteShowcaseRepository(tmp_path / "showcase.db")
    repository.initialize()
    repository.set_setting("admin_password_hash", hash_password("admin-pass"))
    return repository


@pytest.fixture
def authenticated_client(repo: SQLiteShowcaseRepository) -> TestClient:
    client = TestClient(create_showcase_app(repository=repo))
    response = client.post("/api/admin/login", json={"password": "admin-pass"})
    assert response.status_code == 200
    return client


def test_admin_can_update_single_product_price(authenticated_client, repo) -> None:
    repo.upsert_product(_product("p1", visible=True, display_price=558))

    response = authenticated_client.patch("/api/admin/products/p1", json={"displayPrice": 688})

    assert response.status_code == 200
    assert repo.get_product("p1").display_price == 688
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_showcase_web_api_admin.py::test_admin_can_update_single_product_price -q`

Expected: FAIL because patch route does not exist.

- [ ] **Step 3: Implement product patch route**

Add `PATCH /api/admin/products/{product_id}` supporting `model`, `brand`, `displayPrice`, `displayCopy`, `visible`, and `sold`.

- [ ] **Step 4: Verify single update test passes**

Run: `python -m pytest tests/test_showcase_web_api_admin.py::test_admin_can_update_single_product_price -q`

Expected: PASS.

- [ ] **Step 5: Write batch price update test**

```python
def test_admin_can_batch_adjust_prices_by_brand(authenticated_client, repo) -> None:
    repo.upsert_product(_product("canon", visible=True, display_price=500, brand="佳能"))
    repo.upsert_product(_product("sony", visible=True, display_price=500, brand="索尼"))

    response = authenticated_client.post(
        "/api/admin/products/batch-price",
        json={"mode": "increment", "amount": 30, "brand": "佳能"},
    )

    assert response.status_code == 200
    assert response.json()["updatedCount"] == 1
    assert repo.get_product("canon").display_price == 530
    assert repo.get_product("sony").display_price == 500
```

- [ ] **Step 6: Implement batch price route**

Add `POST /api/admin/products/batch-price` with filters `brand`, `minPrice`, `maxPrice`, `query`, `visibleOnly`, and modes `increment` or `set`.

- [ ] **Step 7: Write add/delete product tests**

```python
def test_admin_can_create_and_delete_product(authenticated_client, repo) -> None:
    create_response = authenticated_client.post(
        "/api/admin/products",
        json={"productId": "manual-1", "model": "理光rr30", "brand": "理光", "displayPrice": 399, "displayCopy": "手动新增"},
    )
    assert create_response.status_code == 201
    assert repo.get_product("manual-1") is not None

    delete_response = authenticated_client.delete("/api/admin/products/manual-1")
    assert delete_response.status_code == 200
    assert repo.get_product("manual-1") is None
```

- [ ] **Step 8: Implement create/delete routes**

Add `POST /api/admin/products` and `DELETE /api/admin/products/{product_id}`. Deletion is hard delete for manual mistakes; sold/hidden remains separate.

- [ ] **Step 9: Build admin product UI**

`admin.html` includes login panel, product table, search/filter controls, inline price input, visible toggle, sold toggle, edit modal, create-product modal, and batch-price panel.

- [ ] **Step 10: Verify admin product tests pass**

Run: `python -m pytest tests/test_showcase_web_api_admin.py -q`

Expected: PASS.

- [ ] **Step 11: Commit**

```bash
git add src/moments_inventory/showcase_web tests/test_showcase_web_api_admin.py
git commit -m "feat: manage showcase products"
```

---

### Task 6: Image Upload And Ordering

**Files:**
- Modify: `src/moments_inventory/showcase_web/api.py`
- Modify: `src/moments_inventory/showcase_web/repository.py`
- Modify: `src/moments_inventory/showcase_web/static/admin.js`
- Test: `tests/test_showcase_web_api_admin.py`

- [ ] **Step 1: Write image upload test**

```python
def test_admin_can_upload_product_image(authenticated_client, repo, tmp_path: Path) -> None:
    repo.upsert_product(_product("p1", visible=True, display_price=558))

    response = authenticated_client.post(
        "/api/admin/products/p1/images",
        files={"file": ("body.jpg", b"image-bytes", "image/jpeg")},
        data={"imageType": "detail"},
    )

    assert response.status_code == 201
    image = repo.list_product_images("p1")[0]
    assert image.image_type == "detail"
    assert Path(image.image_path).exists()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_showcase_web_api_admin.py::test_admin_can_upload_product_image -q`

Expected: FAIL because upload route does not exist.

- [ ] **Step 3: Implement upload route**

Add `POST /api/admin/products/{product_id}/images`. Accept `.jpg`, `.jpeg`, `.png`, `.webp`. Store under `storage/showcase_images/<product_id>/<image_id>.<ext>`. Reject unsupported content types with 400.

- [ ] **Step 4: Add reorder/set-cover/delete image tests**

```python
def test_admin_can_reorder_set_cover_and_delete_images(authenticated_client, repo) -> None:
    repo.add_product_image("p1", "a.jpg", "detail", 0, True)
    repo.add_product_image("p1", "b.jpg", "detail", 1, False)

    reorder = authenticated_client.post("/api/admin/products/p1/images/reorder", json={"imageIds": ["b", "a"]})
    assert reorder.status_code == 200

    cover = authenticated_client.post("/api/admin/products/p1/images/b/cover")
    assert cover.status_code == 200

    delete = authenticated_client.delete("/api/admin/products/p1/images/a")
    assert delete.status_code == 200
```

- [ ] **Step 5: Implement image ordering routes**

Add:
- `POST /api/admin/products/{product_id}/images/reorder`
- `POST /api/admin/products/{product_id}/images/{image_id}/cover`
- `DELETE /api/admin/products/{product_id}/images/{image_id}`

- [ ] **Step 6: Update customer detail route**

Ensure `GET /api/public/products/{product_id}` returns cover first, then detail/sample images, capped at 9.

- [ ] **Step 7: Update admin UI**

Add image upload button, image grid, delete button, set-cover button, and up/down order controls.

- [ ] **Step 8: Verify image tests pass**

Run: `python -m pytest tests/test_showcase_web_api_admin.py -q`

Expected: PASS.

- [ ] **Step 9: Commit**

```bash
git add src/moments_inventory/showcase_web tests/test_showcase_web_api_admin.py
git commit -m "feat: manage showcase product images"
```

---

### Task 7: Statement, Partners, And Customer Password Management

**Files:**
- Modify: `src/moments_inventory/showcase_web/api.py`
- Modify: `src/moments_inventory/showcase_web/repository.py`
- Modify: `src/moments_inventory/showcase_web/static/admin.js`
- Modify: `src/moments_inventory/showcase_web/static/showcase.js`
- Test: `tests/test_showcase_web_api_admin.py`
- Test: `tests/test_showcase_web_api_public.py`

- [ ] **Step 1: Write public settings test**

```python
def test_public_settings_returns_statement_and_partners(tmp_path: Path) -> None:
    repo = SQLiteShowcaseRepository(tmp_path / "showcase.db")
    repo.initialize()
    repo.set_setting("statement_text", "自定义声明")
    repo.add_authorized_partner("星星CCD直营", "主账号", active=True)
    client = TestClient(create_showcase_app(repository=repo))

    response = client.get("/api/public/settings")

    assert response.status_code == 200
    assert response.json()["statementText"] == "自定义声明"
    assert response.json()["partners"][0]["name"] == "星星CCD直营"
```

- [ ] **Step 2: Implement public settings route**

Add `GET /api/public/settings`. Return statement, watermark text, inventory updated time, active partners.

- [ ] **Step 3: Write admin settings update test**

```python
def test_admin_can_update_statement_and_customer_password(authenticated_client, repo) -> None:
    response = authenticated_client.patch(
        "/api/admin/settings",
        json={"statementText": "新声明", "customerPassword": "week-pass"},
    )

    assert response.status_code == 200
    assert repo.get_setting("statement_text") == "新声明"
    assert repo.get_setting("customer_password_hash") != "week-pass"
```

- [ ] **Step 4: Implement settings update**

Add `PATCH /api/admin/settings`. Hash `customerPassword` before saving. Do not return password hash to frontend.

- [ ] **Step 5: Write partner CRUD test**

```python
def test_admin_can_add_update_and_delete_authorized_partner(authenticated_client, repo) -> None:
    create = authenticated_client.post("/api/admin/partners", json={"name": "A代理", "note": "允许转发"})
    partner_id = create.json()["partnerId"]

    update = authenticated_client.patch(f"/api/admin/partners/{partner_id}", json={"name": "A代理更新", "active": False})
    delete = authenticated_client.delete(f"/api/admin/partners/{partner_id}")

    assert create.status_code == 201
    assert update.status_code == 200
    assert delete.status_code == 200
```

- [ ] **Step 6: Implement partner CRUD**

Add:
- `GET /api/admin/partners`
- `POST /api/admin/partners`
- `PATCH /api/admin/partners/{partner_id}`
- `DELETE /api/admin/partners/{partner_id}`

- [ ] **Step 7: Add customer password gate**

Add `POST /api/public/access` accepting `{password}`. Verify against `customer_password_hash` and set HttpOnly cookie `showcase_customer_access` for 7 days. Public product APIs require this cookie once a customer password exists.

- [ ] **Step 8: Update customer/admin UI**

Customer page shows password gate before product list. Admin settings tab edits statement, watermark text, customer password, and authorized partners.

- [ ] **Step 9: Verify settings tests pass**

Run: `python -m pytest tests/test_showcase_web_api_public.py tests/test_showcase_web_api_admin.py -q`

Expected: PASS.

- [ ] **Step 10: Commit**

```bash
git add src/moments_inventory/showcase_web tests/test_showcase_web_api_public.py tests/test_showcase_web_api_admin.py
git commit -m "feat: manage showcase settings and access"
```

---

### Task 8: CLI Commands And Windows Bat Startup

**Files:**
- Modify: `src/moments_inventory/cli.py`
- Create: `config/showcase.yaml`
- Create: `start_showcase_server.bat`
- Create: `import_showcase_excel.bat`
- Create: `backup_showcase_db.bat`
- Test: `tests/test_cli_showcase_web.py`

- [ ] **Step 1: Write CLI parser test**

```python
from moments_inventory.cli import build_parser


def test_cli_accepts_showcase_database_commands() -> None:
    parser = build_parser()

    init_args = parser.parse_args(["showcase-db-init", "--database", "data/showcase.db"])
    import_args = parser.parse_args(["showcase-db-import", "--manual-xlsx", "manual/客户展示库存.xlsx", "--database", "data/showcase.db"])
    server_args = parser.parse_args(["showcase-server", "--database", "data/showcase.db", "--host", "127.0.0.1", "--port", "8899"])
    backup_args = parser.parse_args(["showcase-db-backup", "--database", "data/showcase.db", "--storage-dir", "storage/showcase_images", "--backup-dir", "backup/showcase"])

    assert init_args.command == "showcase-db-init"
    assert import_args.command == "showcase-db-import"
    assert server_args.command == "showcase-server"
    assert backup_args.command == "showcase-db-backup"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_cli_showcase_web.py::test_cli_accepts_showcase_database_commands -q`

Expected: FAIL because commands do not exist.

- [ ] **Step 3: Implement CLI commands**

Add:
- `showcase-db-init`
- `showcase-db-import`
- `showcase-server`
- `showcase-db-backup`

`showcase-server` runs `uvicorn.run(create_showcase_app(database_path=args.database, storage_dir=args.storage_dir), host=args.host, port=args.port)`.

- [ ] **Step 4: Create config file**

`config/showcase.yaml`:

```yaml
database_path: data/showcase.db
storage_dir: storage/showcase_images
host: 127.0.0.1
port: 8899
admin_path: /admin-xingxing
```

- [ ] **Step 5: Create startup scripts**

`start_showcase_server.bat`:

```bat
@echo off
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
  echo [ERROR] Missing .venv. Please run setup_windows.bat first.
  pause
  exit /b 1
)

".venv\Scripts\python.exe" -m moments_inventory.cli showcase-db-init --database "data/showcase.db"
start "" http://127.0.0.1:8899/admin-xingxing
".venv\Scripts\python.exe" -m moments_inventory.cli showcase-server --database "data/showcase.db" --storage-dir "storage/showcase_images" --host "127.0.0.1" --port 8899
pause
```

`import_showcase_excel.bat`:

```bat
@echo off
setlocal
cd /d "%~dp0"
".venv\Scripts\python.exe" -m moments_inventory.cli showcase-db-import --manual-xlsx "manual/客户展示库存.xlsx" --database "data/showcase.db"
pause
```

`backup_showcase_db.bat`:

```bat
@echo off
setlocal
cd /d "%~dp0"
".venv\Scripts\python.exe" -m moments_inventory.cli showcase-db-backup --database "data/showcase.db" --storage-dir "storage/showcase_images" --backup-dir "backup/showcase"
pause
```

- [ ] **Step 6: Verify CLI tests pass**

Run: `python -m pytest tests/test_cli_showcase_web.py -q`

Expected: PASS.

- [ ] **Step 7: Run full verification**

Run:

```bash
python -m pytest -q
python -m moments_inventory.cli showcase-db-init --database data/showcase.db
python -m moments_inventory.cli showcase-db-import --manual-xlsx manual/客户展示库存.xlsx --database data/showcase.db
python -m moments_inventory.cli showcase-server --database data/showcase.db --storage-dir storage/showcase_images --host 127.0.0.1 --port 8899
```

Expected:
- Tests pass.
- Database file exists.
- Import prints inserted/updated/missing counts.
- Browser can open `http://127.0.0.1:8899/`.
- Browser can open `http://127.0.0.1:8899/admin-xingxing`.

- [ ] **Step 8: Commit**

```bash
git add src/moments_inventory/cli.py config/showcase.yaml start_showcase_server.bat import_showcase_excel.bat backup_showcase_db.bat tests/test_cli_showcase_web.py
git commit -m "feat: add showcase database server commands"
```

---

## Execution Notes

- Keep the current static showcase generator working until database version is fully verified.
- Do not delete `manual/客户展示库存.xlsx`; it remains the import source during transition.
- Store generated runtime data under ignored paths: `data/`, `storage/`, and `backup/`.
- Admin is single-user only. Do not add roles or user tables in this implementation.
- Public customer pages must never show cost price, real source name, internal notes, or admin routes.
- Product card source text remains hidden; product source may exist internally for compatibility but is not displayed.

## Self-Review

- Spec coverage: database tables, Excel import, public display, hide/show, single price, batch price, admin login, product CRUD, image upload, statement, partners, password management, and bat startup are covered.
- Red-flag scan: no incomplete markers, no unscoped future tasks, no missing implementation target files.
- Type consistency: product fields use `product_id`, `display_price`, `visible`, `sold`, `cover_image_path`; API JSON uses camelCase for frontend responses.
