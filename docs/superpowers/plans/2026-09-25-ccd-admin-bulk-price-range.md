# CCD 管理后台价格段批量改价实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在 CCD 商品管理中交付一个范围清楚、支持五个价格段与自定义区间、可安全预览和撤销的批量改价工作台。

**Architecture:** 继续使用现有 FastAPI、SQLite 快照和原生 HTML/JavaScript，不新增数据库表。前端显式提交作用范围、价格区间、状态条件和改价方式；后端负责最终校验、计算预览统计、保存完整快照，并通过现有行版本与事务机制安全执行和撤销。

**Tech Stack:** Python 3.11、FastAPI、Pydantic 2、SQLite、原生 HTML/CSS/JavaScript、pytest、Node.js `node:test`

---

## 范围说明

本计划只实现设计文档的第一独立交付阶段：

- 明确“已勾选商品/当前筛选结果/全部库存”。
- 支持 `≤200`、`201～300`、`301～600`、`601～800`、`≥801` 和自定义价格区间。
- 支持统一加价、统一减价和固定价格。
- 完善匹配、修改、不变、跳过统计和完整 CSV 预览。
- 完善操作摘要并允许改价、隐藏、显示操作撤销。

后台导航、数据概览、删除恢复机制和可配置多价格段规则属于独立子系统，不混入本计划，避免一次发布同时改变过多管理流程。

## 文件职责

- `src/moments_inventory/showcase_web/api.py`：请求校验、作用范围解析、价格计算、预览统计、CSV 导出接口。
- `src/moments_inventory/showcase_web/bulk_service.py`：保存完整快照、筛选可执行项目、事务执行、操作摘要和撤销。
- `src/moments_inventory/showcase_web/static/admin.html`：批量工作台、预览区域和最终确认对话框。
- `src/moments_inventory/showcase_web/static/admin.js`：工作台状态、请求构造、预览失效、确认执行、CSV 下载和撤销交互。
- `src/moments_inventory/showcase_web/static/showcase.css`：工作台、统计卡片、对话框、响应式和键盘焦点样式。
- `tests/test_showcase_web_api_admin.py`：接口契约、价格边界和作用范围测试。
- `tests/test_showcase_web_bulk_transactions.py`：快照、幂等、冲突、撤销和日志测试。
- `tests/browser/frontend-contracts.cjs`：前端请求、失效规则、双击防护和范围文案测试。
- `docs/ccd-release-runbook.md`：发布验收入口。

### Task 1: 建立明确的批量请求契约

**Files:**
- Modify: `src/moments_inventory/showcase_web/api.py:400-449`
- Test: `tests/test_showcase_web_api_admin.py:564-640`

- [ ] **Step 1: 写接口校验测试**

在 `tests/test_showcase_web_api_admin.py` 增加：

```python
def test_admin_bulk_request_requires_explicit_safe_scope(
    authenticated_client: TestClient,
    repo: SQLiteShowcaseRepository,
) -> None:
    repo.upsert_product(_product_with("p1", model="佳能测试", brand="佳能", price=200))

    implicit = authenticated_client.post(
        "/api/admin/products/bulk-preview",
        json={"operation": "price", "priceMode": "increment", "amount": 30},
    )
    empty_selected = authenticated_client.post(
        "/api/admin/products/bulk-preview",
        json={
            "scope": "selected",
            "operation": "price",
            "priceMode": "increment",
            "amount": 30,
            "productIds": [],
        },
    )
    explicit_all = authenticated_client.post(
        "/api/admin/products/bulk-preview",
        json={
            "scope": "all",
            "operation": "price",
            "priceMode": "increment",
            "amount": 30,
            "filters": {"visible": True, "sold": False},
        },
    )

    assert implicit.status_code == 422
    assert empty_selected.status_code == 422
    assert explicit_all.status_code == 200


def test_admin_bulk_request_validates_price_range_and_amount(
    authenticated_client: TestClient,
) -> None:
    reversed_range = authenticated_client.post(
        "/api/admin/products/bulk-preview",
        json={
            "scope": "filtered",
            "operation": "price",
            "priceMode": "increment",
            "amount": 30,
            "filters": {"priceMin": 301, "priceMax": 300},
        },
    )
    zero_increment = authenticated_client.post(
        "/api/admin/products/bulk-preview",
        json={
            "scope": "filtered",
            "operation": "price",
            "priceMode": "increment",
            "amount": 0,
            "filters": {"priceMax": 200},
        },
    )

    assert reversed_range.status_code == 422
    assert zero_increment.status_code == 422
```

- [ ] **Step 2: 运行测试并确认失败**

Run:

```powershell
python -m pytest tests/test_showcase_web_api_admin.py -k "explicit_safe_scope or validates_price_range" -v
```

Expected: FAIL；当前请求没有 `scope` 校验，反向区间和 0 元加价不会全部返回 422。

- [ ] **Step 3: 实现请求模型校验**

在 `api.py` 顶部加入：

```python
from typing import Self

from pydantic import BaseModel, Field, model_validator
```

将批量筛选和请求模型更新为：

```python
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
            self.query.strip(), self.model.strip(), self.brand.strip(), self.brands,
            self.priceMin is not None, self.priceMax is not None,
            self.hasBodyImage is not None, self.hasSampleImage is not None,
            self.manualPrice is not None, self.tags, self.sectionId.strip(),
            self.updatedAfter.strip(), self.importId.strip(), self.reviewState.strip(),
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

    @model_validator(mode="after")
    def validate_scope_and_price(self) -> Self:
        references = [*self.productIds, *self.publicIds]
        if self.scope == "selected" and not references:
            raise ValueError("已勾选商品范围至少需要一个商品")
        if self.scope != "selected" and references:
            raise ValueError("只有已勾选商品范围可以提交商品编号")
        if self.scope == "filtered" and not self.filters.has_narrowing_constraint():
            raise ValueError("当前筛选结果范围至少需要价格段或商品筛选条件；处理全部展示中未售商品时请选择全部库存")
        if self.operation == "price" and self.priceMode in {"increment", "decrement"} and self.amount <= 0:
            raise ValueError("加价或减价金额必须大于 0")
        return self
```

- [ ] **Step 4: 更新已有批量测试请求**

所有明确商品编号的测试请求增加：

```python
"scope": "selected",
```

所有有筛选条件的测试请求增加：

```python
"scope": "filtered",
```

所有确实验证全库快照的测试请求增加：

```python
"scope": "all",
```

同时把旧 `tiered_increment` 测试改为明确价格范围和 `increment`，不再依赖后端写死阶梯。

- [ ] **Step 5: 运行批量接口测试**

Run:

```powershell
python -m pytest tests/test_showcase_web_api_admin.py -k "bulk" -v
```

Expected: PASS；所有批量请求都显式声明作用范围。

- [ ] **Step 6: 提交请求契约**

