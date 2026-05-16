# 微信朋友圈工具 + AI 客服工作台

这个仓库当前包含两条能力线：

1. 基于 WeFlow 的朋友圈内容抓取、识别和导出
2. 面向微信人工客服场景的 AI 辅助工作台

## 朋友圈工具

仓库最早的能力是一套 Windows 命令行工具，用来通过 WeFlow HTTP API 抓取朋友圈内容，识别 CCD 商品信息，并导出：

- 当前在售 Excel
- 分批大执行脚本 `run_batched_warmup_and_export.bat`
- 对应的本地图片和视频

### 快速开始

1. 运行 `setup_windows.bat`
2. 配置 `config/config.yaml`
3. 配置 `config/models.txt`
4. 设置环境变量 `WEFLOW_ACCESS_TOKEN`
5. 运行 `run_export.bat`

详细说明见 [docs/windows-使用说明.md](docs/windows-使用说明.md)。

### 命令行入口

```bash
python -m moments_inventory.cli sync
python -m moments_inventory.cli export
python -m moments_inventory.cli sync --export
python -m moments_inventory.cli warmup --export
python -m moments_inventory.cli batch-run --export
```

## AI 客服工作台

AI 客服后端已经从普通“检索 + 生成”升级到“规则驱动草稿生成”。

### 当前已落地能力

- 主规则常驻注入
- 会话阶段识别与阶段持久化
- 风险等级识别
- 固定话术锁定机制
- 预算驱动的商品筛选
- 显式偏好叠加筛选
- 利润计算、同款优先、多台购买利润校验
- 知识库分层与权重策略
- WeFlow 会话同步到工作台
- 业务库上传状态持久化

### 当前规则驱动能力

- 系统提示词已分层：
  - 最高优先级主规则
  - 当前会话状态
  - 阶段推进规则
  - 固定话术调用规则
  - 资料不足兜底规则
  - 人工接管触发规则
  - 禁止项
- 固定话术支持：
  - `locked` / `strict_locked`：正文完全不可改写
  - `soft_locked`：正文不可改写，只允许系统拼接短前后缀
- 商品推荐规则：
  - 先识别预算
  - 默认只按预算推荐 12 台
  - 只有客户显式提出偏好，才叠加品牌、功能正常、验机视频等筛选
- 知识召回规则：
  - `master_rule`：常驻注入
  - `fixed_reply`：单独命中，不走普通检索
  - `faq`：默认业务知识层
  - `product_inventory`：结构化库存层，参与预算筛货与推荐
  - `product_material`：在验机、配件、导出、细节说明等场景按需召回
  - `shipping_info`：发货、物流、仓库、供应链问题优先召回
  - `after_sale_doc`：售后、退换、质保边界问题优先召回
  - `style_sample`：只影响风格，不参与业务决策

### 当前检索实现状态

当前检索已经从“纯字符串碰撞”升级为本地混合检索：

- 先按 `knowledge_tier + workflow` 做分层路由
- 层内使用 BM25 风格词项打分
- 保留标签命中、短语命中和同层保守兜底
- 对发货、售后、商品素材库做单独定向召回

当前已经接入可降级的向量混合检索，但还没有外部重排模型或独立向量索引。

`embedding_provider` 已经进入真实检索链路：导入知识时会 best-effort 生成 chunk embedding，生成草稿时会 best-effort 生成 query embedding；如 provider 不可用或向量缺失，则自动降级回关键词检索。

## 知识库模型

### 七类知识层

后端仍然保留 7 个知识层，供检索和命令行导入使用：

- `master_rule`
- `fixed_reply`
- `faq`
- `product_inventory`
- `product_material`
- `shipping_info`
- `after_sale_doc`
- `style_sample`

### 五个业务库入口

前端工作台不再直接让用户选择 `knowledge_tier`，而是改成 5 个业务库入口：

