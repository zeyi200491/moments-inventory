# 微信朋友圈商品提取 + AI 客服工作台

这个仓库当前包含两条主线能力：

1. 微信朋友圈商品提取
2. AI 客服工作台

## 1. 微信朋友圈商品提取

这套工具通过 WeFlow HTTP API 抓取指定联系人的朋友圈内容，识别 CCD 商品信息，并导出为 Excel。

CCD 展示网页从本地 SQLite 到 Cloudflare 快照的统一操作流程见 [CCD 展示网页全流程命令](docs/ccd-python-pipeline.md)；正式数据边界和发布安全要求见 [CCD 发布与回滚手册](docs/ccd-release-runbook.md)。

当前已经落地的关键能力：

- 只保留“当前在售”语义，不再导出历史总库
- 支持按 `tier` 分层运行
- 支持 `priority_only` / `full` 两种编排模式
- 支持大批量联系人按批执行
- 支持 Windows 微信桌面端 warmup 预刷新
- 支持无媒体下载的快速导出

### 1.1 重要概念

- `tier: 1`
  表示优先货源。通常用于第一阶段先跑、先出表的联系人。
- `tier: 2`
  表示普通货源。通常在优先货源之后继续批量执行。
- `priority_only`
  只跑 `tier=1` 目标，并导出一份优先库 Excel。
- `full`
  先跑 `tier=1`，再继续跑其余目标，最后导出全量 Excel。

### 1.2 当前正式价格规则

导出到正式 Excel 的记录，当前遵循下面这套硬规则：

1. 原文里必须出现 `💰`
2. 价格只认 `💰` 前后紧邻的数字
3. 没有 `💰` 的记录，不进入正式 Excel
4. 价格 `< 99` 的记录，不进入正式 Excel

这套规则是为了避免把：

- `15新`
- `99新`
- `1400万像素`
- 编号、序列号

这类数字误识别成商品价格。

### 1.3 常用命令

```bash
python -m moments_inventory.cli sync
python -m moments_inventory.cli export
python -m moments_inventory.cli sync --export
python -m moments_inventory.cli warmup --export
python -m moments_inventory.cli batch-run --export
python -m moments_inventory.cli orchestrated-run --mode priority_only
python -m moments_inventory.cli orchestrated-run --mode full
python -m moments_inventory.cli orchestrated-run --mode full --resume
```

### 1.4 常用脚本

项目根目录下提供了这些 Windows 脚本：

- `setup_windows.bat`
- `run_export.bat`
- `run_warmup_and_export.bat`
- `run_batched_warmup_and_export.bat`
- `run_ai_kefu_workbench.bat`

### 1.5 推荐运行方式

#### 快速导出，不刷新朋友圈

适合只验证导出规则、先看结果、不想等待微信 warmup：

- `warmup.enabled: false`
- `task.download_media: false`

然后运行：

```bash
python -m moments_inventory.cli orchestrated-run --mode priority_only
```

#### 第一阶段优先货源

适合先处理最重要的联系人：

- 前 25 个联系人设为 `tier: 1`
- `warmup.enabled: true`
- `task.download_media: false`

运行后会先输出一份优先货源 Excel。

#### 全量模式

适合先跑优先货源，再继续跑剩余联系人：

```bash
python -m moments_inventory.cli orchestrated-run --mode full
```

运行完成后会得到：

- `优先货源当前库.xlsx`
- `全量当前库.xlsx`
- `progress.json`
- `failed_targets.csv`

### 1.6 当前阶段的已知边界

- warmup 仍然依赖 Windows 微信桌面端 UI 自动化
- 微信窗口大小、DPI、界面版本仍会影响命中率
- 当前已重点提升“打开朋友圈小窗”的命中率与失败后的安全恢复
- 如果 warmup 失败，当前设计会优先保证“不把微信主界面带崩”

更详细的 Windows 使用说明见：

- [docs/windows-使用说明.md](E:\Ai jjfajgsw\AIkefu\.worktrees\moments-batched-current-only\docs\windows-使用说明.md)

## 2. AI 客服工作台

仓库同时包含一套本地 AI 客服工作台，用于：

- 上传业务知识库
- 生成客服草稿
- 管理商品库
- 同步 WeFlow 私聊会话

### 2.1 当前已落地能力

- 主规则常驻注入
- 会话阶段识别与持久化
- 风险等级识别
- 固定话术锁定机制
- 预算驱动的商品筛选
- 显式偏好叠加筛选
- 利润计算与同款优先策略
- 知识库分层与加权召回
- WeFlow 会话同步到工作台

### 2.2 启动方式

推荐直接运行：

```bat
run_ai_kefu_workbench.bat
```

它会自动启动：

- 后端：`http://127.0.0.1:8787`
- 前端：`http://127.0.0.1:5173`

如果只想单独启动后端：

```bash
python -m moments_inventory.cli kefu-dev --host 127.0.0.1 --port 8787 --reload --ai-kefu-config config/ai_kefu.yaml
```

## 3. CCD 客户展示站

当前正式展示系统使用 FastAPI、SQLite 和管理后台，不再以旧静态 `site_dist/` 作为库存管理或发布入口。本地 SQLite 是库存唯一写入权威；Cloudflare 仅接收本地导出的只读展示快照。

日常导入、管理、备份、恢复和发布边界见 [CCD 发布与回滚手册](docs/ccd-release-runbook.md) 和 [本机配置说明](docs/ccd-local-configuration.md)。本地客户页为 `http://127.0.0.1:8899/`，管理页为 `http://127.0.0.1:8899/admin-xingxing`。请只在正式 CCD 工作树中启动正式服务；开发 worktree 和恢复副本必须使用隔离配置及端口。

`publish_showcase_site.bat` 已停用，避免继续生成与 SQLite 管理系统并行的旧静态站点，也避免将客户口令放入进程参数。`showcase-build` 命令只保留给需要读取旧静态制品的迁移/兼容场景，不用于当前正式发布。

## 4. 建议的接手顺序

如果是第一次接手这个仓库，建议按这个顺序理解：

1. 先看这份 `README.md`
2. 再看 [docs/windows-使用说明.md](E:\Ai jjfajgsw\AIkefu\.worktrees\moments-batched-current-only\docs\windows-使用说明.md)
3. 再看 `config/config.example.yaml`
4. 最后再看 `src/moments_inventory/` 里的实现细节