```powershell
git add src/moments_inventory/showcase_web/api.py tests/test_showcase_web_api_admin.py tests/test_showcase_web_bulk_transactions.py
git commit -m "feat: require explicit CCD bulk operation scope"
```

### Task 2: 实现五个价格段、减价和预览统计

**Files:**
- Modify: `src/moments_inventory/showcase_web/api.py:428-449`
- Modify: `src/moments_inventory/showcase_web/api.py:2500-2588`
- Test: `tests/test_showcase_web_api_admin.py:564-640`

- [ ] **Step 1: 写价格边界和预览统计测试**

在 `tests/test_showcase_web_api_admin.py` 增加：

```python
def test_admin_bulk_price_bands_use_inclusive_integer_boundaries(
    authenticated_client: TestClient,
    repo: SQLiteShowcaseRepository,
) -> None:
    for price in (200, 201, 300, 301, 600, 601, 800, 801):
        repo.upsert_product(_product_with(str(price), model=f"边界{price}", brand="佳能", price=price))

    expected = {
        (None, 200): [200],
        (201, 300): [201, 300],
        (301, 600): [301, 600],
        (601, 800): [601, 800],
        (801, None): [801],
    }
    for (minimum, maximum), prices in expected.items():
        response = authenticated_client.post(
            "/api/admin/products/bulk-preview",
            json={
                "scope": "filtered",
                "operation": "price",
                "priceMode": "increment",
                "amount": 30,
                "filters": {
                    "priceMin": minimum,
                    "priceMax": maximum,
                    "visible": True,
                    "sold": False,
                },
            },
        )
        assert response.status_code == 200
        assert sorted(item["oldPrice"] for item in response.json()["items"] if not item["skippedReason"]) == prices


def test_admin_bulk_preview_separates_changed_unchanged_and_skipped(
    authenticated_client: TestClient,
    repo: SQLiteShowcaseRepository,
) -> None:
    repo.upsert_product(_product_with("changed", model="变化商品", brand="佳能", price=200, visible=True))
    repo.upsert_product(_product_with("unchanged", model="不变商品", brand="佳能", price=230, visible=True))
    repo.upsert_product(_product_with("hidden", model="隐藏商品", brand="佳能", price=200, visible=False))
    repo.upsert_product(_product_with("sold", model="已售商品", brand="佳能", price=200, visible=True, sold=True))

    response = authenticated_client.post(
        "/api/admin/products/bulk-preview",
        json={
            "scope": "all",
            "operation": "price",
            "priceMode": "fixed_final",
            "amount": 230,
            "filters": {"priceMax": 300, "visible": True, "sold": False},
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["matchedCount"] == 4
    assert body["changedCount"] == 1
    assert body["unchangedCount"] == 1
    assert body["skippedCount"] == 2
    assert body["skipReasons"] == {"已隐藏": 1, "已售": 1}
    assert body["priceStats"] == {"minimum": 230, "maximum": 230, "totalDelta": 30}


def test_admin_bulk_decrement_skips_negative_result(
    authenticated_client: TestClient,
    repo: SQLiteShowcaseRepository,
) -> None:
    repo.upsert_product(_product_with("low", model="低价商品", brand="佳能", price=20))
    response = authenticated_client.post(
        "/api/admin/products/bulk-preview",
        json={
            "scope": "selected",
            "operation": "price",
            "priceMode": "decrement",
            "amount": 30,
            "productIds": ["low"],
        },
    )
    assert response.status_code == 200
    assert response.json()["changedCount"] == 0
    assert response.json()["skipReasons"] == {"减价后低于 0 元": 1}
```

- [ ] **Step 2: 运行测试并确认失败**

Run:

```powershell
python -m pytest tests/test_showcase_web_api_admin.py -k "price_bands or separates_changed or decrement" -v
```

Expected: FAIL；当前响应没有统计字段、来源价、变化标记和跳过原因，也不支持减价。

- [ ] **Step 3: 扩展预览响应模型**

在 `api.py` 中加入：

```python
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
```

- [ ] **Step 4: 实现价格计算和状态跳过逻辑**

将 `_bulk_new_price` 和 `_bulk_preview_response` 改为：

```python
def _bulk_new_price(old_price: int, request: AdminBulkOperationRequest) -> int:
    if request.priceMode == "fixed_final":
        return request.amount
    if request.priceMode == "decrement":
        return old_price - request.amount
    return old_price + request.amount


def _bulk_skip_reason(product: ShowcaseProduct, request: AdminBulkOperationRequest) -> str:
    if request.operation == "show" and product.sold:
        return "已售商品不能直接显示"
    if request.filters.sold is not None and product.sold != request.filters.sold:
        return "已售" if product.sold else "未售"
    if request.filters.visible is not None and product.visible != request.filters.visible:
        return "已隐藏" if not product.visible else "展示中"
    return ""


def _bulk_preview_response(
    repo: SQLiteShowcaseRepository,
    request: AdminBulkOperationRequest,
) -> AdminBulkPreviewResponse:
    search = _admin_search_from_bulk_filters(request.filters)
    search_without_status = replace(search, visible=None, sold=None)
    references = request.publicIds or request.productIds
    product_ids = repo.resolve_product_references(references) if request.scope == "selected" else None
    summaries = repo.list_admin_products_for_bulk(search_without_status, product_ids=product_ids)
    items: list[AdminBulkPreviewItemResponse] = []
    skip_reasons: dict[str, int] = {}

    for summary in sorted(summaries, key=lambda item: (-item.product.display_price, item.product.product_id)):
        product = summary.product
        skipped_reason = _bulk_skip_reason(product, request)
        new_price = product.display_price
        new_visible = product.visible
        if not skipped_reason and request.operation == "price":
            new_price = _bulk_new_price(product.display_price, request)
            if new_price < 0:
                skipped_reason = "减价后低于 0 元"
                new_price = product.display_price
        elif not skipped_reason and request.operation == "hide":
            new_visible = False
        elif not skipped_reason and request.operation == "show":
            new_visible = True

        changed = not skipped_reason and (
            new_price != product.display_price or new_visible != product.visible
        )
        if skipped_reason:
            skip_reasons[skipped_reason] = skip_reasons.get(skipped_reason, 0) + 1
        items.append(AdminBulkPreviewItemResponse(
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
        ))

    changed_items = [item for item in items if item.changed]
    unchanged_count = sum(1 for item in items if not item.changed and not item.skippedReason)
    prices = [item.newPrice for item in changed_items if request.operation == "price"]
    stats = AdminBulkPriceStatsResponse(
        minimum=min(prices) if prices else None,
        maximum=max(prices) if prices else None,
        totalDelta=sum(item.delta for item in changed_items),
    )
    return AdminBulkPreviewResponse(
        operation=request.operation,
        total=len(items),
        matchedCount=len(items),
        changedCount=len(changed_items),
        unchangedCount=unchanged_count,
        skippedCount=sum(skip_reasons.values()),
        skipReasons=skip_reasons,
        priceStats=stats,
        items=items,
    )
```

