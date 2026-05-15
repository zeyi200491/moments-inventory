# 朋友圈商品库独立仓库拆分设计

## 背景

当前仓库同时承载两类能力：

1. 基于 WeFlow 的朋友圈抓取、商品识别、SQLite 入库、Excel 导出。
2. 面向微信客服场景的 AI 客服工作台。

用户本次目标不是继续扩展大仓库，而是把“朋友圈商品库提取功能”单独抽出来，形成一个公开 GitHub 项目。这个独立项目需要满足两个核心要求：

1. 别人下载仓库后，可以只使用朋友圈商品库提取相关功能。
2. 别人在自己的电脑上完成一次环境初始化后，可以通过运行脚本直接产出 Excel。

这里的“朋友圈商品库提取功能”明确包含两部分：

1. 朋友圈抓取、商品识别、SQLite 存储、Excel 导出。
2. 自动刷朋友圈的 warmup 流程，即在 Windows 微信桌面端中按固定路径预刷新目标联系人朋友圈，再继续同步与导出。

## 目标

1. 新建一个公开 GitHub 仓库，仓库名为 `pengyouquantiqu`。
2. 从当前项目中抽离最小可运行的朋友圈商品库工具，不携带 AI 客服代码。
3. 保留当前已验证的命令能力：
   - `sync`
   - `export`
   - `sync --export`
   - `warmup --export`
4. 保留 Windows 初始化脚本和运行脚本，运行方式调整为：
   - 先执行一次环境初始化脚本
   - 之后通过命令运行导出脚本，不依赖“双击即可用”的交互方式
5. 重写 README 和 Windows 使用说明，使公开仓库用户能够按步骤完成配置与导出。
6. 清理依赖、文档和测试，让新仓库边界清晰且可维护。

## 非目标

1. 不保留任何 AI 客服工作台功能。
2. 不在第一版中重命名 Python 包名，继续使用 `moments_inventory`。
3. 不将 WeFlow token、真实联系人、真实输出目录等敏感配置提交到公开仓库。
4. 不追求单脚本自动完成“初始化 + 导出”，避免把安装问题和业务执行问题耦合在一起。
5. 不新增新的业务能力，只做独立化、清理和可交付改造。

## 方案对比

### 方案一：从当前仓库复制并裁剪出精简独立仓库

做法：
以现有 `moments_inventory` 为基础，复制核心代码、脚本、配置示例、文档和相关测试，再删除 AI 客服相关内容。

优点：

1. 改动最小，复用当前已验证链路。
2. 风险最低，最容易保持 warmup 与导出行为一致。
3. 可以快速形成可发布、可运行的首版公开仓库。

缺点：

1. 需要做一次系统性的依赖、文档和测试清理。
2. 仓库中可能会保留少量历史命名痕迹，例如包名仍为 `moments_inventory`。

### 方案二：保留单仓库，拆成多包或子项目发布

做法：
继续维持当前大仓库，在仓库内重构出多个包，再对外发布子包或子目录。

优点：

1. 理论上代码复用更规范。
2. 后续双向同步更方便。

缺点：

1. 对外使用复杂，不符合“别人下载就直接能用”的目标。
2. 文档、脚本、配置路径和发布流程都会更绕。

### 方案三：从零创建新仓库，再逐个搬运模块

做法：
新建完全空白项目，只把必要模块逐个迁移过去。

优点：

1. 仓库最干净。
2. 边界最强。

缺点：

1. 重组成本最高。
2. 容易在迁移时漏掉 warmup、配置或测试细节。

## 推荐方案

推荐采用方案一：从当前仓库复制并裁剪出精简独立仓库。

原因如下：

1. 当前朋友圈工具本身已经基本具备独立产品雏形，拆分成本远低于重写。
2. 用户最关心的是“别人拿到就能用”，不是内部架构完美主义。
3. 现有 `sync / export / warmup`、SQLite、Excel 导出、Windows 脚本都已有验证基础，保守迁移最稳妥。

## 独立仓库范围

### 保留内容

新仓库只保留与朋友圈商品库提取直接相关的代码和交付物：

1. 核心 Python 包中的以下模块：
   - `config.py`
   - `exporter.py`
   - `logging_utils.py`
   - `matcher.py`
   - `models.py`
   - `parser.py`
   - `service.py`
   - `storage.py`
   - `utils.py`
   - `weflow_client.py`
   - `wechat_ui_adapter.py`
   - `wechat_warmup.py`
   - `warmup_report.py`
   - `cli.py`
   - `__init__.py`
2. 配置示例：
   - `config/config.example.yaml`
   - `config/models.example.txt`
