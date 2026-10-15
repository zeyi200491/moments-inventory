# CCD 展示网页 Python 全流程实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**目标：** 在本地 CCD Python 应用实现可审计、可暂停续跑的 `ccd-pipeline`，串联库存刷新、管理端人工导入复核、媒体包生成与 Cloudflare 同步预检，并确保只有显式 `--apply` 才可能触发远端写入。

**架构：** 新增独立的 pipeline 编排、状态仓库、命令执行与 Cloudflare 边界模块；复用现有导入复核服务、导出器和 Cloudflare 同步脚本。持久化状态采用原子 JSON 文件，续跑前重新校验工作树、输入摘要、SQLite 路径和 Cloudflare 目标身份。

**技术栈：** Python 3.11、argparse、SQLite、JSON、SHA-256、pytest；Windows 全量刷新通过受控 `cmd.exe` 启动现有批处理；外部命令以参数数组运行。

---

## 文件结构与责任

- 新建 `src/moments_inventory/ccd_pipeline.py`：阶段状态机、`run/status/resume` 用例、验证已完成阶段及控制暂停/失败/未知结果。
- 新建 `src/moments_inventory/ccd_pipeline_state.py`：运行状态 schema、原子读写、摘要与脱敏错误格式。
- 新建 `src/moments_inventory/ccd_pipeline_commands.py`：正式路径预检、参数数组子进程执行、超时和退出码处理；为测试注入命令执行器。
- 修改 `src/moments_inventory/showcase_web/repository.py`：按稳定来源标签查找任意状态的复核批次，修复“创建批次成功但状态文件尚未落盘”时的恢复窗口。
- 修改 `src/moments_inventory/cli.py`：添加 `ccd-pipeline run/status/resume` 参数与分发，不改变既有命令行为。
- 新建 `tests/test_ccd_pipeline_state.py`：状态原子保存、摘要校验、敏感字段过滤与损坏文件行为。
- 新建 `tests/test_ccd_pipeline.py`：阶段顺序、暂停恢复、输入变更、失败停止、apply 门禁和未知结果。
- 修改 `tests/test_cli_showcase_web.py` 或新建 `tests/test_cli_ccd_pipeline.py`：命令行帮助、必填 Cloudflare 仓库路径及状态/运行调用。
- 新建 `docs/ccd-python-pipeline.md`：操作步骤、后台复核、续跑与失败处理、状态位置、远端安全边界。
- 修改 `README.md` 与 `docs/ccd-release-runbook.md`：增加入口索引和正式发布流程链接。

## Task 1：持久运行状态与摘要校验

**文件：** `src/moments_inventory/ccd_pipeline_state.py`、`tests/test_ccd_pipeline_state.py`

- [x] **步骤 1：先写状态文件原子写入测试**

测试创建 `tmp_path/output/ccd-pipeline/runs/run-a.json`；保存时先写同目录临时文件再 `os.replace`；重新加载内容相同，目录中不残留临时文件。

- [x] **步骤 2：运行测试并确认按预期失败**

运行：`pytest tests/test_ccd_pipeline_state.py -q`。预期因目标模块尚不存在而失败。

- [x] **步骤 3：实现最小状态仓库**

定义 `create_run(environment, target)`、`load_run(run_id)`、`save_run(run_state)` 和 `sha256_file(path)`。状态含 `schema_version`、`run_id`、`created_at`、`updated_at`、`environment`、`target`、`current_stage`、`status`、`stages`；状态只写入 JSON 原生类型。

- [x] **步骤 4：测试哈希校验与敏感字段拒绝**

增加输入文件摘要测试；状态递归字段名命中 password/token/cookie/secret/authorization 时保存失败，错误信息不得包含字段值。读取损坏 JSON 要返回可读 `PipelineStateError`，不得重置或覆盖损坏状态。

- [x] **步骤 5：运行状态测试**

运行：`pytest tests/test_ccd_pipeline_state.py -q`。预期全部通过。

## Task 2：安全预检和外部命令执行器

**文件：** `src/moments_inventory/ccd_pipeline_commands.py`、`tests/test_ccd_pipeline.py`

- [x] **步骤 1：先写预检拒绝测试**