1. `master_rule_bundle`
2. `product_inventory_excel`
3. `product_material_excel`
4. `shipping_info_excel`
5. `style_sample_md`

对应规则如下：

- 主规则文件：上传 `.md`，同一份文件里可同时包含主规则和 FAQ，系统会自动拆分到 `master_rule` 和 `faq`
- 商品库存库：上传 `.xlsx`，全量覆盖当前商品库
- 商品素材库：上传 `.xlsx`，按每行一条素材事实入库
- 供应链发货信息库：上传 `.xlsx` / `.xls`，按每行一条发货规则入库
- 风格样本库：上传 `.md`，只影响语气

### 商品库存库

商品库通过独立结构化表保存，不走普通文本知识库导入。

当前最小结构化字段包括：

- `brand`
- `model_std`
- `is_functional`
- `has_inspection_video`
- `has_sample_output`
- `cost_price`
- `sale_price`
- `profit_amount`

当前在售表可通过以下命令导入：

```powershell
$env:PYTHONPATH='E:\Ai jjfajgsw\AIkefu\src'
python -m moments_inventory.cli import-products --xlsx "E:\Ai jjfajgsw\AIkefu\config\output\当前在售库.xlsx" --ai-kefu-config "E:\Ai jjfajgsw\AIkefu\config\ai_kefu.yaml"
```

## 后端启动

```bash
set AI_KEFU_OPENAI_API_KEY=你的真实密钥
python -m moments_inventory.cli kefu-dev --host 127.0.0.1 --port 8787 --reload --ai-kefu-config config/ai_kefu.yaml
```

日常本地联调更建议直接运行：

```bat
run_ai_kefu_workbench.bat
```

这个启动器会同时检查并拉起：

- AI 客服后端 `127.0.0.1:8787`
- 前端工作台 `127.0.0.1:5173`

并默认带上后端热重载，避免改完代码后浏览器还连着旧进程。

启动后可用接口：

- `GET /api/health`
- `POST /api/drafts`
- `GET /api/drafts/history`
- `POST /api/drafts/feedback`
- `GET /api/knowledge/libraries`
- `GET /api/knowledge/sources`
- `POST /api/knowledge/imports`
- `POST /api/knowledge/uploads`
- `GET /api/chat-sync/sessions`
- `GET /api/chat-sync/sessions/{sessionId}`
- `POST /api/chat-sync/current-session`
- `POST /api/chat-sync/sessions/{sessionId}/refresh`

`POST /api/drafts` 请求体示例：

```json
{
  "conversation_id": "manual-001",
  "customer_message": "预算300-500，有什么推荐？"
}
```

返回除 `reply_text` 外，还包括：

- `risk_level`
- `reason`
- `customer_stage`
- `intent`
- `should_handoff`
- `reply_type`
- `required_data`
- `used_knowledge`

其中 `used_knowledge` 包含：

- `chunk_id`
- `source_name`
- `category`
- `knowledge_tier`
- `text`
- `tags`

## 审计与反馈闭环

每次草稿生成后，系统会自动保存：

- 原始客户消息
- 风险等级与原因
- 工作流判断结果
- 命中的知识片段 ID
- 生成的回复草稿

可通过以下接口查看和反馈：

- `GET /api/drafts/history`
- `POST /api/drafts/feedback`

前端工作台设置页已接通这套闭环：

- “生成历史”直接读取后端审计记录
- 每条历史支持 `采用 / 改写 / 转人工 / 丢弃`
- 反馈会实时回写到后端审计表

## 知识导入边界

### 前端业务库上传

工作台主入口使用 `POST /api/knowledge/uploads`：

- 请求类型：`multipart/form-data`
- 必填字段：
  - `library_type`
  - `file`
- 上传一次后会持久化保存到本地数据库
- 商品库存库重新上传会全量覆盖当前商品库
- 其余业务库重传时按业务库整体覆盖旧版本

### 通用文本导入

