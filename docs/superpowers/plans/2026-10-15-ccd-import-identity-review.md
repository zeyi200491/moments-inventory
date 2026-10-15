# CCD 导入身份复核队列实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在本地 CCD 管理后台加入可恢复的逐行导入身份复核队列，只有管理员确认后才以一个 SQLite 事务提交商品、图片、身份别名、导入日志和库存修订号。

**Architecture:** 继续复用现有工作簿解析、商品导入归一化和 SQLite 仓储。增加批次/行暂存和来源身份别名表；后台 API 负责上传、读取、逐行决定、提交、放弃，前端负责断点恢复与差异审核。提交阶段在单连接事务内重新校验唯一键、版本和全量范围，任何冲突整体回滚。

**Tech Stack:** Python 3.11、FastAPI、Pydantic、SQLite、现有原生 JavaScript 管理页面、pytest。

---

## 文件结构与职责

- 修改 `src/moments_inventory/showcase_web/migrations.py`：增加批次/行/身份别名持久化表及索引，保持可重复迁移。
- 修改 `src/moments_inventory/showcase_web/models.py`：定义导入复核 DTO、批次状态和决定枚举。
- 修改 `src/moments_inventory/showcase_web/repository.py`：实现暂存生命周期、候选查询、别名唯一约束、CAS 校验和原子提交。
- 修改 `src/moments_inventory/showcase_web/importer.py`：复用 Excel 校验/解析入口，产出复核行与来源范围元数据；不再直接提交后台上传批次。
- 新建 `src/moments_inventory/showcase_web/import_review_service.py`：协调批次预览、人工决定验证、候选提示、摘要计算、幂等提交和放弃。
- 修改 `src/moments_inventory/showcase_web/api.py`：添加受管理员会话保护的批次接口和请求/响应模型。
- 修改 `src/moments_inventory/showcase_web/static/admin.html`：增加工作簿上传、待处理批次恢复、逐行身份选择、提交差异与放弃控件。
- 修改 `src/moments_inventory/showcase_web/static/admin.js`：实现队列 API 调用、状态恢复、行级决定编辑、冲突和幂等重试提示。
- 修改 `src/moments_inventory/showcase_web/static/admin.html`：复用页面内现有样式区补充复核队列的窄屏布局、差异状态和操作反馈样式。
- 新建 `tests/test_showcase_web_import_review.py`：覆盖服务、身份别名、事务回滚、并发版本冲突、重试和生命周期。
- 修改 `tests/test_showcase_web_migrations.py`、`tests/test_showcase_web_api_admin.py`：验证迁移与管理员接口授权/数据隔离。
- 修改 `tests/browser/frontend-contracts.cjs`：锁定管理页关键 DOM/API 契约，确保客户页面不暴露来源身份复核字段。
- 修改 `docs/ccd-import-backup-restore.md`：说明暂存批次保留/清理与数据库备份恢复行为。

## 约束与数据契约

- 状态仅为 `pending`、`committed`、`discarded`；终态批次不可再改决定。
- 决定仅为 `link`、`create`、`skip`。一个批次中的来源键不得重复；一个目标商品不得被两行重复认领；被其他商品当前键或别名占用的键不得重绑。
- 精确 `source_product_key` 或精确已确认别名只生成自动建议；管理者仍须明确确认每一行。型号/品牌/价格/图片相似只生成候选，绝不自动决定。
- `link` 保留目标 `product_id`、`public_id`、管理员覆盖、已售状态、图片区关系和栏目关系；把新来源键追加为别名。无来源键行也允许人工关联，但不建立空别名。
- 每行记录解析快照、候选摘要、决定、目标商品 ID 和目标 `row_version`；不保存工作簿原始副本，不返回这些内容给公开 API。
- 全量批次的缺失集合基于完整解析后的所有行计算；`skip` 不写商品但不能被误当成文件不完整。缺失商品沿用 `missing` 人工复核策略，不自动隐藏。
- API 的提交幂等键在批次范围唯一；同键成功重试返回同一提交结果。所有持久化数据留在本地 SQLite，Cloudflare/D1 不增加写能力。