- [ ] **Step 5: 让预览接口保存完整快照但仅返回前 200 条**

保持 `preview.items` 全量传入 `bulk_service.save_preview`，响应继续使用：

```python
displayed_items = preview.items[:200]
return preview.model_copy(update={
    "previewId": preview_id,
    "expiresAt": expires,
    "displayedCount": len(displayed_items),
    "truncated": len(displayed_items) < preview.total,
    "items": displayed_items,
})
```

- [ ] **Step 6: 运行价格边界测试**

Run:

```powershell
python -m pytest tests/test_showcase_web_api_admin.py -k "bulk" -v
```

Expected: PASS；所有边界归属、减价和统计字段符合设计。

- [ ] **Step 7: 提交价格计算和统计**

```powershell
git add src/moments_inventory/showcase_web/api.py tests/test_showcase_web_api_admin.py
git commit -m "feat: preview CCD bulk pricing by explicit price ranges"
```

### Task 3: 只执行变化项目并完善操作日志与撤销

**Files:**
- Modify: `src/moments_inventory/showcase_web/bulk_service.py:11-130`
- Modify: `src/moments_inventory/showcase_web/api.py:1270-1341`
- Modify: `src/moments_inventory/showcase_web/static/admin.js:566-578`
- Test: `tests/test_showcase_web_bulk_transactions.py:7-106`

- [ ] **Step 1: 写快照执行和操作摘要测试**

在 `tests/test_showcase_web_bulk_transactions.py` 增加：

```python
def test_bulk_executes_only_changed_items_and_records_scope(repo, authenticated_client):
    repo.upsert_product(_product('changed', visible=True, display_price=200))
    repo.upsert_product(_product('same', visible=True, display_price=230))
    repo.upsert_product(replace(_product('sold', visible=True, display_price=200), sold=True))
    preview = authenticated_client.post('/api/admin/products/bulk-preview', json={
        'scope': 'all',
        'operation': 'price',
        'priceMode': 'fixed_final',
        'amount': 230,
        'filters': {'priceMax': 300, 'visible': True, 'sold': False},
    }).json()

    applied = authenticated_client.post('/api/admin/products/bulk-apply', json={
        'previewId': preview['previewId'], 'idempotencyKey': 'changed-only',
    })

    assert applied.status_code == 200
    assert applied.json()['updatedCount'] == 1
    operations = authenticated_client.get('/api/admin/operations').json()['operations']
    assert operations[0]['summary'] == '全部库存 · 300 元以内 · 固定为 230 元 · 修改 1 台'
    assert 'priceMax=300' in operations[0]['filterText']


def test_hide_operation_can_be_undone(repo, authenticated_client):
    repo.upsert_product(_product('a', visible=True, display_price=500))
    preview = authenticated_client.post('/api/admin/products/bulk-preview', json={
        'scope': 'selected', 'operation': 'hide', 'productIds': ['a'],
    }).json()
    applied = authenticated_client.post('/api/admin/products/bulk-apply', json={
        'previewId': preview['previewId'], 'idempotencyKey': 'hide-apply',
    }).json()
    undone = authenticated_client.post(
        '/api/admin/operations/' + applied['operationId'] + '/undo',
        json={'idempotencyKey': 'hide-undo'},
    )
    assert undone.status_code == 200
    assert repo.get_product('a').visible is True
```

- [ ] **Step 2: 运行测试并确认失败**

Run:

```powershell
python -m pytest tests/test_showcase_web_bulk_transactions.py -k "changed_items or hide_operation" -v
```

Expected: FAIL；当前服务对快照内所有项目做版本校验，日志摘要和筛选文本不完整。

- [ ] **Step 3: 保存可读摘要并筛出真正执行的项目**

在 `api.py` 增加摘要函数：

```python
def _bulk_price_range_text(filters: AdminBulkProductFilters) -> str:
    if filters.priceMin is None and filters.priceMax == 200:
        return "200 元以内"
    if filters.priceMin is not None and filters.priceMax is not None:
        return f"{filters.priceMin}～{filters.priceMax} 元"
    if filters.priceMin == 801 and filters.priceMax is None:
        return "801 元以上"
    if filters.priceMin is not None:
        return f"{filters.priceMin} 元以上"
    if filters.priceMax is not None:
        return f"{filters.priceMax} 元以内"
    return "全部价格"


def _bulk_operation_summary(request: AdminBulkOperationRequest, changed_count: int) -> str:
    scope_text = {"selected": "已勾选商品", "filtered": "当前筛选结果", "all": "全部库存"}[request.scope]
    range_text = _bulk_price_range_text(request.filters)
    if request.operation == "hide":
        action_text = "批量隐藏"
    elif request.operation == "show":
        action_text = "批量显示"
    elif request.priceMode == "fixed_final":
        action_text = f"固定为 {request.amount} 元"
    elif request.priceMode == "decrement":
        action_text = f"减价 {request.amount} 元"
    else:
        action_text = f"加价 {request.amount} 元"
    return f"{scope_text} · {range_text} · {action_text} · 修改 {changed_count} 台"


def _bulk_filter_text(request: AdminBulkOperationRequest) -> str:
    pairs = [f"scope={request.scope}"]
    for key, value in request.filters.model_dump().items():
        if value not in (None, "", []):
            pairs.append(f"{key}={value}")
    return "; ".join(pairs)
```

在预览接口保存快照前加入：

```python
request_snapshot = request.model_dump()
request_snapshot["operationSummary"] = _bulk_operation_summary(request, preview.changedCount)
request_snapshot["filterText"] = _bulk_filter_text(request)
preview_id, expires = bulk_service.save_preview(
    repo,
    showcase_admin_session,
    request_snapshot,
    [item.model_dump() for item in preview.items],
)
```

在 `bulk_service.py` 中把 `_write_operation` 改成显式接收摘要：

```python
def _write_operation(
    conn,
    operation_id,
    operation_type,
    items,
    now,
    *,
    summary,
    filter_text,
    parent="",
):
    conn.execute(
        '''INSERT INTO showcase_admin_operation_logs
        (operation_id,operation_type,summary,filter_text,updated_count,created_at,undone_at,parent_operation_id)
        VALUES (?,?,?,?,?,?,?,?)''',
        (operation_id, operation_type, summary, filter_text, len(items), now, '', parent),
    )
    conn.executemany(
        '''INSERT INTO showcase_admin_operation_items
        (item_id,operation_id,product_id,old_price,new_price,old_visible,new_visible,old_version,new_version,
         old_price_override,new_price_override,old_visibility_override,new_visibility_override,
         old_override_origin,new_override_origin)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
        [(uuid.uuid4().hex, operation_id, item['productId'],
          item['oldPrice'], item['newPrice'], item['oldVisible'], item['newVisible'],
          item['rowVersion'], item['rowVersion'] + 1,
          item.get('oldPriceOverride'), item.get('newPriceOverride'),
          item.get('oldVisibilityOverride'), item.get('newVisibilityOverride'),
          item.get('oldOverrideOrigin', ''), item.get('newOverrideOrigin', '')) for item in items],
    )
```

