# CCD 本地操作历史保留实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 本地 SQLite 中批量操作日志、撤销快照和相应幂等响应按滚动 90 天保留，并以有界、可重试的方式清理。

**Architecture:** 在现有迁移中为 `showcase_idempotency` 增加 UTC `created_at`，旧记录回填为迁移时刻以免立刻误删。仓储清理方法在事务中先检查整个原操作/撤销族均过期，再分批删快照、日志和过期幂等记录；管理员读取操作历史触发一次有限清理。

**Tech Stack:** Python 3.11、SQLite、FastAPI、pytest。

---

## 文件职责

- `src/moments_inventory/showcase_web/migrations.py`：本地 SQLite schema 版本 14，为幂等缓存增加时间戳并安全回填历史行。
- `src/moments_inventory/showcase_web/bulk_service.py`：批量执行缓存写入时保存 UTC 创建时间。
- `src/moments_inventory/showcase_web/repository.py`：操作族过期判定、有限快照清理与历史读取前的维护触发。
- `tests/test_showcase_web_migrations.py`：升级旧数据库及已有缓存的迁移回归。
- `tests/test_showcase_web_bulk_transactions.py`：保留期边界、事务、批量上限和商品现值不变。
- `tests/test_showcase_web_api_admin.py`：管理员历史读取触发清理，并仍需管理员认证。
- `docs/ccd-release-runbook.md`、`docs/ccd-admin-password.md`：说明历史/撤销期限与到期行为。

### Task 1：先锁定迁移和写入时间契约

**Files:**
- Modify: `tests/test_showcase_web_migrations.py`
- Modify: `src/moments_inventory/showcase_web/migrations.py`
- Modify: `src/moments_inventory/showcase_web/bulk_service.py`

- [ ] **Step 1: 写失败迁移测试**

在 `tests/test_showcase_web_migrations.py` 创建已应用版本 13 的旧 schema，插入一条四列 `showcase_idempotency` 记录，运行 `migrate(conn)`，断言列中含 `created_at`、旧记录时间戳非空且可以按新五列结构读取。

- [ ] **Step 2: 验证迁移测试先失败**

运行：`python -B -m pytest tests/test_showcase_web_migrations.py -q`

预期：新增断言因缺少 `created_at` 失败。

- [ ] **Step 3: 增加版本 14 迁移**

在 `migrations.py` 末尾为 `showcase_idempotency` 添加 `created_at text not null default ''`，将旧空值回填为迁移时的 UTC ISO 时间，再记录 schema version 14。迁移不读取业务数据库文件，只由测试临时数据库覆盖。

- [ ] **Step 4: 为幂等响应写入 UTC 时间**

在 `bulk_service.execute` 将 `INSERT INTO showcase_idempotency` 改为显式列名插入，并写入已生成的 `now`：

```python
conn.execute(
    '''INSERT INTO showcase_idempotency
       (idempotency_key, owner, request_hash, response_json, created_at)
       VALUES (?,?,?,?,?)''',
    (key, owner, fingerprint, json.dumps(result), now),
)
```

- [ ] **Step 5: 运行迁移与批量事务测试**

运行：`python -B -m pytest tests/test_showcase_web_migrations.py tests/test_showcase_web_bulk_transactions.py -q`

预期：全部通过，既有幂等重试结果保持一致。

### Task 2：实现原子、有界的过期清理

**Files:**
- Modify: `src/moments_inventory/showcase_web/repository.py`
- Modify: `tests/test_showcase_web_bulk_transactions.py`

- [ ] **Step 1: 写操作族保留期反例测试**

使用 pytest 临时 SQLite 仓储，插入三个隔离产品及操作数据：旧原操作+旧撤销操作、旧原操作+90 天内撤销操作、正好位于 cutoff 的操作；包含逐商品快照和商品当前价格。调用清理后断言仅第一组删除，边界组和新撤销组完整保留，所有产品价格/可见状态/版本均未改变。

