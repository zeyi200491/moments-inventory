# Customer Showcase Performance Sales Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the CCD customer showcase fast on phones, searchable from the server, easier to filter, and easier for customers to copy a product inquiry back to WeChat.

**Architecture:** Move public product listing from full-table API responses to SQLite-backed paginated search. Keep the existing static frontend, but make it request pages from the server and preserve list state in `sessionStorage`. Keep homepage sections manually managed through the existing database tables while upgrading the customer-facing layout.

**Tech Stack:** Python 3.13, FastAPI, SQLite, pytest, vanilla HTML/CSS/JavaScript, Playwright CLI for browser verification.

---

## Files And Responsibilities

- Modify `src/moments_inventory/showcase_web/models.py`
  - Add small dataclasses for product search criteria and search result.
- Modify `src/moments_inventory/showcase_web/repository.py`
  - Add indexed public search queries.
  - Add brand metadata query.
  - Add sales tag normalization and automatic tag matching helpers.
- Modify `src/moments_inventory/showcase_web/api.py`
  - Change `/api/public/products` to accept query parameters and return pagination metadata.
  - Add `/api/public/filters`.
  - Ensure public section products include merged sales tags.
- Modify `src/moments_inventory/showcase_web/static/index.html`
  - Add tag quick filters and price preset buttons.
- Modify `src/moments_inventory/showcase_web/static/product.html`
  - Add a stronger detail-page inquiry copy action.
- Modify `src/moments_inventory/showcase_web/static/showcase.js`
  - Replace client-side full-list filtering with server-side paginated loading.
  - Add inquiry copy behavior.
  - Save and restore customer list state.
- Modify `src/moments_inventory/showcase_web/static/showcase.css`
  - Style quick filters, inquiry buttons, loading states, and stronger homepage sections.
- Modify `tests/test_showcase_web_repository.py`
  - Cover repository pagination, search, price, brand, and tag filtering.
- Modify `tests/test_showcase_web_api_public.py`
  - Cover public product pagination and filter metadata.

---

### Task 1: Repository Search Models And Indexes

**Files:**
- Modify: `src/moments_inventory/showcase_web/models.py`
- Modify: `src/moments_inventory/showcase_web/repository.py`
- Test: `tests/test_showcase_web_repository.py`

- [ ] **Step 1: Write failing repository pagination test**

Add this test to `tests/test_showcase_web_repository.py`:

```python
def test_repository_search_products_returns_paginated_public_products(tmp_path: Path) -> None:
    repo = SQLiteShowcaseRepository(tmp_path / "showcase.db")
    for index in range(5):
        product = _product(f"p{index}", 300 + index)
        product.published_at = f"2026-08-10T10:0{index}:00+08:00"
        repo.upsert_product(product)
    hidden = _product("hidden", 399)
    hidden.visible = False
    sold = _product("sold", 399)
    sold.sold = True
    repo.upsert_product(hidden)
    repo.upsert_product(sold)

    result = repo.search_products(limit=2, offset=1)

    assert result.total == 5
    assert result.limit == 2
    assert result.offset == 1
    assert result.has_more is True
    assert [product.product_id for product in result.products] == ["p3", "p2"]
```

- [ ] **Step 2: Run test and verify it fails**

Run:

```powershell
pytest tests/test_showcase_web_repository.py::test_repository_search_products_returns_paginated_public_products -q
```

Expected: FAIL because `SQLiteShowcaseRepository.search_products` does not exist.

- [ ] **Step 3: Add search dataclasses**

In `src/moments_inventory/showcase_web/models.py`, add:

```python
@dataclass(frozen=True)
class ShowcaseProductSearch:
    query: str = ""
    brand: str = ""
    price_min: int | None = None
    price_max: int | None = None
    tags: tuple[str, ...] = ()
    limit: int = 80
    offset: int = 0


@dataclass(frozen=True)
class ShowcaseProductSearchResult:
    products: list[ShowcaseProduct]
    total: int
    limit: int
    offset: int

    @property
    def has_more(self) -> bool:
        return self.offset + len(self.products) < self.total
```

- [ ] **Step 4: Add indexes during repository initialization**

In `SQLiteShowcaseRepository.initialize`, after product table creation, add:

```python
conn.execute(
    """
    create index if not exists idx_showcase_products_public
    on showcase_products(visible, sold, published_at)
    """
)
conn.execute(
    """
    create index if not exists idx_showcase_products_brand_price
    on showcase_products(brand, display_price)
    """
)
```

- [ ] **Step 5: Implement minimal `search_products`**

Import the new dataclasses in `repository.py`, then add:

