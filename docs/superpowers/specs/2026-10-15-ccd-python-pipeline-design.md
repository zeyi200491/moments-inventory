# CCD 展示网页 Python 全流程编排设计

## 目标

在本地 CCD Python 项目提供一个统一的 `ccd-pipeline` 命令，将朋友圈库存刷新、人工导入复核、本地 SQLite 更新、样片与商品媒体核验、Cloudflare 发布包生成、远端 dry-run 和可选 apply 纳入同一条可追踪流程。每个阶段有持久状态和内容摘要；失败、人工复核或需确认的写操作会暂停，后续只能在输入与目标身份仍匹配时继续。

## 方案选择

1. **本地 Python CLI 编排（采用）**：编排入口放在本地 CCD 项目，显式传入 Cloudflare 仓库路径，复用两端已有的刷新、复核、导出和同步实现。优点是库存权威源 SQLite 与状态入口同处本地项目；缺点是需要验证两个仓库边界，并要求操作员显式配置 Cloudflare 工作树。
2. **Windows 批处理串联现有命令**：改动少，适合单台 Windows；但阶段状态、失败定位、跨阶段续跑和测试注入会继续分散，不能满足完整追踪目标。
3. **Cloudflare 仓库做入口**：便于调用导出与同步工具；但它无法作为朋友圈刷新、导入复核和本地 SQLite 的权威编排入口，会把本地数据流程和云端目标混在一起。

## 架构与范围

- 编排器属于本地 Python CCD 应用，命令名为 `ccd-pipeline`，并可通过 `python -m moments_inventory.cli ccd-pipeline ...` 使用。
- 编排器只允许本地正式环境门禁确认的 CCD 工作树和 SQLite 路径。Cloudflare 仓库通过必填 `--cloud-repo` 显式指定；启动时校验目录结构、预期 Git 仓库标识、同步脚本和导出脚本存在，不自动查找或切换到 AI 工作台。
- 复用现有 `run_full_mode.bat`、库存合并逻辑、本地复核服务、`export-local-showcase.py` 和 `sync-cloudflare.mjs`。不维护另一份导入、媒体映射或 Cloudflare 同步逻辑。
- 本地 SQLite 仍是唯一可写库存权威。Cloudflare D1 仅接收本地快照；编排器不会将云端数据写回 SQLite。
- 真实远端 apply 必须同时满足显式 `--apply`、已通过配置与 account 门禁、已完成 package dry-run，以及操作员确认本次目标。默认 `run` 与 `resume` 只做本地流程和远端 dry-run，不调用远端写操作。

## 阶段和数据流

1. **预检**：验证正式 CCD 工作树、配置解析的数据库/媒体根、当前 Git 分支与工作区策略、Cloudflare 仓库路径、所需命令和输出目录可写；把解析后的路径和环境 ID 写入运行状态，敏感配置值不落盘。
2. **库存刷新**：调用正式全量刷新入口，要求生成 `output/全量当前库.xlsx`；记录源文件 SHA-256、大小和修改时间。命令失败或产物缺失时停止，不进入后续阶段。
3. **人工表合并与导入复核**：执行现有展示表合并并生成持久复核批次。身份不确定、来源缺失、价格异常和低置信关联由管理员在已有后台复核队列处理；流程显示批次 ID 和管理页地址，并等待批次完成。没有任何“自动猜测后继续”的路径。
4. **提交到本地 SQLite**：只有复核批次所有行均有明确决定且版本检查通过时，才经既有单事务复核提交逻辑写入 SQLite。写入前先在运行状态记录数据库路径、批次 ID、幂等键和预期 revision；重复续跑查询批次结果，不生成新的导入身份。
5. **媒体与发布包检查**：核验商品图片、样片引用及 Cloudflare 导出器要求的权威媒体根；调用现有导出器生成发布包。只有 `READY`、manifest、媒体摘要和 verification 全部通过，流程才进入 dry-run。
6. **Cloudflare dry-run**：调用 Cloudflare 仓库同步脚本默认模式，显式传入包路径、D1 数据库名、R2 桶名和配置；保存 stdout 摘要、目标指纹和 package hash。dry-run 结果不等同于线上已发布。
7. **可选 apply 与发布验收**：仅带 `--apply` 进入远端写入；复用同步器的租约、维护窗口、断点 state 和远端批次凭据。同步返回成功并检查发布后的就绪状态后，才将运行标记为 `published`。任何失败都保留 Cloudflare 维护状态的既有规则，并将运行标记为失败或结果未知，绝不显示成功。

