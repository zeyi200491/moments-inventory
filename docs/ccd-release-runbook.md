# CCD 展示系统发布与回滚手册

## 正式运行边界

统一刷新、人工复核、媒体包检查和 Cloudflare 快照同步流程入口见 [CCD Python 全流程命令](ccd-python-pipeline.md)。全流程命令不绕过本手册下述的 SQLite 权威源与维护状态门禁。

正式管理与库存维护只写入本地 FastAPI 和 SQLite：

- 本机配置：若存在则使用 `config/showcase.local.yaml`，否则使用仓库示例 `config/showcase.yaml`；首次配置见 `docs/ccd-local-configuration.md`。
- 权威数据库：正式工作树 `.worktrees/ccd-inventory-showcase` 下配置指向的 `data/showcase.db`
- 客户页：`http://127.0.0.1:8899/`
- 管理页：`http://127.0.0.1:8899/admin-xingxing`
- 启动：`start_showcase_server.bat`
- 管理员口令重置：`reset_showcase_admin_password.bat`；口令以隐藏输入方式录入，成功后会撤销旧管理员会话。
- 导入：`import_showcase_excel.bat`
- 完整备份：`backup_showcase_db.bat`

上述启动、导入、备份和口令重置入口会调用正式环境门禁。门禁以 Git 共用目录为基准，只接受 `.worktrees/ccd-inventory-showcase` 中的入口及其 `config/showcase.yaml` 或本机覆盖配置，并要求数据库、机身图、样片根、人工库存表、备份目录和监听地址分别符合正式工作树约定。从根目录或开发/恢复工作树运行时会在数据库打开前退出；请进入正式工作树后再运行。门禁只核验路径和目录，不读取或改写数据库。

本地管理登录和客户口令入口默认每个进程每 60 秒最多计数 20 次，成功登录会清除此来源的计数。该计数保存在当前进程内；若将服务改为多进程或部署到反向代理后，应在代理/边缘层另配共享限流，不要直接信任未经配置的转发 IP 请求头。

本地 SQLite 是库存唯一写入权威。Cloudflare 部署仅接收从本地导出的发布快照，用于只读展示；Cloudflare 管理页的库存、设置及其他业务写操作必须被禁用，不能把 D1 当作可回写库存，也不能同时向 SQLite 和 D1 写库存。每次发布前由本地权威库生成快照、检查清单并单向同步。若发布失败，修复应回到本地 SQLite 后重新发布。

AI 工作台及其数据库、端口、页面不属于这套系统。隔离 worktree、候选恢复目录和临时测试库只用于开发、验证或恢复演练，不是正式数据入口。启动正式本地服务前，核对配置解析出的数据库路径确实指向上述权威数据库；若运行目录或配置不确定，停止写入并先核实路径。

## 当前数据协议

数据库最新迁移版本为 11。商品使用稳定 `public_id` 对外，`product_id` 保留为来源键；历史链接由 `product-lookup` 兼容。所有商品修改递增 `row_version`。批量预览保存完整目标快照，确认和撤销均检查全部版本并在单事务中执行。

Excel 导入默认为增量预览。全量导入必须显式声明 `--mode full --complete`；来源中消失的商品进入 `review_state=missing`，不会自动下架。后台人工价格、文案和显示状态作为覆盖值保存，后续导入不能静默覆盖。

样片按型号共享保存，人工上传与自动匹配分开。重建只替换自动匹配关系；空、缺失或不可读的样片根会拒绝操作。

客户访问口令保护公开库存 API 与原图/缩略图。媒体直链只对仍被公开商品或公开图库引用的图片开放；商品隐藏、售出或图库隐藏后，若没有其他公开引用，旧链接立即返回 404。共享图片只要仍被至少一个公开商品或图库引用，仍可访问。媒体响应不允许缓存；管理员有效会话仍可查看隐藏素材。

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