`POST /api/knowledge/imports` 仍然保留，适合命令行或脚本化文本导入：

- 主规则
- FAQ
- 固定话术
- 商品素材
- 发货信息
- 正式售后文件
- 风格样本

命令行示例：

```powershell
$env:PYTHONPATH='E:\Ai jjfajgsw\AIkefu\src'
python -m moments_inventory.cli import-knowledge --file "E:\Ai jjfajgsw\AIkefu\data\faq\发货规则.md" --category "发货" --tier shipping_info --tags "物流,时效" --ai-kefu-config "E:\Ai jjfajgsw\AIkefu\config\ai_kefu.yaml"
```

## 配置说明

`config/ai_kefu.yaml` 可参考 [config/ai_kefu.example.yaml](config/ai_kefu.example.yaml)：

```yaml
workspace_dir: "./data/ai_kefu_workspace"
database_path: "./data/ai_kefu/ai-kefu.db"
embedding_provider: "openai"
embedding_model: "text-embedding-3-small"
chat_provider: "openai_compatible"
chat_model: "gpt-4.1-mini"
chat_provider_options:
  api_base: "https://api.openai.com/v1"
  api_key_env: "AI_KEFU_OPENAI_API_KEY"
  timeout_seconds: 30
api_auth:
  api_key_env: "AI_KEFU_BACKEND_API_KEY"
chat_sync:
  enabled: true
  weflow_base_url: "http://127.0.0.1:5031"
  weflow_access_token_env: "WEFLOW_ACCESS_TOKEN"
  session_poll_limit: 100
  merge_window_seconds: 8
retrieval:
  chunk_size: 600
  chunk_overlap: 120
```

说明：

- `chat_provider: openai_compatible` 使用兼容 OpenAI 的 `POST /chat/completions`
- `AI_KEFU_BACKEND_API_KEY` 可选，用于保护本地后端接口
- 商品导入数据库路径按 `ai_kefu.yaml` 相对目录解析

## 前端启动

```bash
cd frontend/workbench
npm install
npm run dev
```

默认开发代理会把 `/api` 转发到 `http://127.0.0.1:8787`。

如需调整前端开发地址或代理目标，可设置：

- `VITE_DEV_HOST`
- `VITE_DEV_PORT`
- `VITE_API_BASE_URL`
- `VITE_AI_KEFU_API_KEY`

## 手工运行流程

1. 在工作台里粘贴客户消息
2. 在设置页上传 5 类业务库文件
3. 商品更新时重新上传商品库存 Excel
4. 点击生成，查看候选回复、风险等级、流程元数据和命中的知识层
5. 人工确认后再复制回微信发送

## WeFlow 会话同步流程

1. 在 `config/ai_kefu.yaml` 里启用 `chat_sync`
2. 启动 `python -m moments_inventory.cli kefu-dev --host 127.0.0.1 --port 8787 --reload --ai-kefu-config config/ai_kefu.yaml`
3. 打开工作台，在“实际运行”页选择一个私聊会话
4. 新消息会自动追加到“客户消息”区域
5. 打开“自动生成”后，新消息进入会自动触发候选回复生成

如果你改过知识库上传、检索或规则代码，但页面仍提示“未实现解析”这类旧报错，优先怀疑本地后端还是旧实例：

- 直接重新执行 `run_ai_kefu_workbench.bat`
- 或手动重启 `kefu-dev`
- 然后刷新浏览器页面再重试

第一版只支持私聊，不处理群聊，也不会跟随 WeFlow 当前打开窗口自动切换。

## 前端生产构建

```bash
cd frontend/workbench
npm run build
```

构建产物输出到 `frontend/workbench/dist`。

## 当前仍未完成的能力

下面这些还没落地完，不要把当前版本当成完全自动化客服：

- 多台组合推荐器
- 正式人工接管队列或 UI
- 更细粒度的商品资料结构化字段