```python
def search_products(
    self,
    search: ShowcaseProductSearch | None = None,
) -> ShowcaseProductSearchResult:
    search = search or ShowcaseProductSearch()
    limit = min(max(search.limit, 1), 120)
    offset = max(search.offset, 0)
    where = ["visible = 1", "sold = 0"]
    params: list[object] = []
    with self._connect() as conn:
        total = int(
            conn.execute(
                f"select count(*) from showcase_products where {' and '.join(where)}",
                params,
            ).fetchone()[0]
        )
        rows = conn.execute(
            f"""
            select product_id, model, brand, cost_price, display_price, visible, sold,
                   published_at, raw_copy, display_copy, cover_image_path, created_at,
                   updated_at, last_seen_import_id, short_selling_point, recommend_tags
            from showcase_products
            where {' and '.join(where)}
            order by published_at desc, created_at desc
            limit ? offset ?
            """,
            [*params, limit, offset],
        ).fetchall()
    return ShowcaseProductSearchResult(
        products=[_product_from_row(row) for row in rows],
        total=total,
        limit=limit,
        offset=offset,
    )
```

- [ ] **Step 6: Run test and verify it passes**

Run:

```powershell
pytest tests/test_showcase_web_repository.py::test_repository_search_products_returns_paginated_public_products -q
```

Expected: PASS.

---

### Task 2: Repository Search Filters

**Files:**
- Modify: `src/moments_inventory/showcase_web/repository.py`
- Test: `tests/test_showcase_web_repository.py`

- [ ] **Step 1: Write failing brand, price, and query tests**

Add:

```python
def test_repository_search_products_filters_by_brand_price_and_query(tmp_path: Path) -> None:
    repo = SQLiteShowcaseRepository(tmp_path / "showcase.db")
    canon = _product("canon", 558)
    canon.brand = "佳能"
    canon.model = "佳能ixus80"
    canon.display_copy = "冷白皮 操作简单"
    sony = _product("sony", 899)
    sony.brand = "索尼"
    sony.model = "索尼t77"
    sony.display_copy = "超薄 氛围感"
    repo.upsert_product(canon)
    repo.upsert_product(sony)

    result = repo.search_products(
        ShowcaseProductSearch(query="冷白皮", brand="佳能", price_min=500, price_max=600)
    )

    assert result.total == 1
    assert result.products[0].product_id == "canon"
```

- [ ] **Step 2: Run test and verify it fails**

Run:

```powershell
pytest tests/test_showcase_web_repository.py::test_repository_search_products_filters_by_brand_price_and_query -q
```

Expected: FAIL because `search_products` ignores filters.

- [ ] **Step 3: Add filter SQL builder**

In `repository.py`, add a private helper:

```python
def _build_public_product_filters(search: ShowcaseProductSearch) -> tuple[list[str], list[object]]:
    where = ["visible = 1", "sold = 0"]
    params: list[object] = []
    if search.brand:
        where.append("brand = ?")
        params.append(search.brand)
    if search.price_min is not None:
        where.append("display_price >= ?")
        params.append(search.price_min)
    if search.price_max is not None:
        where.append("display_price <= ?")
        params.append(search.price_max)
    if search.query.strip():
        like = f"%{search.query.strip()}%"
        where.append(
            """
            (
              model like ?
              or brand like ?
              or raw_copy like ?
              or display_copy like ?
              or short_selling_point like ?
              or recommend_tags like ?
            )
            """
        )
        params.extend([like, like, like, like, like, like])
    return where, params
```

- [ ] **Step 4: Use filter SQL in `search_products`**

Change the method to call:

```python
where, params = _build_public_product_filters(search)
```

Use the same `where` and `params` in both count query and page query.

- [ ] **Step 5: Run filter test**

Run:

```powershell
pytest tests/test_showcase_web_repository.py::test_repository_search_products_filters_by_brand_price_and_query -q
```

Expected: PASS.

---

### Task 3: Sales Tag Rules And Filter Metadata

**Files:**
- Modify: `src/moments_inventory/showcase_web/repository.py`
- Modify: `src/moments_inventory/showcase_web/api.py`
- Test: `tests/test_showcase_web_repository.py`
- Test: `tests/test_showcase_web_api_public.py`

- [ ] **Step 1: Write failing auto-tag repository test**

Add:

```python
def test_repository_search_products_filters_by_manual_and_auto_sales_tags(tmp_path: Path) -> None:
    repo = SQLiteShowcaseRepository(tmp_path / "showcase.db")
    manual = _product("manual", 500)
    manual.recommend_tags = "新手推荐"
    auto = _product("auto", 600)
    auto.display_copy = "30倍光学变焦 演唱会 长焦"
    miss = _product("miss", 700)
    miss.display_copy = "普通复古小相机"
    repo.upsert_product(manual)
    repo.upsert_product(auto)
    repo.upsert_product(miss)

    manual_result = repo.search_products(ShowcaseProductSearch(tags=("新手推荐",)))
    auto_result = repo.search_products(ShowcaseProductSearch(tags=("长焦",)))

    assert [product.product_id for product in manual_result.products] == ["manual"]
    assert [product.product_id for product in auto_result.products] == ["auto"]
```

- [ ] **Step 2: Run tag test and verify it fails**

Run:

```powershell
pytest tests/test_showcase_web_repository.py::test_repository_search_products_filters_by_manual_and_auto_sales_tags -q
```