在 `execute` 读取预览后加入：

```python
request_data = json.loads(preview['request_json'])
items = [
    item for item in json.loads(preview['items_json'])
    if item.get('changed') and not item.get('skippedReason')
]
operation_type = request_data['operation']
summary = request_data['operationSummary']
filter_text = request_data['filterText']
```

撤销分支设置：

```python
summary = f"撤销：{operation['summary']}"
filter_text = operation['filter_text']
```

调用 `_write_operation` 时使用：

```python
_write_operation(
    conn,
    operation_id,
    operation_type,
    changed,
    now,
    summary=summary,
    filter_text=filter_text,
    parent=reference if undo else "",
)
```

- [ ] **Step 4: 允许所有可撤销批量操作显示撤销按钮**

在 `admin.js` 的 `loadOperations` 中把按钮条件改为：

```javascript
${operation.operationType !== "undo" && !operation.undoneAt
  ? `<button class="undo-operation" type="button">撤销这次操作</button>`
  : ""}
```

- [ ] **Step 5: 运行事务和撤销测试**

Run:

```powershell
python -m pytest tests/test_showcase_web_bulk_transactions.py -v
```

Expected: PASS；只修改 `changed=true` 的项目，日志包含范围和规则，隐藏操作可以安全撤销。

- [ ] **Step 6: 提交事务与日志改造**

```powershell
git add src/moments_inventory/showcase_web/api.py src/moments_inventory/showcase_web/bulk_service.py src/moments_inventory/showcase_web/static/admin.js tests/test_showcase_web_bulk_transactions.py
git commit -m "feat: record and undo CCD bulk operation snapshots"
```

### Task 4: 增加完整预览 CSV 导出

**Files:**
- Modify: `src/moments_inventory/showcase_web/bulk_service.py:11-20`
- Modify: `src/moments_inventory/showcase_web/api.py:1269-1304`
- Test: `tests/test_showcase_web_api_admin.py`

- [ ] **Step 1: 写 CSV 导出测试**

```python
def test_admin_can_export_complete_bulk_preview_csv(
    authenticated_client: TestClient,
    repo: SQLiteShowcaseRepository,
) -> None:
    for index in range(205):
        repo.upsert_product(_product_with(
            f"p-{index}", model=f"导出商品{index}", brand="佳能", price=200 + index,
        ))
    preview = authenticated_client.post(
        "/api/admin/products/bulk-preview",
        json={
            "scope": "all",
            "operation": "price",
            "priceMode": "increment",
            "amount": 30,
            "filters": {"visible": True, "sold": False},
        },
    ).json()

    response = authenticated_client.get(
        f"/api/admin/products/bulk-preview/{preview['previewId']}/export"
    )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/csv")
    assert "attachment" in response.headers["content-disposition"]
    assert response.content.startswith(b"\xef\xbb\xbf")
    assert response.text.count("\n") == 206
    assert "p-204" in response.text
```

- [ ] **Step 2: 运行测试并确认失败**

Run:

```powershell
python -m pytest tests/test_showcase_web_api_admin.py -k "export_complete_bulk_preview_csv" -v
```

Expected: FAIL with 404；导出接口尚不存在。

- [ ] **Step 3: 增加快照读取函数**

在 `bulk_service.py` 增加：

```python
def load_preview_items(repo, owner, preview_id):
    now = datetime.now(timezone.utc).isoformat()
    with repo._lock, repo._get_connection() as conn:
        row = conn.execute(
            'SELECT owner, expires_at, items_json FROM showcase_bulk_previews WHERE preview_id=?',
            (preview_id,),
        ).fetchone()
    if row is None or row[0] != owner:
        raise HTTPException(404, '预览不存在')
    if row[1] < now:
        raise HTTPException(409, '预览已过期，请重新预览')
    return json.loads(row[2])
```

- [ ] **Step 4: 增加 CSV 导出路由**

在 `api.py` 顶部增加 `csv` 和 `io` 导入，并在批量预览路由后增加：

```python
@router.get(
    "/products/bulk-preview/{preview_id}/export",
    dependencies=[Depends(require_admin)],
)
def export_admin_bulk_preview(
    preview_id: str,
    showcase_admin_session: str = Cookie(default=""),
    repo: SQLiteShowcaseRepository = Depends(get_repository),
) -> Response:
    items = bulk_service.load_preview_items(repo, showcase_admin_session, preview_id)
    output = io.StringIO()
    writer = csv.writer(output, lineterminator="\n")
    writer.writerow([
        "商品ID", "型号", "品牌", "导入原价", "当前展示价", "新展示价",
        "变化金额", "是否修改", "跳过原因", "展示状态", "已售状态",
    ])
    for item in items:
        writer.writerow([
            item["productId"], item["model"], item["brand"], item["sourcePrice"],
            item["oldPrice"], item["newPrice"], item["delta"],
            "是" if item["changed"] else "否", item["skippedReason"],
            "展示" if item["oldVisible"] else "隐藏", "已售" if item["sold"] else "未售",
        ])
    content = "\ufeff" + output.getvalue()
    return Response(
        content=content.encode("utf-8"),
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="ccd-bulk-preview-{preview_id}.csv"'
        },
    )
```

- [ ] **Step 5: 运行导出测试**

Run:

```powershell
python -m pytest tests/test_showcase_web_api_admin.py -k "export_complete_bulk_preview_csv" -v
```

Expected: PASS；205 台商品全部出现在 CSV，页面响应仍只渲染前 200 台。

- [ ] **Step 6: 提交 CSV 导出**

```powershell
git add src/moments_inventory/showcase_web/api.py src/moments_inventory/showcase_web/bulk_service.py tests/test_showcase_web_api_admin.py
git commit -m "feat: export complete CCD bulk price preview"
```

### Task 5: 将批量工作台并入商品管理

**Files:**
- Modify: `src/moments_inventory/showcase_web/static/admin.html:212-240`
- Modify: `src/moments_inventory/showcase_web/static/admin.html:289-364`
- Modify: `src/moments_inventory/showcase_web/static/showcase.css:1068-1171`
- Test: `tests/browser/frontend-contracts.cjs`

- [ ] **Step 1: 写静态结构契约测试**

在 `tests/browser/frontend-contracts.cjs` 增加：

```javascript
test('商品管理包含明确的批量作用范围和价格段控件', () => {
  const html = fs.readFileSync(path.join(root, 'admin.html'), 'utf8');
  assert.match(html, /id="bulkScopeInput"/);
  assert.match(html, /value="selected"/);
  assert.match(html, /value="filtered"/);
  assert.match(html, /value="all"/);
  assert.match(html, /id="bulkPriceRangeInput"/);
  for (const value of ['up_to_200', '201_300', '301_600', '601_800', '801_plus', 'custom']) {
    assert.match(html, new RegExp(`value="${value}"`));
  }
  assert.ok(html.indexOf('id="bulkPricingPanel"') > html.indexOf('<h2>商品管理</h2>'));
  assert.match(html, /id="bulkPreviewStatus"[^>]*aria-live="polite"/);
});
```