## 阶段状态与恢复

- 每次运行分配随机 `run_id`，状态文件写到权威 CCD 环境的 `output/ccd-pipeline/runs/<run_id>.json`，以临时文件加原子替换持久化。文件权限尽可能限制为当前用户可读写。
- 状态记录 schema 版本、阶段、状态（pending/running/paused/succeeded/failed/unknown）、时间、输入文件路径与 hash、产物路径与 hash、目标指纹、复核批次 ID、幂等键和脱敏错误摘要。不得记录客户口令、管理员口令、cookie、token、Cloudflare secret 或完整环境变量。
- `status --run-id` 只读展示每一阶段结果和下一条允许的命令。`resume --run-id` 先重新验证工作树、数据库、源文件和 Cloudflare 目标；已完成阶段仅在其输出 hash 仍匹配时跳过。输入变化后不允许沿用旧进度，需显式创建新 run。
- 复核阶段属于正常暂停，不是失败；人工完成队列后 resume 会核对原 batch ID 和数据库 revision。提交结果未知时先查询批次日志/操作结果，不创建新批次。
- Cloudflare apply 的结果未知时保留相同发布包、配置、account、远端 state 与幂等批次身份；交由现有同步器进行远端 marker 核对和维护窗口恢复，禁止换新 package 自动重试。

## 错误与安全边界

- 任意阶段的非零退出、缺少产物、hash 不符、环境身份变化或版本冲突都停止后续阶段，并保存脱敏诊断。失败阶段可以在输入完全相同、错误条件消除后恢复。
- “已完成”仅指本地源刷新、复核提交、包生成、dry-run 或远端验收各自实际完成；不能把上游脚本退出码等同于客户页已更新。
- 命令通过参数数组调用，不使用 `shell=True` 或拼接密码命令行。刷新入口若依赖 Windows batch，只在 Windows 上调用 `cmd.exe /d /s /c` 的受控入口；其他系统明确报平台不支持，不伪装成成功。
- 远端发布不自动部署 Worker；部署配置验证、Worker 部署与域名/缓存/WAF 预发布验收仍按 Cloudflare 发布手册单独执行。编排器只做经 `sync-cloudflare.mjs --apply` 授权的数据快照同步。
- 此功能不会触碰真实 SQLite、D1、R2 或生产站点的验证环境；实现验收使用临时 SQLite、伪造刷新命令和 fake Wrangler CLI。

## 验收标准

1. `--help` 展示 `run`、`status`、`resume` 及其必需参数；不存在隐式 Cloudflare 仓库路径或隐式 apply。
2. 缺失正式配置、数据库路径错误、路径越界、Cloudflare 仓库错误或工具缺失时，预检失败且不运行刷新、导入、导出或远端命令。
3. 每阶段成功后都有原子状态记录及输入/输出 hash；模拟每个阶段中断后，status 能定位停点，resume 只重做可安全重做阶段。
4. 复核未完成时流程停在 paused；旧批次或旧 row version 不可提交；恢复后不得重复写库存或新增重复 import log。
5. 刷新成功但导入失败、导出媒体校验失败、dry-run 失败等场景都不会调用 apply，也不会报告已发布。
6. 默认流程和所有测试都不会访问真实 Cloudflare account、D1、R2 或生产站点；只有明确 `--apply` 才进入现有同步器的受保护远端流程。
7. apply 成功只有在同步器完整验收并返回可核验结果后才把运行终态记为 `published`；超时、断连或返回不完整都记录为 `unknown` 并要求用原 run/package/state 核查。
8. 文档说明流程阶段、人工复核点、状态目录、失败恢复、明确禁止的隐式操作及与两套仓库/AI 工作台的边界。