Expected: FAIL because tag filtering does not exist.

- [ ] **Step 3: Add sales tag constants and helpers**

In `repository.py`, add:

```python
SALES_TAG_RULES: dict[str, tuple[str, ...]] = {
    "新手推荐": ("新手", "操作简单", "闭眼入", "好上手"),
    "礼盒装": ("礼盒", "精品礼盒", "送礼"),
    "长焦": ("长焦", "10倍", "12倍", "20倍", "25倍", "30倍", "演唱会"),
    "自拍": ("自拍", "翻转屏"),
    "小巧": ("小巧", "便携", "超薄", "口袋"),
    "冷白皮": ("冷白皮", "冷白"),
    "氛围感": ("氛围感", "胶片感", "复古"),
}


def list_sales_tags() -> list[str]:
    return list(SALES_TAG_RULES.keys())


def product_sales_tags(product: ShowcaseProduct) -> list[str]:
    raw_text = " ".join(
        [
            product.model,
            product.brand,
            product.raw_copy,
            product.display_copy,
            product.short_selling_point,
            product.recommend_tags,
        ]
    )
    tags: list[str] = []
    seen: set[str] = set()
    for raw_tag in product.recommend_tags.split(","):
        tag = raw_tag.strip()
        if tag and tag not in seen:
            seen.add(tag)
            tags.append(tag)
    for tag, keywords in SALES_TAG_RULES.items():
        if tag in seen:
            continue
        if any(keyword in raw_text for keyword in keywords):
            seen.add(tag)
            tags.append(tag)
    return tags
```

- [ ] **Step 4: Apply tag filter after SQL page candidate expansion**

Because auto tags depend on text rules, implement tag filtering by querying candidate rows first:

```python
if search.tags:
    candidate_limit = max(limit + offset, 300)
    rows = conn.execute(page_sql, [*params, candidate_limit, 0]).fetchall()
    matched = [
        _product_from_row(row)
        for row in rows
        if all(tag in product_sales_tags(_product_from_row(row)) for tag in search.tags)
    ]
    total = len(matched)
    products = matched[offset : offset + limit]
    return ShowcaseProductSearchResult(products=products, total=total, limit=limit, offset=offset)
```

Use normal SQL count and limit path when `search.tags` is empty.

- [ ] **Step 5: Run tag test**

Run:

```powershell
pytest tests/test_showcase_web_repository.py::test_repository_search_products_filters_by_manual_and_auto_sales_tags -q
```

Expected: PASS.

- [ ] **Step 6: Write failing filter metadata API test**

Add to `tests/test_showcase_web_api_public.py`:

```python
def test_public_filters_api_returns_brands_tags_and_price_presets(tmp_path: Path) -> None:
    repo = SQLiteShowcaseRepository(tmp_path / "showcase.db")
    repo.initialize()
    canon = _product("canon", visible=True, display_price=558)
    canon.brand = "佳能"
    sony = _product("sony", visible=True, display_price=688)
    sony.brand = "索尼"
    repo.upsert_product(canon)
    repo.upsert_product(sony)
    client = TestClient(create_showcase_app(repository=repo))

    response = client.get("/api/public/filters")

    assert response.status_code == 200
    data = response.json()
    assert data["brands"] == ["佳能", "索尼"]
    assert "新手推荐" in data["tags"]
    assert {"label": "500以内", "priceMin": 0, "priceMax": 500} in data["pricePresets"]
```

- [ ] **Step 7: Implement metadata methods and API**

Add repository method:

```python
def list_public_brands(self) -> list[str]:
    with self._connect() as conn:
        rows = conn.execute(
            """
            select distinct brand
            from showcase_products
            where visible = 1 and sold = 0 and brand != ''
            order by brand
            """
        ).fetchall()
    return [str(row[0]) for row in rows]
```

Add API models:

```python
class PublicPricePresetResponse(BaseModel):
    label: str
    priceMin: int
    priceMax: int


class PublicFiltersResponse(BaseModel):
    brands: list[str]
    tags: list[str]
    pricePresets: list[PublicPricePresetResponse]
```

Add route:

```python
@router.get("/filters", response_model=PublicFiltersResponse)
def list_public_filters(repo: SQLiteShowcaseRepository = Depends(get_repository)) -> PublicFiltersResponse:
    return PublicFiltersResponse(
        brands=repo.list_public_brands(),
        tags=list_sales_tags(),
        pricePresets=[
            PublicPricePresetResponse(label="500以内", priceMin=0, priceMax=500),
            PublicPricePresetResponse(label="800以内", priceMin=0, priceMax=800),
            PublicPricePresetResponse(label="千元热门", priceMin=800, priceMax=1200),
            PublicPricePresetResponse(label="300-500 推荐", priceMin=300, priceMax=500),
        ],
    )
```

- [ ] **Step 8: Run metadata test**

Run:

```powershell
pytest tests/test_showcase_web_api_public.py::test_public_filters_api_returns_brands_tags_and_price_presets -q
```

Expected: PASS.