- [ ] **Step 2: 运行结构测试并确认失败**

Run:

```powershell
node --test tests/browser/frontend-contracts.cjs
```

Expected: FAIL；批量工作台仍位于独立区域且缺少范围和价格段控件。

- [ ] **Step 3: 移动并重写批量工作台 HTML**

删除原 `批量操作中心` section。在“商品管理”的筛选工具栏之后、商品列表之前加入：

```html
<section id="bulkPricingPanel" class="bulk-workbench" aria-labelledby="bulkPricingHeading">
  <div class="bulk-workbench-heading">
    <div>
      <h3 id="bulkPricingHeading">批量操作</h3>
      <p id="bulkScopeSummary" class="status-text" aria-live="polite">当前没有选择商品</p>
    </div>
    <button id="clearBulkSelectionButton" class="secondary-button" type="button">清空选择</button>
  </div>
  <form id="batchPriceForm" class="bulk-workbench-grid">
    <label class="field">
      <span>作用范围</span>
      <select id="bulkScopeInput">
        <option value="selected">已勾选商品</option>
        <option value="filtered" selected>当前筛选结果</option>
        <option value="all">全部库存</option>
      </select>
    </label>
    <label class="field">
      <span>操作</span>
      <select id="bulkOperationInput">
        <option value="price">批量改价</option>
        <option value="hide">批量隐藏</option>
        <option value="show">批量显示</option>
      </select>
    </label>
    <label class="field bulk-price-field">
      <span>价格范围</span>
      <select id="bulkPriceRangeInput">
        <option value="all">全部价格</option>
        <option value="up_to_200">200 元以内</option>
        <option value="201_300">201～300 元</option>
        <option value="301_600">301～600 元</option>
        <option value="601_800">601～800 元</option>
        <option value="801_plus">801 元以上</option>
        <option value="custom">自定义价格区间</option>
      </select>
    </label>
    <label id="bulkCustomMinField" class="field bulk-price-field" hidden>
      <span>最低价格</span>
      <input id="bulkMinPriceInput" type="number" min="0" inputmode="numeric" autocomplete="off">
    </label>
    <label id="bulkCustomMaxField" class="field bulk-price-field" hidden>
      <span>最高价格</span>
      <input id="bulkMaxPriceInput" type="number" min="0" inputmode="numeric" autocomplete="off">
    </label>
    <label class="field">
      <span>展示状态</span>
      <select id="bulkVisibleInput">
        <option value="true" selected>只处理展示中</option>
        <option value="false">只处理已隐藏</option>
        <option value="">展示中和已隐藏</option>
      </select>
    </label>
    <label class="field">
      <span>已售状态</span>
      <select id="bulkSoldInput">
        <option value="false" selected>只处理未售</option>
        <option value="true">只处理已售</option>
        <option value="">未售和已售</option>
      </select>
    </label>
    <label class="field bulk-price-field">
      <span>改价方式</span>
      <select id="bulkPriceModeInput">
        <option value="increment">统一加价</option>
        <option value="decrement">统一减价</option>
        <option value="fixed_final">固定最终价</option>
      </select>
    </label>
    <label class="field bulk-price-field">
      <span id="bulkAmountLabel">每台增加金额</span>
      <input id="batchAmountInput" type="number" min="0" inputmode="numeric" autocomplete="off" value="30">
    </label>
    <button id="generateBulkPreviewButton" class="secondary-button" type="submit">生成预览</button>
  </form>
  <p id="bulkPreviewStatus" class="status-text" aria-live="polite"></p>
  <div id="bulkPreviewSummary" class="bulk-preview-stats"></div>
  <div id="bulkPreviewPanel" class="admin-compact-list"></div>
  <div class="bulk-preview-actions">
    <button id="exportBulkPreviewButton" class="secondary-button" type="button" disabled>导出完整预览</button>
    <button id="openBulkConfirmButton" class="access-button" type="button" disabled>检查并确认执行</button>
  </div>
</section>

<dialog id="bulkConfirmDialog" class="bulk-confirm-dialog">
  <form method="dialog">
    <h3>确认批量操作</h3>
    <p id="bulkConfirmSummary"></p>
    <div id="bulkConfirmWarnings" class="bulk-warning-list"></div>
    <div class="bulk-confirm-actions">
      <button class="secondary-button" type="submit" value="cancel">返回检查</button>
      <button id="applyBulkButton" class="access-button" type="button">确认执行</button>
    </div>
  </form>
</dialog>
```

- [ ] **Step 4: 增加工作台样式和焦点状态**

在 `showcase.css` 增加：

```css
.bulk-workbench {
  margin: 16px 0;
  padding: 16px;
  border: 2px solid rgba(216, 78, 134, 0.32);
  background: #fffafb;
}

.bulk-workbench-heading,
.bulk-preview-actions,
.bulk-confirm-actions {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
}

.bulk-workbench-heading h3 {
  margin: 0 0 4px;
}

.bulk-workbench-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(170px, 1fr));
  align-items: end;
  gap: 12px;
  margin-top: 14px;
}

.bulk-preview-stats {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(120px, 1fr));
  gap: 8px;
  margin-top: 12px;
}

.bulk-preview-stat {
  padding: 10px;
  border: 1px solid var(--line);
  background: var(--surface);
}

.bulk-preview-stat strong {
  display: block;
  font-size: 20px;
  font-variant-numeric: tabular-nums;
}

.bulk-confirm-dialog {
  width: min(620px, calc(100vw - 32px));
  border: 1px solid var(--line);
  padding: 22px;
}

.bulk-confirm-dialog::backdrop {
  background: rgba(38, 24, 31, 0.46);
}

.bulk-warning-list {
  color: #9d3e2e;
  font-weight: 800;
}

button:focus-visible,
a:focus-visible,
input:focus-visible,
select:focus-visible,
textarea:focus-visible {
  outline: 3px solid rgba(216, 78, 134, 0.42);
  outline-offset: 2px;
}

@media (max-width: 760px) {
  .bulk-workbench-grid {
    grid-template-columns: 1fr;
  }

  .bulk-preview-actions > button,
  .bulk-confirm-actions > button {
    width: 100%;
  }
}
```

- [ ] **Step 5: 运行结构契约测试**

Run:

```powershell
node --test tests/browser/frontend-contracts.cjs
```

Expected: PASS；工作台位于商品管理中，所有范围控件和动态状态区域存在。

- [ ] **Step 6: 提交工作台结构**