- [ ] **Step 2: 运行新测试确认失败**

运行：`python -B -m pytest tests/test_showcase_web_bulk_transactions.py -k retention -q`

预期：仓储尚无清理方法，测试失败。

- [ ] **Step 3: 增加清理方法并包事务**

在 `SQLiteShowcaseRepository` 增加 `cleanup_expired_admin_operations(now: datetime | None = None, limit: int = 500) -> dict[str, int]`。UTC cutoff 固定为 `now - timedelta(days=90)`；将 limit 限定在 1–500。使用 `_lock`、`BEGIN IMMEDIATE`，只选取 `created_at < cutoff` 且其父操作和所有 `parent_operation_id` 子操作都早于 cutoff 的操作族。

- [ ] **Step 4: 分批删除快照、再删日志和缓存**

在同一事务中，最多选择 limit 条过期快照 `item_id` 并显式删除；仅对快照已清空且整个操作族已过期的操作删除日志。SQLite 版本无关紧要，使用参数绑定和 `IN` 占位符；不删除商品。按 `created_at < cutoff` 有界删除幂等缓存，返回 `{items, operations, idempotency}` 三个计数。异常时整个事务回滚。

- [ ] **Step 5: 覆盖批次上限、重试和故障回滚**

补测试：超过 limit 的快照多次调用后最终清空；第二次调用返回零且不出错；通过临时触发器让日志删除失败，断言同事务中的快照删除也回滚。

- [ ] **Step 6: 运行目标测试**

运行：`python -B -m pytest tests/test_showcase_web_bulk_transactions.py tests/test_showcase_web_migrations.py -q`

预期：全部通过。

### Task 3：管理员历史接口触发清理并记录保留规则

**Files:**
- Modify: `src/moments_inventory/showcase_web/api.py`
- Modify: `tests/test_showcase_web_api_admin.py`
- Modify: `docs/ccd-release-runbook.md`
- Modify: `docs/ccd-admin-password.md`

- [ ] **Step 1: 添加接口触发测试**

建立一条测试临时库内的过期操作族，通过认证管理员调用 `GET /api/admin/operations`，断言操作不再返回且日志/快照已删除；未认证请求仍返回 401 且不执行管理操作。

- [ ] **Step 2: 运行接口测试确认失败**

运行：`python -B -m pytest tests/test_showcase_web_api_admin.py -k operations_retention -q`

预期：旧接口不调用清理，过期操作仍可见。

- [ ] **Step 3: 在列历史前调用有界仓储清理**

在已通过 `require_admin` 保护的 `list_admin_operations` 路由中先执行 `repo.cleanup_expired_admin_operations()`，随后沿用现有 `list_admin_operations()` 响应结构；不新增匿名清理入口。

- [ ] **Step 4: 更新管理员文档**

在 `docs/ccd-release-runbook.md` 和 `docs/ccd-admin-password.md` 写明：历史与撤销快照按滚动 90 天保留；清理只发生在管理员读取历史时按批次推进；过期操作不可撤销；商品当前数据不受历史清理影响。

- [ ] **Step 5: 运行本地 CCD 管理测试**

运行：`python -B -m pytest tests/test_showcase_web_api_admin.py tests/test_showcase_web_bulk_transactions.py tests/test_showcase_web_migrations.py -q`

预期：全部通过。

### Task 4：本地验收与提交

**Files:**
- Review: 上述本地文件及新增测试

- [ ] **Step 1: 运行本地完整测试套件**

运行：`python -B -m pytest -q`

预期：全套通过；测试只使用临时/隔离数据。

- [ ] **Step 2: 检查变更**

运行：`git diff --check`、`git status --short`，确认没有真实数据库、备份、配置或媒体文件进入变更。

- [ ] **Step 3: 提交本地实现**

提交代码、测试和操作文档；不运行生产迁移或发布。