### Task 1：迁移和领域模型

**Files:**
- Modify: `src/moments_inventory/showcase_web/migrations.py`
- Modify: `src/moments_inventory/showcase_web/models.py`
- Test: `tests/test_showcase_web_migrations.py`

- [ ] **Step 1: 为新迁移编写失败测试**

新增测试迁移数据库并断言存在 `showcase_import_review_batches`、`showcase_import_review_rows`、`showcase_source_identity_aliases`；断言别名 `(source_scope, source_key)` 唯一，并确认重复调用 `migrate()` 不改变已有批次数据。

- [ ] **Step 2: 运行迁移测试确认失败**

运行：`python -m pytest tests/test_showcase_web_migrations.py -q`
预期：新表/唯一约束相关断言失败。

- [ ] **Step 3: 增加迁移与模型**

批次表保存 `batch_id`、`status`、`scope`、`mode`、`complete`、`source_path`、`source_fingerprint`、解析总行数、缺失数量、创建/提交时间、`idempotency_key` 与最终 JSON 结果；行表按 `(batch_id,row_number)` 唯一保存解析商品字段 JSON、来源键、决定、目标 ID、目标版本和候选 JSON；别名表以 `(source_scope,source_key)` 为主键并外键指向商品。只允许三种批次状态和三种决定，由服务校验，迁移用 CHECK 限制状态值。

- [ ] **Step 4: 重跑迁移测试**

运行：`python -m pytest tests/test_showcase_web_migrations.py -q`
预期：全部通过，既有迁移回归不变。

- [ ] **Step 5: 提交本任务**

提交信息：`feat: add CCD import review persistence`。

### Task 2：解析、候选建议与批次生命周期

**Files:**
- Modify: `src/moments_inventory/showcase_web/importer.py`
- Create: `src/moments_inventory/showcase_web/import_review_service.py`
- Modify: `src/moments_inventory/showcase_web/repository.py`
- Test: `tests/test_showcase_web_import_review.py`

- [ ] **Step 1: 编写服务失败测试**

使用临时 SQLite 与合成工作簿测试：创建批次不改变商品；同键商品/别名显示精确关联候选；同型号不同来源键只显示相似候选但 `decision` 为空；无稳定键可人工创建/关联；逐行保存决定后重新读取仍存在；放弃批次不改变商品。

- [ ] **Step 2: 运行失败测试**

运行：`python -m pytest tests/test_showcase_web_import_review.py -q`
预期：因复核服务及持久化方法不存在而失败。

- [ ] **Step 3: 实现批次创建、读取和决定保存**

调用现有 `read_showcase_workbook` / 归一化路径，在验证通过后写入 pending 批次和行快照；来源键精确映射与别名映射生成建议，其他候选使用现有 admin 商品搜索的规范字段生成提示；每次决定保存时验证批次仍为 pending、行号存在、决定目标有效并捕获目标 `row_version`。接口刷新后根据数据库恢复，不依赖浏览器内存。

- [ ] **Step 4: 验证生命周期测试**

运行：`python -m pytest tests/test_showcase_web_import_review.py -q`
预期：批次准备、候选显示、逐行决定、放弃与恢复测试通过。

- [ ] **Step 5: 提交本任务**

提交信息：`feat: stage CCD imports for identity review`。

### Task 3：事务提交、身份别名和并发冲突

**Files:**
- Modify: `src/moments_inventory/showcase_web/import_review_service.py`
- Modify: `src/moments_inventory/showcase_web/repository.py`
- Modify: `tests/test_showcase_web_import_review.py`
- Modify: `tests/test_showcase_web_import_reconciliation.py`