```powershell
git add src/moments_inventory/showcase_web/static/admin.html src/moments_inventory/showcase_web/static/showcase.css tests/browser/frontend-contracts.cjs
git commit -m "feat: add CCD bulk pricing workbench"
```

### Task 6: 实现前端范围、预览失效、确认和导出交互

**Files:**
- Modify: `src/moments_inventory/showcase_web/static/admin.js:1-45`
- Modify: `src/moments_inventory/showcase_web/static/admin.js:1175-1245`
- Test: `tests/browser/frontend-contracts.cjs:86-103`

- [ ] **Step 1: 写前端请求和预览失效测试**

在 `tests/browser/frontend-contracts.cjs` 增加：

```javascript
test('批量价格段转换为包含边界且默认排除隐藏和已售商品', () => {
  const c = pageContext('admin.js');
  c.nodes.get('bulkScopeInput').value = 'filtered';
  c.nodes.get('bulkOperationInput').value = 'price';
  c.nodes.get('bulkPriceRangeInput').value = '201_300';
  c.nodes.get('bulkVisibleInput').value = 'true';
  c.nodes.get('bulkSoldInput').value = 'false';
  c.nodes.get('bulkPriceModeInput').value = 'increment';
  c.nodes.get('batchAmountInput').value = '50';

  const request = vm.runInContext('buildBulkRequest()', c);
  assert.equal(JSON.stringify(request), JSON.stringify({
    scope: 'filtered', operation: 'price', priceMode: 'increment', amount: 50,
    productIds: [], filters: {
      query: '', brands: [], priceMin: 201, priceMax: 300,
      visible: true, sold: false, hasBodyImage: null,
      hasSampleImage: null, manualPrice: null, reviewState: '', tags: [],
    },
  }));
});

test('修改批量条件会清除旧预览和执行能力', () => {
  const c = pageContext('admin.js');
  vm.runInContext(`adminState.lastBulkRequest = {previewId:'old',idempotencyKey:'key'};
    adminState.lastBulkPreview = {changedCount:3};`, c);
  c.nodes.get('openBulkConfirmButton').disabled = false;
  c.nodes.get('exportBulkPreviewButton').disabled = false;

  c.nodes.get('bulkPriceRangeInput').listeners.change();

  assert.equal(vm.runInContext('adminState.lastBulkRequest', c), null);
  assert.equal(vm.runInContext('adminState.lastBulkPreview', c), null);
  assert.equal(c.nodes.get('openBulkConfirmButton').disabled, true);
  assert.equal(c.nodes.get('exportBulkPreviewButton').disabled, true);
});
```

扩展 `pageContext` 的测试节点，使节点默认包含 `disabled`、`textContent`、`innerHTML`、`classList`、`showModal()` 和 `close()`。

- [ ] **Step 2: 运行前端测试并确认失败**

Run:

```powershell
node --test tests/browser/frontend-contracts.cjs
```

Expected: FAIL；当前没有价格段映射、显式作用范围和统一预览失效函数。

- [ ] **Step 3: 增加工作台状态和价格段映射**

在 `admin.js` 顶部增加节点引用和状态：

```javascript
const bulkPreviewSummary = document.getElementById("bulkPreviewSummary");
const bulkPreviewStatus = document.getElementById("bulkPreviewStatus");
const openBulkConfirmButton = document.getElementById("openBulkConfirmButton");
const exportBulkPreviewButton = document.getElementById("exportBulkPreviewButton");
const bulkConfirmDialog = document.getElementById("bulkConfirmDialog");

const BULK_PRICE_RANGES = {
  all: [null, null],
  up_to_200: [null, 200],
  "201_300": [201, 300],
  "301_600": [301, 600],
  "601_800": [601, 800],
  "801_plus": [801, null],
};

const BULK_PRICE_RANGE_LABELS = {
  all: "全部价格",
  up_to_200: "200 元以内",
  "201_300": "201～300 元",
  "301_600": "301～600 元",
  "601_800": "601～800 元",
  "801_plus": "801 元以上",
  custom: "自定义价格区间",
};
```

在 `adminState` 中增加：

```javascript
lastBulkPreview: null,
```

- [ ] **Step 4: 实现请求构造和预览失效**

替换 `buildBulkRequest`，并增加辅助函数：

```javascript
function nullableBooleanValue(id) {
  const value = document.getElementById(id)?.value ?? "";
  if (value === "true") return true;
  if (value === "false") return false;
  return null;
}

function nonNegativeNumberInputValue(id) {
  const raw = document.getElementById(id)?.value ?? "";
  if (raw === "") return null;
  const value = Number(raw);
  return Number.isInteger(value) && value >= 0 ? value : null;
}

function selectedBulkPriceRange() {
  const value = document.getElementById("bulkPriceRangeInput")?.value || "all";
  if (value === "custom") {
    return [
      nonNegativeNumberInputValue("bulkMinPriceInput"),
      nonNegativeNumberInputValue("bulkMaxPriceInput"),
    ];
  }
  return BULK_PRICE_RANGES[value] || [null, null];
}

function buildBulkRequest() {
  const scope = document.getElementById("bulkScopeInput")?.value || "filtered";
  const filters = scope === "filtered" ? collectAdminFilters() : {
    query: "", brands: [], priceMin: null, priceMax: null,
    visible: null, sold: null, hasBodyImage: null,
    hasSampleImage: null, manualPrice: null, reviewState: "", tags: [],
  };
  const [priceMin, priceMax] = selectedBulkPriceRange();
  filters.priceMin = priceMin;
  filters.priceMax = priceMax;
  filters.visible = nullableBooleanValue("bulkVisibleInput");
  filters.sold = nullableBooleanValue("bulkSoldInput");
  return {
    scope,
    operation: document.getElementById("bulkOperationInput")?.value || "price",
    priceMode: document.getElementById("bulkPriceModeInput")?.value || "increment",
    amount: Number(document.getElementById("batchAmountInput")?.value || 0),
    productIds: scope === "selected" ? [...adminState.selectedProductIds] : [],
    filters,
  };
}

function validateBulkRequest(request) {
  const hasSelected = request.productIds.length > 0;
  const hasNarrowingFilter = Boolean(
    request.filters.query || request.filters.brands.length ||
    request.filters.priceMin !== null || request.filters.priceMax !== null ||
    request.filters.hasBodyImage !== null || request.filters.hasSampleImage !== null ||
    request.filters.manualPrice !== null || request.filters.reviewState || request.filters.tags.length
  );
  if (request.scope === "selected" && !hasSelected) {
    throw new Error("请先勾选商品，或改用当前筛选结果")
  }
  if (request.scope === "filtered" && !hasNarrowingFilter) {
    throw new Error("请先选择价格段或设置商品筛选；如需处理全部展示中未售商品，请明确选择全部库存")
  }
  if (request.filters.priceMin !== null && request.filters.priceMax !== null &&
      request.filters.priceMin > request.filters.priceMax) {
    throw new Error("最低价格不能高于最高价格")
  }
  if (request.operation === "price" && request.priceMode !== "fixed_final" && request.amount <= 0) {
    throw new Error("加价或减价金额必须大于 0")
  }
}

function syncBulkControls() {
  const operation = document.getElementById("bulkOperationInput")?.value || "price";
  const priceMode = document.getElementById("bulkPriceModeInput")?.value || "increment";
  const rangeMode = document.getElementById("bulkPriceRangeInput")?.value || "all";
  document.querySelectorAll(".bulk-price-field").forEach((field) => {
    field.hidden = operation !== "price";
  });
  const showCustom = operation === "price" && rangeMode === "custom";
  document.getElementById("bulkCustomMinField").hidden = !showCustom;
  document.getElementById("bulkCustomMaxField").hidden = !showCustom;
  const labels = {
    increment: "每台增加金额",
    decrement: "每台减少金额",
    fixed_final: "新的展示价格",
  };
  document.getElementById("bulkAmountLabel").textContent = labels[priceMode];
}

function updateBulkScopeSummary() {
  const scope = document.getElementById("bulkScopeInput")?.value || "filtered";
  const range = document.getElementById("bulkPriceRangeInput")?.value || "all";
  const scopeText = scope === "selected"
    ? `已勾选 ${adminState.selectedProductIds.size} 台商品`
    : scope === "all"
      ? "以全部库存为基础范围"
      : `当前筛选结果共 ${adminState.productTotal} 台`;
  const target = document.getElementById("bulkScopeSummary");
  if (target) target.textContent = `${scopeText} · ${BULK_PRICE_RANGE_LABELS[range]}`;
}

function invalidateBulkPreview(message = "条件已变化，请重新生成预览") {
  adminState.lastBulkRequest = null;
  adminState.lastBulkPreview = null;
  if (openBulkConfirmButton) openBulkConfirmButton.disabled = true;
  if (exportBulkPreviewButton) exportBulkPreviewButton.disabled = true;
  if (bulkPreviewStatus) bulkPreviewStatus.textContent = message;
}
```