---

### Task 4: Public Products API Pagination

**Files:**
- Modify: `src/moments_inventory/showcase_web/api.py`
- Test: `tests/test_showcase_web_api_public.py`

- [ ] **Step 1: Write failing public pagination API test**

Add:

```python
def test_public_products_api_supports_pagination_and_filters(tmp_path: Path) -> None:
    repo = SQLiteShowcaseRepository(tmp_path / "showcase.db")
    repo.initialize()
    for index, brand in enumerate(["佳能", "佳能", "索尼"], start=1):
        product = _product(f"p{index}", visible=True, display_price=300 + index * 100)
        product.brand = brand
        product.display_copy = "冷白皮 推荐"
        product.published_at = f"2026-08-10T10:0{index}:00+08:00"
        repo.upsert_product(product)
    client = TestClient(create_showcase_app(repository=repo))

    response = client.get(
        "/api/public/products",
        params={
            "brand": "佳能",
            "priceMin": 300,
            "priceMax": 600,
            "query": "冷白皮",
            "limit": 1,
            "offset": 0,
        },
    )

    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 2
    assert data["limit"] == 1
    assert data["offset"] == 0
    assert data["hasMore"] is True
    assert len(data["products"]) == 1
```

- [ ] **Step 2: Run API test and verify it fails**

Run:

```powershell
pytest tests/test_showcase_web_api_public.py::test_public_products_api_supports_pagination_and_filters -q
```

Expected: FAIL because response model does not include pagination metadata.

- [ ] **Step 3: Update response model**

Change `PublicProductsResponse`:

```python
class PublicProductsResponse(BaseModel):
    products: list[PublicProductResponse] = Field(default_factory=list)
    total: int
    limit: int
    offset: int
    hasMore: bool
```

- [ ] **Step 4: Update route query parameters**

Change `list_public_products` signature:

```python
def list_public_products(
    query: str = "",
    brand: str = "",
    priceMin: int | None = None,
    priceMax: int | None = None,
    tags: str = "",
    limit: int = 80,
    offset: int = 0,
    repo: SQLiteShowcaseRepository = Depends(get_repository),
) -> PublicProductsResponse:
```

Inside route:

```python
search = ShowcaseProductSearch(
    query=query.strip(),
    brand=brand.strip(),
    price_min=priceMin,
    price_max=priceMax,
    tags=tuple(tag.strip() for tag in tags.split(",") if tag.strip()),
    limit=limit,
    offset=offset,
)
result = repo.search_products(search)
sample_cover_paths = repo.list_first_image_paths_by_type("sample")
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
)
```

- [ ] **Step 5: Run public API tests**

Run:

```powershell
pytest tests/test_showcase_web_api_public.py -q
```

Expected: PASS after updating older public product tests to assert `products` and ignore or assert pagination fields.

---

### Task 5: Customer List Uses Server Pagination

**Files:**
- Modify: `src/moments_inventory/showcase_web/static/index.html`
- Modify: `src/moments_inventory/showcase_web/static/showcase.js`
- Modify: `src/moments_inventory/showcase_web/static/showcase.css`

- [ ] **Step 1: Add filter controls to HTML**

In `index.html`, below the existing price filter, add:

```html
<section class="quick-filter-panel" aria-label="快速筛选">
  <div id="tagFilterButtons" class="quick-filter-row"></div>
  <div id="pricePresetButtons" class="quick-filter-row"></div>
</section>
```

- [ ] **Step 2: Replace list state in JS**

In `showcase.js`, replace `state.products`, `state.visibleCount`, and client-side filtering fields with:

```javascript
const PRODUCT_PAGE_SIZE = 80;

const state = {
  products: [],
  total: 0,
  hasMore: false,
  loading: false,
  query: "",
  brand: "",
  priceMin: null,
  priceMax: null,
  tags: new Set(),
  filters: {
    brands: [],
    tags: [],
    pricePresets: [],
  },
  sections: [],
  settings: {
    statementText: "",
    watermarkText: "星星CCD",
    inventoryUpdatedAt: "",
    partners: [],
  },
};
```

- [ ] **Step 3: Add query string builder**

Add:

```javascript
function buildProductQuery(offset) {
  const params = new URLSearchParams();
  params.set("limit", String(PRODUCT_PAGE_SIZE));
  params.set("offset", String(offset));
  if (state.query) params.set("query", state.query);
  if (state.brand) params.set("brand", state.brand);
  if (state.priceMin !== null) params.set("priceMin", String(state.priceMin));
  if (state.priceMax !== null) params.set("priceMax", String(state.priceMax));
  if (state.tags.size) params.set("tags", [...state.tags].join(","));
  return params.toString();
}
```

- [ ] **Step 4: Add server page loader**

Replace `loadInventory` product loading with:

```javascript
async function loadProductPage({ reset = false } = {}) {
  if (state.loading) return;
  state.loading = true;
  const offset = reset ? 0 : state.products.length;
  const response = await fetch(`/api/public/products?${buildProductQuery(offset)}`);
  if (response.status === 401) {
    state.loading = false;
    showAccessPanel(loadInventory);
    return;
  }
  if (!response.ok) {
    state.loading = false;
    return;
  }
  const data = await response.json();
  state.products = reset
    ? Array.isArray(data.products) ? data.products : []
    : [...state.products, ...(Array.isArray(data.products) ? data.products : [])];
  state.total = Number(data.total || 0);
  state.hasMore = Boolean(data.hasMore);
  state.loading = false;
  renderList();
}
```

- [ ] **Step 5: Update render count and load more**

Change `renderList`:

```javascript
function renderList() {
  const productGrid = document.getElementById("productGrid");
  const emptyState = document.getElementById("emptyState");
  const resultCount = document.getElementById("resultCount");
  const loadMoreButton = document.getElementById("loadMoreButton");
  if (!productGrid || !emptyState || !resultCount) return;
  resultCount.textContent = state.products.length === state.total
    ? `${state.total} 台`
    : `${state.products.length} / ${state.total} 台`;
  productGrid.innerHTML = state.products.map(renderProductCard).join("");
  emptyState.hidden = state.products.length !== 0;
  if (loadMoreButton) {
    loadMoreButton.hidden = !state.hasMore;
    loadMoreButton.textContent = state.loading ? "加载中" : "显示更多";
  }
}
```

Change load more click:

```javascript
document.getElementById("loadMoreButton")?.addEventListener("click", () => {
  loadProductPage({ reset: false });
});
```

- [ ] **Step 6: Load filter metadata**

Add:

```javascript
async function loadFilters() {
  const response = await fetch("/api/public/filters");
  if (!response.ok) return;
  state.filters = await response.json();
  renderBrands();
  renderQuickFilters();
}
```

Update `renderBrands` to use `state.filters.brands` instead of `state.products`.

- [ ] **Step 7: Render quick filters**

Add:

```javascript
function renderQuickFilters() {
  const tagTarget = document.getElementById("tagFilterButtons");
  const priceTarget = document.getElementById("pricePresetButtons");
  if (tagTarget) {
    tagTarget.innerHTML = (state.filters.tags || []).map((tag) => `
      <button class="quick-filter-button ${state.tags.has(tag) ? "active" : ""}" type="button" data-tag="${escapeHtml(tag)}">${escapeHtml(tag)}</button>
    `).join("");
  }
  if (priceTarget) {
    priceTarget.innerHTML = (state.filters.pricePresets || []).map((preset) => `
      <button class="quick-filter-button" type="button" data-price-min="${preset.priceMin}" data-price-max="${preset.priceMax}">${escapeHtml(preset.label)}</button>
    `).join("");
  }
}
```

- [ ] **Step 8: Bind quick filters**

Add document click handling:

```javascript
document.addEventListener("click", (event) => {
  const tagButton = event.target.closest("[data-tag]");
  if (tagButton) {
    const tag = tagButton.dataset.tag;
    if (state.tags.has(tag)) state.tags.delete(tag);
    else state.tags.add(tag);
    renderQuickFilters();
    loadProductPage({ reset: true });
    return;
  }
  const priceButton = event.target.closest("[data-price-min]");
  if (priceButton) {
    state.priceMin = Number(priceButton.dataset.priceMin);
    state.priceMax = Number(priceButton.dataset.priceMax);
    document.getElementById("priceFilter").value = `${state.priceMin}-${state.priceMax}`;
    loadProductPage({ reset: true });
  }
});
```

- [ ] **Step 9: Add CSS**

Add:

```css
.quick-filter-panel {
  display: grid;
  gap: 8px;
  margin: -4px 0 14px;
}

.quick-filter-row {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.quick-filter-button {
  min-height: 34px;
  padding: 0 10px;
  border: 1px solid var(--line);
  background: rgba(255, 255, 255, 0.88);
  color: var(--ink);
  font-weight: 900;
  cursor: pointer;
}

.quick-filter-button.active {
  border-color: var(--pine);
  background: var(--pine);
  color: #fff;
}
```

- [ ] **Step 10: Run frontend syntax checks**

Run:

```powershell
node --check src/moments_inventory/showcase_web/static/showcase.js
```

Expected: exit code 0.

---

### Task 6: Copy Inquiry Text

**Files:**
- Modify: `src/moments_inventory/showcase_web/static/showcase.js`
- Modify: `src/moments_inventory/showcase_web/static/showcase.css`

- [ ] **Step 1: Add inquiry text builder**

Add:

```javascript
function buildInquiryText(product) {
  const url = `${window.location.origin}/product?id=${encodeURIComponent(product.productId)}`;
  return [
    "我想咨询这台 CCD：",
    "",
    `型号：${product.model || ""}`,
    `品牌：${product.brand || ""}`,
    `价格：${product.displayPrice || 0} 元`,
    "",
    "完整文案：",
    product.displayCopy || "",
    "",
    "商品链接：",
    url,
  ].join("\n");
}
```

