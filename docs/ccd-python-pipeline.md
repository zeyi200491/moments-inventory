# CCD 展示网页全流程命令

`ccd-pipeline` 把正式全量刷新、库存表合并、后台人工导入复核、媒体发布包检查和 Cloudflare 数据快照预检串成一条可追踪流程。SQLite 始终是库存唯一写入权威，D1 只接收 SQLite 快照。

## 执行位置与边界

请在本机正式 CCD Python 工作树运行，确认该工作树解析到 `data/showcase.db`、商品媒体目录和样片目录。不要在 AI 工作台目录运行。Cloudflare 仓库路径必须通过 `--cloud-repo` 明确传入；命令不会搜索或猜测另一个仓库。

以下 PowerShell 示例假设当前目录是正式 CCD Python 项目根目录：

```powershell
$env:PYTHONPATH = "$PWD\src"
$cloudRepo = 'E:\Ai jjfajgsw\AIkefu\.worktrees\ccd-cloud-phase1-correctness'
python -m moments_inventory.cli ccd-pipeline run --cloud-repo $cloudRepo
```

如果 Python 包已经安装在项目虚拟环境，可使用 `.venv\Scripts\python.exe` 并省略 `PYTHONPATH`。

## 阶段流程

1. 预检 CCD 项目标识、SQLite 和媒体路径、Cloudflare 仓库标识、Wrangler D1/R2 绑定及所需工具；失败时不启动刷新或远端命令。
2. Windows 上调用 `run_full_mode.bat`，核对 `output/全量当前库.xlsx` 并记录文件摘要。
3. 合并到配置指定的人工展示库存表，创建一个待复核批次后暂停。CLI 会显示本机管理页和复核批次号。
4. 管理员在展示后台逐条处理候选身份和导入决定，并使用后台原有的“提交”操作一次性提交到本地 SQLite。没有自动重绑或自动提交。
5. 使用相同 run id 续跑。CLI 查询同一个复核批次；若它仍待处理，会继续暂停；只有后台批次状态为 `committed` 才进入后续步骤。
6. 调用现有 Cloudflare 导出器，检查 `READY`、manifest、verification 和媒体摘要；然后执行 `sync-cloudflare.mjs` 默认 dry-run。
7. 默认状态为本地 dry-run 完成。该结果不代表客户页已更新，也不验证 Wrangler 登录账号或线上 D1/R2 权限。

## 查看状态和续跑

每次 run 的状态写到：

```text
output/ccd-pipeline/runs/<run_id>.json
```

原子替换保证中断时不会留下半份 JSON；状态记录阶段结果、环境/目标指纹和产物摘要，不记录客户口令、管理员口令、cookie、token、Cloudflare secret 或原始异常内容。先从 `run` 输出复制 `run_id`：

```powershell
python -m moments_inventory.cli ccd-pipeline status --run-id '<run_id>'
python -m moments_inventory.cli ccd-pipeline resume --run-id '<run_id>' --cloud-repo $cloudRepo
```

如果初始命令带 `--apply`，它只记录“可能发布”的意图，不在复核前执行远端写操作；复核提交后，仍需在最终续跑命令上再次明确 `--apply`。

## Cloudflare apply

只有在审核 dry-run 目标、包摘要和生产配置后，才在确认过的相同 run、Cloudflare 仓库和 Wrangler 配置上执行：

```powershell
python -m moments_inventory.cli ccd-pipeline resume --run-id '<run_id>' --cloud-repo $cloudRepo --apply
```

这会调用现有 `sync-cloudflare.mjs --apply`。同步器负责验证 Cloudflare account、资源绑定、远端互斥、维护状态门禁、断点状态和远端验收。Python CLI 不会部署 Worker、域名、WAF 或改写缓存策略。只有同步器返回匹配 manifest、远端 D1 验证和维护关闭状态的完整结果，流程才标为 `published`。

## 暂停、失败和未知结果

- **等待人工复核：** 是正常暂停。按后台批次号逐条完成复核并提交，再运行 `resume`。
- **预检失败：** 修正正式 CCD 路径、仓库路径、Wrangler 配置或工具安装；预检失败的运行不启动刷新。修正后新建 run。
- **全量刷新/人工表合并/导入复核阶段失败：** 不自动重试该 run，先核对正式 SQLite 和表格状态，再修复原因并新建 run。
- **媒体包或 Cloudflare dry-run 失败：** 若原环境、目标和输入产物摘要仍一致，可以续跑；任何既有产物变化都应新建 run。
- **Cloudflare apply 超时、断连或退出结果无法核验：** 状态为 `unknown`，禁止新建包或更换配置。先核对该 run 使用的同一 package 下同步器 `.sync-state.json`、维护状态和远端批次标记；确认后仅以相同 run、相同仓库/配置再次使用 `resume --apply`，由同步器按原进度恢复。若维护状态仍开启，先修复/恢复远端流程再开放客户访问。
- **运行环境/目标指纹变化：** 拒绝续跑，避免把旧复核批次或包应用到另一个数据库、工作树、Cloudflare 仓库或资源目标。

`status` 是只读操作。它不连接 Cloudflare，也不会触碰 SQLite 库存内容。

## 本机验证

```powershell
python -m pytest tests/test_ccd_pipeline_state.py tests/test_ccd_pipeline.py tests/test_cli_ccd_pipeline.py -q
```

测试使用临时目录、临时数据库路径和假的外部命令，不启动朋友圈刷新，也不访问真实 Cloudflare、D1、R2 或生产站点。