将批量预览表单提交处理器替换为：

```javascript
document.getElementById("batchPriceForm")?.addEventListener("submit", async (event) => {
  event.preventDefault();
  if (adminState.bulkBusy) return;
  invalidateBulkPreview("正在生成预览…");
  const previewRequestId = ++adminState.previewRequestId;
  try {
    const request = buildBulkRequest();
    validateBulkRequest(request);
    const preview = await requestJson("/api/admin/products/bulk-preview", {
      method: "POST",
      body: JSON.stringify(request),
    });
    if (previewRequestId !== adminState.previewRequestId) return;
    adminState.lastBulkPreview = preview;
    adminState.lastBulkRequest = {
      previewId: preview.previewId,
      idempotencyKey: crypto.randomUUID(),
    };
    renderBulkPreview(preview);
    openBulkConfirmButton.disabled = preview.changedCount === 0 || !preview.previewId;
    exportBulkPreviewButton.disabled = !preview.previewId;
  } catch (error) {
    if (previewRequestId === adminState.previewRequestId && bulkPreviewStatus) {
      bulkPreviewStatus.textContent = `无法生成预览：${error.message}`;
    }
  }
});
```

为这些节点注册 `change` 或 `input` 监听并调用 `invalidateBulkPreview()`：

```javascript
for (const id of [
  "bulkScopeInput", "bulkOperationInput", "bulkPriceRangeInput",
  "bulkMinPriceInput", "bulkMaxPriceInput", "bulkVisibleInput",
  "bulkSoldInput", "bulkPriceModeInput", "batchAmountInput",
]) {
  const input = document.getElementById(id);
  input?.addEventListener(input?.tagName === "INPUT" ? "input" : "change", () => {
    if (id === "bulkOperationInput") {
      const operation = document.getElementById("bulkOperationInput").value;
      document.getElementById("bulkVisibleInput").value = operation === "show" ? "false" : "true";
    }
    syncBulkControls();
    updateBulkScopeSummary();
    invalidateBulkPreview();
  });
}
syncBulkControls();
updateBulkScopeSummary();

document.getElementById("clearBulkSelectionButton")?.addEventListener("click", () => {
  adminState.selectedProductIds = new Set();
  renderAdminProducts();
  updateBulkScopeSummary();
  invalidateBulkPreview("已清空商品选择，请重新生成预览");
});
```

在 `renderAdminProducts()` 的末尾调用 `updateBulkScopeSummary()`；在 `.admin-product-select` 的现有变更处理器更新 `selectedProductIds` 后，调用 `updateBulkScopeSummary()` 和 `invalidateBulkPreview()`。

- [ ] **Step 5: 实现预览统计和明细**

替换 `renderBulkPreview`：

```javascript
function renderBulkPreview(preview) {
  if (!bulkPreviewPanel || !bulkPreviewSummary) return;
  const items = Array.isArray(preview.items) ? preview.items : [];
  const stats = preview.priceStats || {};
  bulkPreviewSummary.innerHTML = [
    ["匹配", preview.matchedCount],
    ["实际修改", preview.changedCount],
    ["价格不变", preview.unchangedCount],
    ["跳过", preview.skippedCount],
    ["最低新价格", stats.minimum ?? "—"],
    ["最高新价格", stats.maximum ?? "—"],
    ["合计变化", stats.totalDelta ?? 0],
  ].map(([label, value]) => `
    <div class="bulk-preview-stat"><strong>${escapeHtml(value)}</strong><span>${label}</span></div>
  `).join("");
  bulkPreviewPanel.innerHTML = items.map((item) => `
    <div class="admin-compact-row">
      <strong>${escapeHtml(item.model)} · ${escapeHtml(item.brand)}</strong>
      <span>导入价 ${item.sourcePrice} · 当前价 ${item.oldPrice} → 新价格 ${item.newPrice}
        （${item.delta >= 0 ? "+" : ""}${item.delta}）
        ${item.skippedReason ? ` · 跳过：${escapeHtml(item.skippedReason)}` : ""}</span>
    </div>
  `).join("");
  if (bulkPreviewStatus) {
    bulkPreviewStatus.textContent = preview.truncated
      ? `只展示前 ${preview.displayedCount} 台，完整结果请导出 CSV。预览 15 分钟内有效。`
      : `已生成 ${preview.matchedCount} 台商品的完整预览，预览 15 分钟内有效。`;
  }
}
```

- [ ] **Step 6: 实现确认窗口和 CSV 下载**

增加：