用临时目录创建不完整的 Cloudflare repo，调用 `validate_preflight(...)`，断言在执行器记录到任何调用前抛出 `PipelinePreflightError`；为正式路径配置测试提供临时根和显式允许的测试模式参数，不读取正式数据库。

- [x] **步骤 2：运行单测确认预期失败**

运行：`pytest tests/test_ccd_pipeline.py::test_preflight_rejects_invalid_cloud_repo_before_commands -q`。预期缺少被测函数。

- [x] **步骤 3：实现预检与命令执行**

`validate_preflight` 调用既有 `scripts/verify_showcase_environment.py::verify_showcase_config` 正式门禁，再校验 CCD 项目标识/目录、`load_showcase_settings` 解析出的数据库和媒体根、输出目录可写、Cloudflare Git 根目录和项目名、配置以及导出/同步脚本。目标指纹包含 Git HEAD 与 Wrangler 配置、导出器、同步器和配置验证脚本摘要。禁止通过自动搜索选仓库。`run_command(argv, cwd, timeout)` 使用 `subprocess.run(list(argv), shell=False, capture_output=True, text=True)`；错误只保留清洗后的有限尾部摘要。

- [x] **步骤 4：验证命令参数边界**

测试断言执行器以参数数组运行并保留空格路径；超时记录为未知结果；输出脱敏不泄漏环境里的 token/secret；拒绝空仓库参数和越界目标。

- [x] **步骤 5：运行预检与命令测试**

运行：`pytest tests/test_ccd_pipeline.py -q`。预期相关测试全部通过。

## Task 3：阶段编排、人工复核暂停与安全续跑

**文件：** `src/moments_inventory/ccd_pipeline.py`、`tests/test_ccd_pipeline.py`

- [x] **步骤 1：先写完整阶段顺序测试**

注入假的阶段适配器，期望顺序为 `preflight → inventory_refresh → workbook_merge → import_review → local_commit_check → media_export → cloud_dry_run`；未提供 `apply=True` 时不得出现 Cloudflare apply 或远端验收调用。

- [x] **步骤 2：运行测试确认预期失败**

运行：`pytest tests/test_ccd_pipeline.py::test_run_stops_at_review_and_does_not_apply_by_default -q`。预期缺少 pipeline 实现。

- [x] **步骤 3：实现新建运行与人工复核暂停**

实现 `PipelineRunner.run(options)`。库存刷新在 Windows 调用项目根 `run_full_mode.bat`；检查 `output/全量当前库.xlsx` 并记录 hash。运行既有 `showcase-merge` 逻辑生成手工库存表；基于工作簿字节调用 `create_import_review_batch(repository, content, source_scope="default", mode="incremental", source_path=...)` 创建复核批次。保存 batch ID 后返回 `paused`，打印 `http://127.0.0.1:8899/admin-xingxing` 和复核批次 ID；绝不在后台自动作决定或提交。

- [x] **步骤 4：实现恢复后批次核验**

`resume(run_id)` 重新校验环境指纹、刷新表 hash、合并表 hash、DB 解析路径、Cloudflare 仓库身份及先前产物 hash。使用 `SQLiteShowcaseRepository` 查询原 batch ID：pending 时继续暂停；committed 时记录正式导入结果并进入后续阶段；状态文件缺失 batch ID 时，通过 `source_label=CCD pipeline <run_id>` 查询原批次并要求唯一；不存在、重复批次、失败、版本冲突或来源变化时停止，不创建新批次。后台原有提交 API 负责批次幂等提交，编排器只观察原批次状态。

- [x] **步骤 5：实现导出、dry-run、apply 门禁和 unknown**

调用既有 `export-local-showcase.py` 生成包并核对 `READY`、manifest、媒体验证文件与 hash；调用 `sync-cloudflare.mjs` 默认 dry-run，显式传入 package、配置、D1 名称和 R2 桶名。apply 分支必须要求 `--apply`，再调用 `verify-deploy-config.mjs` 完成 account/config 验证，并只通过现有 `sync-cloudflare.mjs --apply`；不部署 Worker。超时、断连或输出不完整写入 `unknown`，续跑只允许以相同 package hash 和 target fingerprint 恢复。dry-run 本身不声称校验了远端账号。

- [x] **步骤 6：覆盖每阶段失败与输入改变**