- [ ] **Step 2: Add copy helper with fallback**

Add:

```javascript
async function copyText(text) {
  if (navigator.clipboard && window.isSecureContext) {
    await navigator.clipboard.writeText(text);
    return true;
  }
  const textarea = document.createElement("textarea");
  textarea.value = text;
  textarea.setAttribute("readonly", "readonly");
  textarea.className = "copy-fallback-textarea";
  document.body.appendChild(textarea);
  textarea.select();
  const copied = document.execCommand("copy");
  textarea.remove();
  return copied;
}
```

- [ ] **Step 3: Add button to product card**

In `renderProductCard`, inside `.product-content`, add:

```html
<button class="copy-inquiry-button" type="button" data-product-id="${escapeHtml(product.productId)}">复制咨询文案（点一下复制这台完整文案，回微信发给我）</button>
```

- [ ] **Step 4: Add button to detail hero**

In `renderDetail`, add under price or selling point:

```html
<button class="copy-inquiry-button detail-copy-button" type="button" data-product-id="${escapeHtml(product.productId)}">复制咨询文案（点一下复制这台完整文案，回微信发给我）</button>
```

- [ ] **Step 5: Store detail product for copy**

Add:

```javascript
state.currentDetailProduct = null;
```

In `renderDetail(product)` set:

```javascript
state.currentDetailProduct = product;
```

- [ ] **Step 6: Handle copy click**

Add to document click handler before image preview logic:

```javascript
const copyButton = event.target.closest(".copy-inquiry-button");
if (copyButton) {
  event.preventDefault();
  event.stopPropagation();
  const productId = copyButton.dataset.productId;
  const product = state.products.find((item) => item.productId === productId)
    || state.currentDetailProduct;
  if (!product) return;
  const copied = await copyText(buildInquiryText(product));
  copyButton.textContent = copied ? "已复制" : "请长按手动复制";
  window.setTimeout(() => {
    copyButton.textContent = "复制咨询文案（点一下复制这台完整文案，回微信发给我）";
  }, 1600);
  return;
}
```

Because this handler uses `await`, make the document click callback `async`.

- [ ] **Step 7: Add CSS**

Add:

```css
.copy-inquiry-button {
  width: 100%;
  min-height: 38px;
  margin-top: 10px;
  border: 1px solid var(--pine);
  background: rgba(255, 255, 255, 0.92);
  color: var(--pine);
  font-size: 13px;
  font-weight: 900;
  cursor: pointer;
}

.detail-copy-button {
  width: min(420px, 100%);
}

.copy-fallback-textarea {
  position: fixed;
  left: 12px;
  bottom: 12px;
  z-index: 80;
  width: calc(100vw - 24px);
  min-height: 180px;
}
```

- [ ] **Step 8: Run syntax check**

Run:

```powershell
node --check src/moments_inventory/showcase_web/static/showcase.js
```

Expected: exit code 0.

---

### Task 7: Restore List State After Detail Page

**Files:**
- Modify: `src/moments_inventory/showcase_web/static/showcase.js`

- [ ] **Step 1: Add state storage helpers**

Add:

```javascript
const LIST_STATE_KEY = "xingxing-showcase-list-state";

function saveListState(productId = "") {
  const snapshot = {
    query: state.query,
    brand: state.brand,
    priceMin: state.priceMin,
    priceMax: state.priceMax,
    tags: [...state.tags],
    loadedCount: state.products.length,
    scrollY: window.scrollY,
    selectedProductId: productId,
  };
  sessionStorage.setItem(LIST_STATE_KEY, JSON.stringify(snapshot));
}

function readListState() {
  try {
    const raw = sessionStorage.getItem(LIST_STATE_KEY);
    return raw ? JSON.parse(raw) : null;
  } catch {
    return null;
  }
}
```

- [ ] **Step 2: Save before product navigation**

In `renderProductCard`, add `data-product-link="true"` to the `<a>` element:

```html
<a class="product-card" data-product-link="true" href="/product?id=${encodeURIComponent(product.productId)}">
```

In document click handler:

```javascript
const productLink = event.target.closest("[data-product-link]");
if (productLink && !event.target.closest(".copy-inquiry-button")) {
  const productId = new URL(productLink.href).searchParams.get("id") || "";
  saveListState(productId);
}
```

- [ ] **Step 3: Restore filters and loaded count**

Add:

```javascript
async function restoreListStateIfAvailable() {
  const saved = readListState();
  if (!saved) return false;
  state.query = String(saved.query || "");
  state.brand = String(saved.brand || "");
  state.priceMin = saved.priceMin === null ? null : Number(saved.priceMin);
  state.priceMax = saved.priceMax === null ? null : Number(saved.priceMax);
  state.tags = new Set(Array.isArray(saved.tags) ? saved.tags : []);
  document.getElementById("searchInput").value = state.query;
  document.getElementById("brandFilter").value = state.brand;
  if (state.priceMin !== null && state.priceMax !== null) {
    document.getElementById("priceFilter").value = `${state.priceMin}-${state.priceMax}`;
  }
  renderQuickFilters();
  const targetCount = Math.max(PRODUCT_PAGE_SIZE, Number(saved.loadedCount || PRODUCT_PAGE_SIZE));
  while (state.products.length < targetCount) {
    await loadProductPage({ reset: state.products.length === 0 });
    if (!state.hasMore) break;
  }
  window.setTimeout(() => window.scrollTo(0, Number(saved.scrollY || 0)), 50);
  return true;
}
```