```javascript
openBulkConfirmButton?.addEventListener("click", () => {
  const preview = adminState.lastBulkPreview;
  if (!preview || !adminState.lastBulkRequest) return;
  const request = buildBulkRequest();
  const warnings = [];
  if (request.scope === "all") warnings.push("本次以全部库存为基础范围。请再次核对价格段和状态条件。");
  if (preview.changedCount > 200) warnings.push(`本次将修改 ${preview.changedCount} 台商品。`);
  if (request.filters.sold !== false) warnings.push("本次范围可能包含已售商品。");
  if (request.priceMode === "fixed_final" && request.amount === 0) warnings.push("本次会把目标商品价格改为 0 元。");
  document.getElementById("bulkConfirmSummary").textContent =
    `匹配 ${preview.matchedCount} 台，实际修改 ${preview.changedCount} 台，跳过 ${preview.skippedCount} 台。`;
  document.getElementById("bulkConfirmWarnings").innerHTML = warnings
    .map((warning) => `<p>${escapeHtml(warning)}</p>`).join("");
  bulkConfirmDialog?.showModal();
});

exportBulkPreviewButton?.addEventListener("click", () => {
  const previewId = adminState.lastBulkRequest?.previewId;
  if (!previewId) return;
  window.location.href = `/api/admin/products/bulk-preview/${encodeURIComponent(previewId)}/export`;
});
```

将现有执行处理器替换为：

```javascript
applyBulkButton?.addEventListener("click", async () => {
  if (!adminState.lastBulkRequest || adminState.bulkBusy) return;
  adminState.bulkBusy = true;
  applyBulkButton.disabled = true;
  const originalLabel = applyBulkButton.textContent;
  applyBulkButton.textContent = "正在执行…";
  try {
    const result = await requestJson("/api/admin/products/bulk-apply", {
      method: "POST",
      body: JSON.stringify(adminState.lastBulkRequest),
    });
    bulkConfirmDialog?.close("confirm");
    if (bulkPreviewStatus) bulkPreviewStatus.textContent = `已执行，实际修改 ${result.updatedCount} 台商品。`;
    adminState.lastBulkRequest = null;
    adminState.lastBulkPreview = null;
    adminState.selectedProductIds = new Set();
    openBulkConfirmButton.disabled = true;
    exportBulkPreviewButton.disabled = true;
    await Promise.all([loadProducts(), loadSections(), loadDiagnostics(), loadOperations()]);
  } catch (error) {
    if (bulkPreviewStatus) {
      bulkPreviewStatus.textContent = `执行未确认：${error.message}。可重试同一预览，系统不会重复执行。`;
    }
  } finally {
    adminState.bulkBusy = false;
    applyBulkButton.disabled = !adminState.lastBulkRequest;
    applyBulkButton.textContent = originalLabel;
  }
});
```

- [ ] **Step 7: 运行前端契约测试**

Run:

```powershell
node --test tests/browser/frontend-contracts.cjs
```

Expected: PASS；价格段映射正确，条件变化会让旧预览失效，重复点击只产生一次执行请求。

- [ ] **Step 8: 提交前端交互**

```powershell
git add src/moments_inventory/showcase_web/static/admin.js tests/browser/frontend-contracts.cjs
git commit -m "feat: implement CCD bulk pricing preview workflow"
```

### Task 7: 完成回归验证和发布手册

**Files:**
- Modify: `docs/ccd-release-runbook.md:40-48`

- [ ] **Step 1: 运行后台接口测试**

Run:

```powershell
python -m pytest tests/test_showcase_web_api_admin.py tests/test_showcase_web_bulk_transactions.py -q
```

Expected: PASS；价格边界、作用范围、统计、CSV、事务、幂等和撤销全部通过。

- [ ] **Step 2: 运行完整展示系统回归测试**

Run:

```powershell
python -m pytest tests/test_showcase_web*.py tests/test_cli_showcase_web.py -q
```

Expected: PASS；客户页、管理页、导入、图片、迁移和批量事务没有回归。

- [ ] **Step 3: 运行浏览器契约测试**

Run:

```powershell
node --test tests/browser/frontend-contracts.cjs
```

Expected: PASS；工作台结构、请求映射、预览失效、双击保护和草稿行为通过。

- [ ] **Step 4: 在候选端口验证真实页面**

先制作正式数据快照，再恢复到专用候选目录：

```powershell
python -m moments_inventory.cli showcase-db-backup --showcase-config config/showcase.yaml
$candidateSnapshot = Get-ChildItem -LiteralPath backup/showcase -Directory |
  Sort-Object LastWriteTime -Descending |
  Select-Object -First 1
$candidateDir = Join-Path 'tmp' ('candidate-bulk-price-' + (Get-Date -Format 'yyyyMMdd-HHmmss'))
python -m moments_inventory.cli showcase-db-restore `
  --snapshot $candidateSnapshot.FullName `
  --destination $candidateDir
$env:PYTHONPATH = "$PWD\src"
python -m moments_inventory.cli showcase-server `
  --showcase-config (Join-Path $candidateDir 'config/showcase.yaml') `
  --port 8898
```

Expected: 恢复工具创建带时间戳的候选目录，候选服务只读写恢复副本并监听 `127.0.0.1:8898`。

在 `http://127.0.0.1:8898/admin-xingxing` 验证：

1. 五个价格段的边界商品数量正确。
2. 已勾选、当前筛选结果和全部库存的范围摘要正确。
3. 修改条件后确认按钮立即失效。
4. 预览统计与 CSV 行数一致。
5. 已售和隐藏商品按选择条件处理。
6. 执行后操作记录摘要正确。
7. 撤销后价格和人工覆盖状态恢复。
8. 电脑和窄屏页面没有横向溢出，键盘焦点清楚可见。

- [ ] **Step 5: 更新发布手册验收入口**

在 `docs/ccd-release-runbook.md` 的验证入口前增加：

```markdown
## 批量改价验收

- 价格段边界固定为：`≤200`、`201～300`、`301～600`、`601～800`、`≥801`。
- 批量操作必须明确选择已勾选、当前筛选结果或全部库存。
- 正式执行前核对匹配、实际修改、不变和跳过数量，并导出完整 CSV 留档。
- 修改筛选或金额后必须重新生成预览；过期预览不能执行。
- 发布验证必须包含一次改价、一次撤销，以及一次版本冲突拒绝。
```

- [ ] **Step 6: 提交发布手册**

```powershell
git add docs/ccd-release-runbook.md
git commit -m "docs: add CCD bulk pricing release checks"
```

- [ ] **Step 7: 检查最终差异**

Run:

```powershell
git status --short
git log --oneline -8
git diff HEAD~7..HEAD --check
```

Expected: 只有本计划列出的代码、测试和发布手册发生变化；`git diff --check` 无输出。

## 完成标准

满足以下条件后，本计划可以结束：

1. 五个价格段和自定义区间均由后端校验。
2. 每次批量请求显式声明作用范围。
3. 默认只处理展示中、未售商品。
4. 页面区分匹配、修改、不变和跳过数量。
5. CSV 包含完整预览快照，而不是重新查询结果。
6. 重复提交不会重复加价。
7. 并发修改导致整个操作拒绝，不产生部分写入。
8. 改价、隐藏和显示操作都能在版本安全前提下撤销。
9. 发布手册包含候选端口验收步骤。