- [ ] **Step 1: 写事务和冲突失败测试**

覆盖新建、关联旧商品、跳过；关联后保留 `public_id`、人工价格/文案/显隐覆盖、已售、图片与栏目关系；同批重复键、跨商品别名冲突、目标重复认领、缺少决定、陈旧 `row_version` 均拒绝提交；注入中途异常验证商品、图片、别名、日志、修订号和批次状态全回滚；同幂等键重试返回同一结果。

- [ ] **Step 2: 运行测试确认缺少原子提交**

运行：`python -m pytest tests/test_showcase_web_import_review.py tests/test_showcase_web_import_reconciliation.py -q`
预期：新的提交场景失败。

- [ ] **Step 3: 实现唯一事务提交**

仓储层使用现有 SQLite 连接事务模式，在写入前对全部行决定、重复来源键、当前键/别名占用、唯一目标和捕获版本重新校验；成功后按行执行复用现有导入写入字段策略、写入来源别名/图片关联/导入日志，依据完整来源集更新 `missing` 标记并递增库存修订号，最后保存 committed 状态与幂等结果。异常时抛出有类型的冲突错误或让事务回滚，不吞错误、不部分提交。

- [ ] **Step 4: 验证事务与 A→B→A 回归**

运行：`python -m pytest tests/test_showcase_web_import_review.py tests/test_showcase_web_import_reconciliation.py -q`
预期：所有新旧导入协调测试通过。

- [ ] **Step 5: 提交本任务**

提交信息：`feat: commit reviewed CCD imports atomically`。

### Task 4：管理员 API 和权限边界

**Files:**
- Modify: `src/moments_inventory/showcase_web/api.py`
- Modify: `tests/test_showcase_web_api_admin.py`
- Modify: `tests/test_showcase_web_api_public.py`

- [ ] **Step 1: 写 API 失败测试**

使用现有 API 测试客户端验证未登录访问所有复核路由返回 401/403；管理员可以上传、查询批次、保存决定、提交、放弃；错误工作簿返回可定位行号而不创建可提交批次；客户商品/设置/图片 API 的响应不包含 `source_key`、候选或复核字段。

- [ ] **Step 2: 运行 API 测试确认路由缺失**

运行：`python -m pytest tests/test_showcase_web_api_admin.py tests/test_showcase_web_api_public.py -q`
预期：新路由用例失败。

- [ ] **Step 3: 增加管理员会话路由**

增加 `POST /api/admin/import-review/batches`（上传并创建批次）、`GET /api/admin/import-review/batches/{batch_id}`（读取）、`PUT /api/admin/import-review/batches/{batch_id}/rows/{row_number}`（保存单行决定）、`POST /api/admin/import-review/batches/{batch_id}/commit`（含 `idempotencyKey`）、`DELETE /api/admin/import-review/batches/{batch_id}`（放弃）。每个端点都声明 `Depends(require_admin_session)` 并以 Pydantic 白名单响应模型返回数据；提交冲突映射到 409，并保留 pending 批次。

- [ ] **Step 4: 重跑 API 权限与响应测试**

运行：`python -m pytest tests/test_showcase_web_api_admin.py tests/test_showcase_web_api_public.py -q`
预期：授权、隔离、错误定位和提交行为通过。

- [ ] **Step 5: 提交本任务**

提交信息：`feat: expose admin CCD import review API`。

### Task 5：后台工作流与刷新恢复

**Files:**
- Modify: `src/moments_inventory/showcase_web/static/admin.html`
- Modify: `src/moments_inventory/showcase_web/static/admin.js`
- Modify: `src/moments_inventory/showcase_web/static/admin.html`（复用页面内样式区）
- Test: `tests/browser/frontend-contracts.cjs`

- [ ] **Step 1: 写前端契约失败测试**