- [ ] **Step 4: Use restore in list initialization**

In `initListPage`, after `loadFilters()` and `renderStatement()`:

```javascript
const restored = await restoreListStateIfAvailable();
if (!restored) {
  await loadProductPage({ reset: true });
}
```

- [ ] **Step 5: Detail back button behavior**

If `product.html` has a back link, ensure it keeps normal browser behavior. If the link is a plain `/`, add in JS:

```javascript
document.querySelector("[data-back-to-list]")?.addEventListener("click", (event) => {
  if (window.history.length > 1) {
    event.preventDefault();
    window.history.back();
  }
});
```

- [ ] **Step 6: Run syntax check**

Run:

```powershell
node --check src/moments_inventory/showcase_web/static/showcase.js
```

Expected: exit code 0.

---

### Task 8: Homepage Featured Sections Visual Upgrade

**Files:**
- Modify: `src/moments_inventory/showcase_web/static/showcase.js`
- Modify: `src/moments_inventory/showcase_web/static/showcase.css`

- [ ] **Step 1: Update featured section rendering**

Change `renderFeaturedSections` so the first section renders as a lead showcase:

```javascript
function renderFeaturedSections() {
  const target = document.getElementById("featuredSections");
  if (!target) return;
  const sections = Array.isArray(state.sections) ? state.sections : [];
  target.innerHTML = sections.length
    ? sections.map((section, index) => {
        const products = Array.isArray(section.products) ? section.products.slice(0, index === 0 ? 6 : 8) : [];
        return `<section class="featured-section ${index === 0 ? "featured-section-lead" : "featured-section-compact"}">
          <div class="section-heading">
            <div>
              <p class="eyebrow">${index === 0 ? "Today Pick" : "Selection"}</p>
              <h2>${escapeHtml(section.title)}</h2>
              ${section.subtitle ? `<p>${escapeHtml(section.subtitle)}</p>` : ""}
            </div>
            <span>${products.length} 台</span>
          </div>
          <div class="${index === 0 ? "featured-lead-grid" : "featured-scroll-row"}">
            ${products.map(renderProductCard).join("")}
          </div>
        </section>`;
      }).join("")
    : "";
}
```

- [ ] **Step 2: Add featured CSS**

Add:

```css
.featured-section-lead {
  border-color: rgba(42, 90, 72, 0.28);
  background: rgba(250, 252, 247, 0.94);
}

.featured-lead-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(230px, 1fr));
  gap: 14px;
}

.featured-scroll-row {
  display: grid;
  grid-auto-flow: column;
  grid-auto-columns: minmax(220px, 260px);
  gap: 12px;
  overflow-x: auto;
  padding-bottom: 6px;
  scroll-snap-type: x proximity;
}

.featured-scroll-row .product-card {
  scroll-snap-align: start;
}

@media (max-width: 760px) {
  .featured-lead-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .featured-scroll-row {
    grid-auto-columns: minmax(170px, 72vw);
  }
}
```

- [ ] **Step 3: Ensure default section names in current database**

Run a one-off local database update after code changes:

```powershell
$env:PYTHONPATH = (Join-Path (Get-Location) 'src')
@'
from pathlib import Path
from datetime import datetime, timezone
from moments_inventory.showcase_web.models import ShowcaseSection
from moments_inventory.showcase_web.repository import SQLiteShowcaseRepository

repo = SQLiteShowcaseRepository(Path("data/showcase.db"))
repo.initialize()
now = datetime.now(timezone.utc).isoformat()
sections = [
    ("today-pick", "今日主推", "今天最值得先看的主推款", 1),
    ("budget-300-500", "预算 300-500 推荐", "预算友好、适合快速下单的 CCD", 2),
    ("beginner-picks", "新手闭眼入", "操作简单、出片稳定、适合第一次买 CCD", 3),
    ("gift-box", "礼盒装专区", "适合送礼、成套搭配、客户第一眼能看懂的主推款", 4),
    ("new-arrivals", "最近上新", "近期新增和适合重点推的活动款", 5),
]
for section_id, title, subtitle, sort_order in sections:
    existing = repo.get_section(section_id)
    repo.upsert_section(ShowcaseSection(
        section_id=section_id,
        title=title,
        subtitle=subtitle,
        active=True if existing is None else existing.active,
        sort_order=sort_order,
        created_at=now if existing is None else existing.created_at,
        updated_at=now,
    ))
'@ | python -
```

- [ ] **Step 4: Run syntax check**

Run:

```powershell
node --check src/moments_inventory/showcase_web/static/showcase.js
```