3. Windows 脚本：
   - `setup_windows.bat`
   - `run_export.bat`
   - `run_warmup_and_export.bat`
4. 文档：
   - `README.md`
   - `docs/windows-使用说明.md`
5. 与上述链路直接相关的测试。

### 删除内容

新仓库明确删除以下内容：

1. `src/moments_inventory/ai_kefu/` 全部代码。
2. `frontend/` 下的客服工作台前端。
3. `main.js` 和工作台启动脚本。
4. `config/ai_kefu.example.yaml` 及 AI 客服专用配置。
5. AI 客服相关测试、说明文档、运行说明。
6. 任何与 FastAPI 服务、知识库导入、商品导入客服库相关的命令入口。

## 仓库结构设计

新仓库建议结构如下：

```text
pengyouquantiqu/
├─ config/
│  ├─ config.example.yaml
│  └─ models.example.txt
├─ docs/
│  └─ windows-使用说明.md
├─ src/
│  └─ moments_inventory/
├─ tests/
├─ .gitignore
├─ README.md
├─ pyproject.toml
├─ setup_windows.bat
├─ run_export.bat
└─ run_warmup_and_export.bat
```

设计原则：

1. 根目录只保留最终用户真正会接触的东西。
2. `config` 目录只放示例和用户本地生成配置。
3. `src` 和 `tests` 保持标准 Python 项目结构，方便后续测试和发布。

## 命令与脚本设计

### CLI 命令

独立仓库只保留以下命令：

```bash
python -m moments_inventory.cli sync
python -m moments_inventory.cli export
python -m moments_inventory.cli sync --export
python -m moments_inventory.cli warmup --export
```

必要时也保留：

```bash
python -m moments_inventory.cli warmup
```

### 初始化脚本

`setup_windows.bat` 只负责环境准备，不负责抓取和导出。它的职责固定为：

1. 检查本机 Python。
2. 创建 `.venv`。
3. 安装项目依赖。
4. 从示例文件复制生成：
   - `config/config.yaml`
   - `config/models.txt`
5. 输出下一步操作提示。

它不再处理任何 AI 客服配置文件。

### 运行脚本

`run_export.bat` 的职责：

1. 检查 `.venv`、`config/config.yaml`、`config/models.txt` 是否存在。
2. 提示 `WEFLOW_ACCESS_TOKEN` 未设置的风险。
3. 执行：

```bash
python -m moments_inventory.cli --config "config/config.yaml" sync --export
```

`run_warmup_and_export.bat` 的职责：

1. 做与 `run_export.bat` 相同的前置检查。
2. 提示用户先把微信停在通讯录或聊天列表。
3. 执行：

```bash
python -m moments_inventory.cli --config "config/config.yaml" warmup --export
```

### 运行方式约束

交付给最终用户的使用方式固定为：

1. 首次执行一次 `setup_windows.bat`
2. 配置 `config/config.yaml`、`config/models.txt`、`WEFLOW_ACCESS_TOKEN`
3. 之后通过命令运行 `run_export.bat` 或 `run_warmup_and_export.bat`

这里明确不把“双击直接完成业务执行”作为设计目标。

## 配置策略

### 公开仓库可提交内容

可以提交：

1. `config/config.example.yaml`
2. `config/models.example.txt`

### 公开仓库不可提交内容

不提交：

1. `config/config.yaml`
2. `config/models.txt`
3. `WEFLOW_ACCESS_TOKEN`
4. 实际 SQLite 数据库
5. 实际导出目录下的 Excel、图片、视频

### 配置原则

1. 仓库只提供示例。
2. 用户本地初始化后生成实际配置。
3. token 继续走 Windows 环境变量。
4. 输出目录、数据库路径继续保持本地路径配置。

## 依赖设计

独立仓库的 `pyproject.toml` 需要清理为“只服务朋友圈工具”的依赖集合。

保留依赖：

1. `PyYAML`
2. `pywinauto`（仅 Windows）

按当前代码实际需要决定是否保留：

1. `httpx`
2. `pydantic`

明确删除：

1. `fastapi`
2. `uvicorn`
3. 其他只为 AI 客服工作台服务的依赖

依赖清理原则：

1. 以运行 `sync / export / warmup` 和通过测试为准。
2. 不因为“可能以后会用到”而保留无关依赖。

## 文档设计

### README

新 README 需要从“综合项目说明”改成“独立工具说明”，重点覆盖：

1. 工具用途
2. 环境要求
3. 初始化步骤
4. 配置步骤
5. 命令行运行方式
6. warmup 使用前提
7. 导出产物说明
8. 常见问题

### Windows 使用说明