增加契约断言：后台有工作簿上传/来源范围选项、pending 批次列表、每行 link/create/skip 选择、完整导入摘要、提交/放弃按钮；代码调用上述 5 个路由；公开 `index.html` 与商品详情页不载入复核字段。

- [ ] **Step 2: 运行前端契约确认 UI 缺失**

运行：`node tests/browser/frontend-contracts.cjs`
预期：新增导入复核控件断言失败。

- [ ] **Step 3: 实现可恢复的管理界面**

上传成功后将 `batch_id` 放入管理页状态并刷新批次详情；页面加载时恢复最近 pending 批次；逐条呈现来源标识、型号/品牌、价格、图像摘要、候选及目标版本，允许关联/新建/跳过；顶部显示新增/更新/跳过/缺失计数和待决定数；提交前展示差异确认，提交按钮在未完成决定时禁用；409 显示冲突行并提供刷新详情入口；网络响应丢失时使用同一幂等键查询批次或重试；放弃要求二次确认。所有用户文本用中文并按当前 admin 页面 XSS 安全方式转义。

- [ ] **Step 4: 验证前端契约**

运行：`node tests/browser/frontend-contracts.cjs`
预期：全部前端契约通过。

- [ ] **Step 5: 提交本任务**

提交信息：`feat: add recoverable CCD import review UI`。

### Task 6：文档、全量验证和审查

**Files:**
- Modify: `docs/ccd-import-backup-restore.md`
- Test: `tests/test_showcase_web_import_review.py`
- Test: `tests/test_showcase_web_api_admin.py`
- Test: `tests/browser/frontend-contracts.cjs`

- [ ] **Step 1: 更新运维/恢复说明**

说明待复核批次位于本地 SQLite、不会写入 Cloudflare、备份含 pending 行和决定、恢复后管理员可继续；已提交/放弃批次只读；导入原文件不会作为附件保存；并注明只对临时 SQLite 测试。

- [ ] **Step 2: 跑 CCD 目标测试**

运行：`python -m pytest tests/test_showcase.py tests/test_showcase_web_importer.py tests/test_showcase_web_import_reconciliation.py tests/test_showcase_web_import_review.py tests/test_showcase_web_api_admin.py tests/test_showcase_web_api_public.py tests/test_showcase_web_migrations.py -q`
预期：全部通过。

- [ ] **Step 3: 跑浏览器契约和相关静态检查**

运行：`node tests/browser/frontend-contracts.cjs` 与仓库已配置的 Python lint/类型检查命令。
预期：命令退出码为 0；如项目没有独立 lint/类型检查命令，以现有 pytest 和前端契约为验证范围。

- [ ] **Step 4: 检查变更和工作树**

运行：`git diff --check`、`git status --short`、`git diff --stat`；确认只改计划列出的 CCD 文件，不含数据库、凭据或生成数据。

- [ ] **Step 5: 提交文档与最终核验**

提交信息：`docs: document CCD import review recovery`; 再运行 CCD 目标测试与 `git status --short`，汇总提交号与已知边界。

## 设计覆盖自检

- 上传校验和未改库存：Task 2、Task 4。
- 精确键/别名建议与相似候选仅提示：Task 2、Task 5。
- link/create/skip、全量缺失策略、同目标和同键冲突：Task 2、Task 3。
- 提交前来源/版本/范围校验、事务回滚、幂等：Task 3。
- API 管理员会话与公开数据隔离：Task 4。
- 刷新恢复、提交确认、失败重试和放弃：Task 5。
- 备份恢复、自动化临时库验证与禁止 Cloudflare 写入：Task 6。

## 实施边界

- 在 `codex/ccd-phase1-correctness` CCD 源工作树中实施并逐任务提交。
- 只用临时 SQLite、虚构工作簿和虚构图片做验证；不得访问真实业务数据库、Cloudflare 账号或外部发布服务。
- 浏览器真实登录验收和生产数据身份复核属于外部人工验收；本计划内完成自动化验证后再明确列出其状态。