Expected: exit code 0.

---

### Task 9: End-To-End Verification

**Files:**
- Verify all modified files.

- [ ] **Step 1: Run Python tests**

Run:

```powershell
pytest tests/test_showcase_web_repository.py tests/test_showcase_web_importer.py tests/test_showcase_web_api_public.py tests/test_showcase_web_auth.py tests/test_showcase_web_api_admin.py tests/test_cli_showcase_web.py tests/test_showcase_web_sample_images.py -q
```

Expected: all tests pass.

- [ ] **Step 2: Run Python compile check**

Run:

```powershell
python -m compileall -q src/moments_inventory/showcase_web src/moments_inventory/cli.py
```

Expected: exit code 0.

- [ ] **Step 3: Run JS syntax checks**

Run:

```powershell
node --check src/moments_inventory/showcase_web/static/admin.js
node --check src/moments_inventory/showcase_web/static/showcase.js
```

Expected: both commands exit 0.

- [ ] **Step 4: Restart local server**

Run:

```powershell
Get-NetTCPConnection -LocalPort 8899 -ErrorAction SilentlyContinue | ForEach-Object { Stop-Process -Id $_.OwningProcess -Force }
Start-Sleep -Seconds 1
$env:PYTHONPATH = (Join-Path (Get-Location) 'src')
$sampleDir = 'E:\Ai jjfajgsw\AIkefu\output\ccdcpt'
$argumentLine = '-m moments_inventory.cli showcase-server --database "data/showcase.db" --storage-dir "storage/showcase_images" --sample-images-dir "' + $sampleDir + '" --host 127.0.0.1 --port 8899'
Start-Process -FilePath 'python' -ArgumentList $argumentLine -WorkingDirectory (Get-Location) -WindowStyle Hidden -RedirectStandardOutput 'showcase_server.out.log' -RedirectStandardError 'showcase_server.err.log'
Start-Sleep -Seconds 2
Get-NetTCPConnection -LocalPort 8899 -ErrorAction SilentlyContinue | Select-Object -Property OwningProcess,State,LocalAddress,LocalPort
```

Expected: `127.0.0.1:8899` is in `Listen` state.

- [ ] **Step 5: Verify public API pagination manually**

Run:

```powershell
$session = New-Object Microsoft.PowerShell.Commands.WebRequestSession
Invoke-WebRequest -UseBasicParsing -Uri http://127.0.0.1:8899/api/public/access -Method POST -Body '{"password":"xxccd0810"}' -ContentType 'application/json' -WebSession $session
$response = Invoke-WebRequest -UseBasicParsing -Uri 'http://127.0.0.1:8899/api/public/products?limit=80&offset=0&brand=三星' -WebSession $session
$response.Content.Substring(0, [Math]::Min(500, $response.Content.Length))
```

Expected: JSON contains `products`, `total`, `limit`, `offset`, and `hasMore`.

- [ ] **Step 6: Verify browser customer flow**

Run Playwright CLI:

```powershell
npx.cmd --yes --package @playwright/cli playwright-cli -s=ccd-performance delete-data
npx.cmd --yes --package @playwright/cli playwright-cli -s=ccd-performance open http://127.0.0.1:8899/
npx.cmd --yes --package @playwright/cli playwright-cli -s=ccd-performance snapshot
npx.cmd --yes --package @playwright/cli playwright-cli -s=ccd-performance fill e10 xxccd0810
npx.cmd --yes --package @playwright/cli playwright-cli -s=ccd-performance click e11
npx.cmd --yes --package @playwright/cli playwright-cli -s=ccd-performance find "80 /"
npx.cmd --yes --package @playwright/cli playwright-cli -s=ccd-performance find "复制咨询文案"
```

Expected: customer page loads, count is paginated, and copy buttons are visible.

- [ ] **Step 7: Verify detail return behavior**

Use Playwright snapshot refs from the latest page:

```powershell
npx.cmd --yes --package @playwright/cli playwright-cli -s=ccd-performance click e38
npx.cmd --yes --package @playwright/cli playwright-cli -s=ccd-performance find "商品文案"
npx.cmd --yes --package @playwright/cli playwright-cli -s=ccd-performance go-back
npx.cmd --yes --package @playwright/cli playwright-cli -s=ccd-performance find "80 /"
```

Expected: detail page opens, back returns to list, and list state is restored.

- [ ] **Step 8: Commit implementation**

After all checks pass:

```powershell
git status --short
git add src/moments_inventory/showcase_web/models.py src/moments_inventory/showcase_web/repository.py src/moments_inventory/showcase_web/api.py src/moments_inventory/showcase_web/static/index.html src/moments_inventory/showcase_web/static/product.html src/moments_inventory/showcase_web/static/showcase.js src/moments_inventory/showcase_web/static/showcase.css tests/test_showcase_web_repository.py tests/test_showcase_web_api_public.py
git commit -m "feat: optimize customer showcase browsing"
```

Expected: commit succeeds after implementation files are staged.