迁移脚本幂等，应用启动只执行尚未记录的版本。不要把工作树中的空 `output/ccdcpt` 当成正式样片库；实际路径以本机配置为准。

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
- 执行期间可收起确认框，服务器请求会继续运行；筛选变化不会改写本次已提交请求。
- 若网络中断、请求超时（408）、限流（429）或服务器返回 5xx 导致结果未知，先使用批量操作区的“安全重试同一操作”。页面会在当前浏览器会话中保留原预览 ID 和幂等键，刷新后也能恢复；确认原请求完成前不能生成新的批量预览。
- 不要清除浏览器会话数据来处理结果未知的操作。预览过期、版本冲突等明确拒绝后，按提示重新预览并核对。
- 后台采用共享管理员凭据，批量预览及幂等结果按共享管理员归属保存；重新登录后仍可导出原预览并使用原幂等键核对结果。该共享范围依赖当前只有一组管理员口令的部署方式，启用独立管理员身份前必须改为账号级归属。
- 批量执行客户端等待上限为 60 秒；超时按结果未知处理，使用原预览 ID 和幂等键重试，不要新建预览。
- 发布验证必须包含一次改价、一次撤销，以及一次版本冲突拒绝。
- 专栏管理在保存或刷新后保留各专栏的搜索条件、价格筛选和待填推荐语；保存失败时检查对应专栏行的错误状态，输入草稿应保留。
- 样片绑定和分组确认失败会在对应行显示结果；服务端 408、5xx 或网络中断时属于结果未知，先刷新列表核对，再决定是否重试。商品/分组身份锁跨列表重绘生效；绑定、刷新和重建期间按钮会显示忙碌状态并阻止重复提交。
- 公开和管理商品列表的 `offset` 上限为 10000；超过上限应返回 400，不执行商品分页查询。

## 验证入口

CCD Python 运行依赖使用 `requirements/ccd-runtime.lock` 锁定直接及传递版本，构建后端 setuptools 固定在 `pyproject.toml`。创建环境时先运行 `python -m pip install -r requirements/ccd-runtime.lock`，再安装项目包。锁文件离线核对了 Python 3.11–3.13 的 Windows/Linux 环境标记；锁文件尚未包含制品哈希，完整依赖集在干净环境的安装仍需后续验证。

本地 wheel 验证记录：2026-10-15 在 Windows 上执行 `python -m pip wheel . --no-deps --no-build-isolation`，随后在临时全新虚拟环境中使用 `--no-deps --no-index` 安装 wheel 成功；从该环境检查到 110 个 `showcase_web/static/` 文件，且 `admin.html`、`index.html`、`product.html` 均存在。这证明 wheel 可离线安装且包含展示网页静态资源；不代表运行依赖已在干净环境安装，也不代表制品哈希已核验。

客户页移动视口合成检查记录：2026-10-15 使用隔离静态服务、模拟公开 API 和 160 条合成商品，在 Chromium 桌面浏览器的 320/375/768 像素视口检查，`documentElement.scrollWidth` 与视口宽度相同；加载下一页后首张商品卡片 DOM 节点保持不变、商品数组原地追加且未保留重复的商品登记 Map，按公开商品 ID 的咨询文案查找也能返回对应商品，未见页面脚本错误。该检查证明本次列表追加路径及这些模拟视口未出现横向溢出；不代表微信内置浏览器、iOS Safari、真实设备性能或无障碍读屏验收通过。

```powershell
$showcaseTests = Get-ChildItem -LiteralPath tests -Filter 'test_showcase_web*.py' | ForEach-Object { $_.FullName }
python -m pytest @showcaseTests tests/test_cli_showcase_web.py -q
node tests/browser/frontend-contracts.cjs
python scripts/benchmark_showcase.py --base-url http://127.0.0.1:8898 --database "数据库副本路径" --connection-mode revision-cache-concurrent-read-wal --concurrency 20 --duration 300 --output "性能报告.json"
```

性能基准只发只读请求。正式数据验证始终使用 SQLite backup 生成的副本。
