# CCD 展示系统发布与回滚手册

## 正式运行边界

正式系统只使用本工作树的 FastAPI、SQLite 与原生前端：

- 配置：`config/showcase.yaml`
- 数据库：`data/showcase.db`
- 客户页：`http://127.0.0.1:8899/`
- 管理页：`http://127.0.0.1:8899/admin-xingxing`
- 启动：`start_showcase_server.bat`
- 管理员口令重置：`reset_showcase_admin_password.bat`；口令以隐藏输入方式录入，成功后会撤销旧管理员会话。
- 导入：`import_showcase_excel.bat`
- 完整备份：`backup_showcase_db.bat`

本地管理登录和客户口令入口默认每个进程每 60 秒最多计数 20 次，成功登录会清除此来源的计数。该计数保存在当前进程内；若将服务改为多进程或部署到反向代理后，应在代理/边缘层另配共享限流，不要直接信任未经配置的转发 IP 请求头。

AI 工作台及其数据库、端口、页面不属于这套系统。`cloudflare/` 是未完成的可选迁移实验，不是正式写入入口，不允许同时向本地库和 D1 写库存。

## 当前数据协议

数据库最新迁移版本为 11。商品使用稳定 `public_id` 对外，`product_id` 保留为来源键；历史链接由 `product-lookup` 兼容。所有商品修改递增 `row_version`。批量预览保存完整目标快照，确认和撤销均检查全部版本并在单事务中执行。

Excel 导入默认为增量预览。全量导入必须显式声明 `--mode full --complete`；来源中消失的商品进入 `review_state=missing`，不会自动下架。后台人工价格、文案和显示状态作为覆盖值保存，后续导入不能静默覆盖。

样片按型号共享保存，人工上传与自动匹配分开。重建只替换自动匹配关系；空、缺失或不可读的样片根会拒绝操作。

## 发布步骤

1. 停止 8899 服务，冻结后台写入。
2. 运行 `backup_showcase_db.bat`，确认快照目录含 `manifest.json`。
3. 在数据库副本运行测试、迁移、`pragma integrity_check` 和媒体引用检查。
4. 使用配置文件启动候选服务到 8898，验证客户页、历史链接、管理员保存、分页、批量预览及图片。
5. 停止旧服务，使用 `start_showcase_server.bat` 启动 8899。
6. 核对商品数、schema 版本、图片 404、错误率和接口延迟，再解除后台写入冻结。

候选恢复和隔离启动必须使用恢复目录自己的配置，完整命令如下：

```powershell
$env:PYTHONPATH = "$PWD\src"
$candidateDir = Join-Path 'tmp' ('candidate-showcase-' + (Get-Date -Format 'yyyyMMdd-HHmmss'))
python -m moments_inventory.cli showcase-db-restore --snapshot "备份快照目录" --destination $candidateDir
python -m moments_inventory.cli showcase-server --showcase-config (Join-Path $candidateDir 'config/showcase.yaml') --host 127.0.0.1 --port 8898
```

候选命令不得使用正式 `config/showcase.yaml`，也不得监听 8899。

迁移脚本幂等，应用启动只执行尚未记录的版本。不要把工作树中的空 `output/ccdcpt` 当成正式样片库；实际路径以配置为准。

备份命令因媒体引用不存在而停止时，必须先修复正式媒体路径，再重新生成带完整 `manifest.json` 的快照；不得跳过媒体校验或用占位文件作为正式备份。

## 回滚

代码可切回上一版本，但新版本产生写入后不能直接用旧数据库覆盖，否则会丢失新价格、上下架和操作日志。

需要数据回滚时：

1. 再次冻结写入并对当前状态制作完整快照。
2. 使用 `python -m moments_inventory.cli showcase-db-restore --snapshot "备份快照目录" --destination "全新恢复目录"` 恢复到全新目录。
3. 检查恢复报告、数据库完整性、商品数和媒体哈希。
4. 在其他端口启动恢复副本并完成验收。
5. 明确比较冻结后新增的写入，再人工决定是否切换配置。

恢复工具不会覆盖已有目录，也不会自动替换正式数据库。

## 批量改价验收

- 价格段边界固定为：`≤200`、`201～300`、`301～600`、`601～800`、`≥801`。
- 批量操作必须明确选择已勾选、当前筛选结果或全部库存。
- 正式执行前核对匹配、实际修改、不变和跳过数量，并导出完整 CSV 留档。
- 修改筛选或金额后必须重新生成预览；过期预览不能执行。
- 发布验证必须包含一次改价、一次撤销，以及一次版本冲突拒绝。
- 公开和管理商品列表的 `offset` 上限为 10000；超过上限应返回 400，不执行商品分页查询。

## 验证入口

CCD Python 运行依赖使用 `requirements/ccd-runtime.lock` 锁定直接及传递版本，构建后端 setuptools 固定在 `pyproject.toml`。创建环境时先运行 `python -m pip install -r requirements/ccd-runtime.lock`，再安装项目包。锁文件离线核对了 Python 3.11–3.13 的 Windows/Linux 环境标记；制品哈希和干净环境安装仍需在获准访问包源的构建机上补验。

本地 wheel 验证记录：2026-10-09 在 Windows 上执行 `python -m pip wheel . --no-deps --no-build-isolation` 成功；检查 wheel 内有 110 个 `showcase_web/static/` 文件，且 `admin.html`、`index.html`、`product.html` 均存在。该检查证明静态页面随安装包分发，不代表在干净隔离环境完成了依赖安装。

```powershell
$showcaseTests = Get-ChildItem -LiteralPath tests -Filter 'test_showcase_web*.py' | ForEach-Object { $_.FullName }
python -m pytest @showcaseTests tests/test_cli_showcase_web.py -q
node tests/browser/frontend-contracts.cjs
python scripts/benchmark_showcase.py --base-url http://127.0.0.1:8898 --database "数据库副本路径" --connection-mode revision-cache-concurrent-read-wal --concurrency 20 --duration 300 --output "性能报告.json"
```

性能基准只发只读请求。正式数据验证始终使用 SQLite backup 生成的副本。
