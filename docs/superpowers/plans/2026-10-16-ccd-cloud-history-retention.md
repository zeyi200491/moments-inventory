# CCD Cloudflare 操作历史保留实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** Cloudflare D1 中批量操作族、撤销快照和幂等执行保护数据按滚动 90 天保留，并由现有定时维护入口安全分批清理。

**Architecture:** 在 `D1ShowcaseRepository.cleanupExpiredEphemeralRecords` 中扩展有界清理：确认整个父子操作族过期后，按每轮最多 100 条物理删除记录的共享预算分批删除状态、快照、执行结果、guard、owner 与操作日志；预估查询也采用有界候选和饱和计数。沿用 D1 batch 事务及现有 Cron 维护错误汇报。

**Tech Stack:** TypeScript、Cloudflare Workers、D1、Vitest。

---

## 文件职责

- `src/repositories/d1ShowcaseRepository.ts`：实现操作族 cutoff 判定、快照/日志/关联结果清理并回传计数。
- `src/services/r2Cleanup.ts`：组合并传播清理计数与失败状态。
- `src/index.ts`：把新计数写入已有结构化定时维护日志。
- `test/d1Repository.test.ts`：使用隔离的 SQLite 仿真数据库验证清理语义、级联和批次边界。
- `test/adminApi.test.ts`：验证现有 Cron 维护路径记录清理结果及错误。
- `docs/release-runbook.md`：说明 Cloudflare D1 的 90 天保留行为和撤销窗口。

### Task 1：扩展仓储清理契约和 D1 仿真测试

**Files:**
- Modify: `test/d1Repository.test.ts`
- Modify: `src/repositories/d1ShowcaseRepository.ts`

- [x] **Step 1: 写清理语义失败测试**

在 `test/d1Repository.test.ts` 使用现有临时 D1 仿真初始化三组日志和产品：完全过期操作族、过期父操作但 90 天内撤销的父子组、正好位于 cutoff 的父子组。插入 `showcase_admin_operation_items`、`showcase_bulk_operation_owners`、`showcase_bulk_operation_item_states`、guards 和 results；保存产品价格/可见性/版本快照。调用清理，断言仅过期快照和整族日志被删、关联数据无孤儿、其他两组全保留、产品行不变。

- [x] **Step 2: 运行目标测试确认失败**

运行：`npm exec -- vitest run test/d1Repository.test.ts -t 'operation retention'`

预期：当前方法不清理操作历史，新增断言失败。

- [x] **Step 3: 扩充清理结果类型**

将清理结果增加 `operationItems`、`operations`、`executionGuards`、`executionResults` 计数；保留 `adminSessions`、`customerSessions` 和 `previews` 字段。所有新增 SQL 使用 cutoff 和占位参数。

- [x] **Step 4: 实现整族过期判断与有界分批删除**

在 D1 batch 中选择早于 cutoff 的旧根操作；若任一子操作 `created_at >= cutoff`，则整族跳过。每轮共享最多 100 条物理行删除预算，计入 item state、快照、results、guards、owners 和操作日志；显式先删外键子行以避免级联绕过预算。候选家族及预算预估查询均有界，结果使用饱和计数。返回四类主表的 `meta.changes`。

- [x] **Step 5: 覆盖 cutoff 边界和批次重试**

新增超过批次上限的数据，重复调用后断言最终清空；再次调用无新增删除；制造较新 undo 子操作确保旧父操作及其关联结果仍保留。断言 D1 batch 失败会拒绝报告成功。

- [x] **Step 6: 运行仓储目标测试**

运行：`npm exec -- vitest run test/d1Repository.test.ts`

预期：文件内全部测试通过。

### Task 2：维护服务日志与失败传播

**Files:**
- Modify: `src/services/r2Cleanup.ts`
- Modify: `src/index.ts`
- Modify: `test/adminApi.test.ts`

- [x] **Step 1: 写定时维护结果合同测试**

扩展 `test/adminApi.test.ts` 已有 `worker.scheduled` 测试夹具，插入一组过期操作快照，运行 Cron 并断言结构日志/维护结果包含新增计数；另模拟仓储清理异常，断言 `ephemeralCleanupFailed=true` 并输出维护失败事件。

- [x] **Step 2: 运行 Cron 目标测试确认失败**

运行：`npm exec -- vitest run test/adminApi.test.ts -t 'scheduled.*cleanup|expired.*operation'`

预期：目前结果结构无操作历史计数，新增合同断言失败。

- [x] **Step 3: 传递各清理阶段计数**

更新 `ExpiredCleanupResult`、`cleanupExpiredRecords`、`processR2CleanupQueue` 的返回类型和每条返回路径，使清理成功时传出所有计数，异常时保持零计数并将 `failed` 设为 true；不得将异常吞成成功。

- [x] **Step 4: 扩展定时结构化日志**

在 `src/index.ts` 的成功/失败 `fields` 中加入四类操作历史计数。仅当有删除记录时输出成功维护日志，失败时继续输出 `scheduled_maintenance_failed`。

- [x] **Step 5: 运行维护和类型检查**

运行：`npm exec -- vitest run test/adminApi.test.ts && npm run typecheck`

预期：测试与 TypeScript 检查通过。

### Task 3：文档、完整验证和提交

**Files:**
- Modify: `docs/ccd-release-runbook.md`

- [x] **Step 1: 更新运维手册**

说明 D1 操作日志和撤销快照滚动保留 90 天，由既有 Cron 按上限清理；未满 90 天的父子操作族整体保留；过期操作不可撤销；日志字段可用于确认维护结果；本地 SQLite 仍为库存权威源。

- [x] **Step 2: 运行 Cloudflare 完整检查**

运行：`npm run typecheck`、`npm test -- --maxWorkers=1`、`npm run test:smoke`、`npm run verify:repo`。默认并行 `npm run check` 中少数资源密集测试触发超时，已逐项重跑通过；单 worker 全量测试通过。

预期：TypeScript、单元、冒烟和仓库扫描全部通过。

- [x] **Step 3: 检查变更并提交 Cloudflare 实现**

运行：`git diff --check`、`git status --short`；确认无 wrangler secrets、生产配置或 D1 数据文件变更后，提交代码、测试和文档。不执行 `npm run deploy`，不访问正式 D1/R2。