`docs/windows-使用说明.md` 需要同步改写，要求：

1. 完全聚焦朋友圈工具。
2. 不再提及 AI 客服工作台。
3. 明确“初始化一次，之后命令运行脚本”的流程。
4. 用中文写清楚 `WEFLOW_ACCESS_TOKEN`、`targets`、`models.txt` 的来源与作用。

## 测试策略

新仓库只保留与朋友圈工具直接相关的测试，至少包括：

1. 配置加载测试
2. WeFlow 响应解析测试
3. 匹配与合并测试
4. 存储测试
5. 导出测试
6. warmup 配置测试
7. warmup 调度测试
8. Windows 脚本文案与交付物测试

删除：

1. 所有 `ai_kefu` 相关测试
2. 前端和工作台相关测试

验收前需要保证：

1. 这些测试在新仓库内能独立运行。
2. 文档与脚本中引用的命令、文件路径、配置文件都与新仓库一致。

## GitHub 发布方案

### 仓库信息

1. 仓库名：`pengyouquantiqu`
2. 可见性：公开

### 创建流程

1. 在当前工作区旁创建新的独立项目目录。
2. 复制并清理需要的文件。
3. 初始化新的 git 仓库。
4. 写入首版 README、脚本、配置示例和测试。
5. 运行测试与必要的脚本验证。
6. 创建公开 GitHub 仓库并推送首版提交。

### 命名策略

第一版只修改 GitHub 仓库名，不修改 Python 包名 `moments_inventory`。

这样做的原因：

1. 能显著降低迁移改名带来的回归风险。
2. 现有测试、脚本和入口都可以更平滑复用。
3. 如果后续确实需要品牌统一，可以在第二阶段再考虑包名迁移。

## 风险与缓解

### 风险一：拆分时误删朋友圈工具依赖文件

影响：
新仓库可以安装，但运行 `sync / export / warmup` 时失败。

缓解：

1. 先按模块边界列清单，再复制。
2. 用测试和命令行验证覆盖 `sync`、`export`、`warmup` 主链路。

### 风险二：脚本或文档残留 AI 客服路径

影响：
公开仓库用户按文档操作时会遇到不存在的文件或命令。

缓解：

1. 全仓搜索 `ai_kefu`、`kefu-dev`、`frontend/workbench` 等关键词。
2. 将 README、Windows 说明、脚本提示语统一重写。

### 风险三：依赖清理过度

影响：
安装成功但运行时缺模块。

缓解：

1. 不按主观判断删依赖，先跑测试再收敛。
2. 在新仓库里实际执行一次初始化和命令验证。

### 风险四：公开仓库暴露敏感配置

影响：
真实联系人、token、服务地址可能外泄。

缓解：

1. 仓库只提交示例配置。
2. 检查 `.gitignore` 是否覆盖本地配置、数据库、输出目录和媒体文件。

## 实施边界

本次实施只覆盖：

1. 新独立仓库创建
2. 代码与测试裁剪
3. 文档与脚本改造
4. GitHub 公开仓库创建与首次推送

本次实施不覆盖：

1. 朋友圈识别算法升级
2. 新的 WeFlow API 适配
3. warmup 操作路径增强
4. 包名和命令名品牌化重命名

## 验收标准

当以下条件同时满足时，视为本次目标达成：

1. 新公开仓库 `pengyouquantiqu` 已创建并推送首版代码。
2. 新仓库中不再包含 AI 客服代码、前端和相关依赖。
3. 用户在全新 Windows 电脑上可以先执行 `setup_windows.bat` 完成环境初始化。
4. 用户完成配置后，可以通过命令运行 `run_export.bat` 产出 Excel。
5. 在启用 warmup 的前提下，用户可以通过命令运行 `run_warmup_and_export.bat` 触发自动刷朋友圈并继续导出。
6. README 与 `docs/windows-使用说明.md` 能独立指导第三方完成使用。
7. 与朋友圈工具相关的测试在新仓库中通过。

## 结论

本次最务实的路径不是重写，而是把现有已验证的朋友圈商品库工具从大仓库中完整剥离，形成一个公开、单用途、可初始化、可运行、可导出 Excel 的独立 GitHub 项目。

首版以“稳定独立交付”为第一优先级，因此采用：

1. 仓库名改为 `pengyouquantiqu`
2. Python 包名继续沿用 `moments_inventory`
3. 保留 `sync / export / warmup` 核心链路
4. 删除 AI 客服全部内容
5. 强化初始化脚本、运行脚本和中文文档

这条路径能在最小风险下最快达到用户目标，也为后续单独维护和公开分发打下清晰边界。