增加测试：任一阶段失败则无后续调用；已完成阶段 hash 改变时禁止跳过；新鲜状态从断点安全恢复；错误摘要无秘密；Cloudflare dry-run 失败时 apply 调用次数为零；远端输出不完整记 unknown；单纯 status 不触发任何副作用。

- [x] **步骤 7：运行编排测试**

运行：`pytest tests/test_ccd_pipeline.py -q`。预期所有阶段状态和门禁测试通过。

## Task 4：命令行接口

**文件：** `src/moments_inventory/cli.py`、`tests/test_cli_ccd_pipeline.py`

- [x] **步骤 1：先写 CLI 解析与门禁测试**

断言 `python -m moments_inventory.cli ccd-pipeline --help` 提供 `run`、`status`、`resume`；run/resume 都必须显式传 `--cloud-repo`；run 支持布尔 `--apply`，默认 false；status 需要 `--run-id`。

- [x] **步骤 2：运行 CLI 测试确认失败**

运行：`pytest tests/test_cli_ccd_pipeline.py -q`。预期子命令尚未注册。

- [x] **步骤 3：添加 parser 和 CLI 分发**

在 `build_parser()` 增加 `ccd-pipeline` 子命令及 `run/status/resume`；run/resume 参数包含必填 `--cloud-repo`、可选 `--showcase-config`、可选 `--apply`。主分发只调用 `PipelineRunner`；pipeline 异常打印一行脱敏中文诊断并返回非零退出码。

- [x] **步骤 4：运行 CLI 与既有 parser 回归测试**

运行：`pytest tests/test_cli_ccd_pipeline.py tests/test_cli_showcase_web.py -q`。预期新接口通过且既有 CCD CLI 行为不变。

## Task 5：操作手册、静态检查与发布边界

**文件：** `docs/ccd-python-pipeline.md`、`README.md`、`docs/ccd-release-runbook.md`

- [x] **步骤 1：撰写使用手册**

给出本地预检命令、默认 `run` 命令、后台逐条人工复核步骤、`status` 与 `resume` 命令、apply 前要求、状态文件路径、每类暂停/失败/未知结果恢复方式。示例中使用明确路径占位，不写真实口令或 Cloudflare secrets。

- [x] **步骤 2：明确解释 dry-run 限制和无自动部署**

注明 dry-run 不验证账号、D1/R2 线上权限或远端内容；显式 apply 仍只做受保护的数据同步，不自动部署 Worker/域名/WAF，也不表示客户页面验收成功。

- [x] **步骤 3：运行全量相关验证**

运行：`pytest tests/test_ccd_pipeline_state.py tests/test_ccd_pipeline.py tests/test_cli_ccd_pipeline.py tests/test_cli_showcase_web.py -q`，随后运行本地 Python 项目完整测试套件。所有外部命令均使用临时工具桩，测试不得调用真实 Windows 全量刷新、Cloudflare/Wrangler、D1、R2 或生产网址。

- [x] **步骤 4：检查变更和安全字符串**

运行：`git diff --check`、`git status --short`、`rg -n "password|token|cookie|secret|authorization" src/moments_inventory/ccd_pipeline*.py tests/test_ccd_pipeline*.py`；检查实现里没有凭据常量、`shell=True`、隐式 Cloudflare 路径和默认 apply。

- [x] **步骤 5：提交本地功能分支**

将新增源码、测试和必要文档提交到当前 `codex/ccd-phase1-correctness` 分支；保留状态文件、构建包、缓存和真实数据在仓库外。完成后按用户既有要求将整改继续推送 GitHub 前，先确认远端分支状态并只推送明确列出的提交。

## 设计覆盖自审

- 唯一本地写源与路径隔离：Task 2、Task 3。
- 正式工作树路径门禁与 Cloudflare 目标/脚本摘要：Task 2。
- 全量刷新与文件摘要：Task 3。
- 完整复核队列、后台人工逐条决定、不自动重绑、单次提交识别：Task 3。
- 媒体校验与发布包完整性：Task 3。
- D1/R2 dry-run、显式 apply、复用维护门禁、未知结果恢复：Task 3。
- 原子可审计状态、续跑输入校验、敏感值不落盘：Task 1、Task 3。
- “复核批次已创建但进程中断”的稳定标签恢复：Task 3。
- CLI、文档与验证：Task 4、Task 5。
