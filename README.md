# 微信朋友圈工具 + AI 客服工作台

这个仓库当前包含两条能力线：

1. 基于 WeFlow 的朋友圈内容抓取、识别和导出
2. 面向微信人工客服场景的 AI 辅助工作台

## 朋友圈工具

仓库原始能力是一个面向 Windows 的命令行工具，用来通过 WeFlow HTTP API 抓取朋友圈内容，识别 CCD 商品信息，并导出：

- 当前在售 Excel
- 历史总库 Excel
- 对应的本地图片和视频

### 快速开始

1. 运行 `setup_windows.bat`
2. 配置 `config/config.yaml`
3. 配置 `config/models.txt`
4. 设置环境变量 `WEFLOW_ACCESS_TOKEN`
5. 运行 `run_export.bat`

详细说明见 [docs/windows-使用说明.md](/E:/Ai%20jjfajgsw/AIkefu/docs/windows-%E4%BD%BF%E7%94%A8%E8%AF%B4%E6%98%8E.md)。

### 命令行入口

```bash
python -m moments_inventory.cli sync
python -m moments_inventory.cli export
python -m moments_inventory.cli sync --export
python -m moments_inventory.cli warmup --export
```

## AI 客服工作台

当前 AI 客服后端已经从普通“检索 + 生成”升级到“规则驱动草稿生成”。

### 当前已落地能力

- 主规则常驻注入
- 会话阶段识别与阶段持久化
- 风险等级识别
- 固定话术锁定机制
- 预算驱动的商品筛选
- 显式偏好叠加筛选
- 利润计算、同款优先、多人购买利润校验
- 知识库分层与权重策略
- WeFlow 会话同步到工作台

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
  - 只有客户显式提出偏好，才叠加品牌 / 功能正常 / 验机视频 / 出片图筛选
- 知识召回规则：
  - `master_rule`：常驻注入
  - `fixed_reply`：单独命中，不走普通检索
  - `faq`：默认业务知识层
  - `product_inventory`：结构化库存层，参与预算筛货与推荐
  - `product_material`：只在验机、配件、续航、导出、需查询后回答等场景按需召回
  - `shipping_info`：发货、物流、仓库、供应链相关问题优先召回
  - `after_sale_doc`：售后、退款、质保、赔付边界问题优先召回
  - `style_sample`：只用于风格，不参与业务检索

### 当前检索实现状态

当前检索已经从“纯字符串碰撞”升级为本地混合检索：

- 先按 `knowledge_tier + workflow` 做分层路由
- 层内使用 BM25 风格词项打分
- 同时保留标签命中、短语命中和同层保守兜底
- 对发货、售后、商品素材库做单独定向召回

当前已经接入可降级的向量混合检索，但还**没有**外部重排模型或独立向量索引。

`embedding_provider` 现在已经进入实际检索链路：导入知识时会 best-effort 生成 chunk embedding，生成草稿时会 best-effort 生成 query embedding；如果 provider 不可用或向量缺失，则自动降级回关键词检索。

### 七类知识库

当前工作台已经把知识库显式建模为 7 类，导入时可以直接指定 `knowledge_tier`：

- `master_rule`：主规则文，决定流程、优先级、禁止项和转人工边界
- `product_inventory`：商品库存库，走结构化 Excel 导入
- `product_material`：商品素材库，例如出片图、验机说明、配件说明
- `faq`：FAQ 规则库，例如砍价、售后、配件、发货、电池、导出、预定
- `shipping_info`：供应链发货信息库，例如仓库位置、发货时效、物流链路
- `after_sale_doc`：正式售后文件库，例如退款、退货、质保、赔付边界
- `style_sample`：风格样本库，只影响表达，不参与业务决策

### 结构化商品库

当前商品库已支持从 Excel 导入最小结构化字段，导入入口是单独链路，不走普通知识库导入。

当前结构化字段包括：

- `brand`
- `model_std`
- `is_functional`
- `has_inspection_video`
- `has_sample_output`
- `cost_price`
- `sale_price`
- `profit_amount`

当前真实在售表可通过以下命令导入：

```powershell
$env:PYTHONPATH='E:\Ai jjfajgsw\AIkefu\src'
python -m moments_inventory.cli import-products --xlsx "E:\Ai jjfajgsw\AIkefu\config\output\当前在售库.xlsx" --ai-kefu-config "E:\Ai jjfajgsw\AIkefu\config\ai_kefu.yaml"
```

### 后端启动

```bash
set AI_KEFU_OPENAI_API_KEY=你的真实密钥
python -m moments_inventory.cli kefu-dev --host 127.0.0.1 --port 8787 --ai-kefu-config config/ai_kefu.yaml
```

启动后可用接口：

- `GET /api/health`
- `POST /api/drafts`
- `GET /api/drafts/history`
- `POST /api/drafts/feedback`
- `GET /api/knowledge/sources`
- `POST /api/knowledge/imports`
- `GET /api/chat-sync/sessions`
- `GET /api/chat-sync/sessions/{sessionId}`
- `POST /api/chat-sync/current-session`
- `POST /api/chat-sync/sessions/{sessionId}/refresh`

`POST /api/drafts` 当前请求体示例：

```json
{
  "conversation_id": "manual-001",
  "customer_message": "预算300-500，有什么推荐"
}
```

`POST /api/drafts` 当前返回除了 `reply_text` 外，还会附带：

- `risk_level`
- `reason`
- `customer_stage`
- `intent`
- `should_handoff`
- `reply_type`
- `required_data`
- `used_knowledge`

其中 `used_knowledge` 已包含：

- `chunk_id`
- `source_name`
- `category`
- `knowledge_tier`
- `text`
- `tags`

### 审计与反馈闭环

每次草稿生成后，系统会自动保存：

- 原始客户消息
- 风险等级与原因
- 工作流判断结果
- 命中的知识片段 ID
- 生成的回复草稿

当前可通过以下接口查看和反馈：

- `GET /api/drafts/history`：读取最近生成记录
- `POST /api/drafts/feedback`：回写 `generated / adopted / edited / handoff / discarded`

这套闭环的目标是让后续规则优化、知识补库和人工复盘有可追踪依据。

前端工作台当前也已接通这套闭环：

- 设置页“最近生成历史”直接读取后端审计记录
- 每条历史支持 `采用 / 改写 / 转人工 / 丢弃`
- 反馈会实时回写到后端审计表，而不是只保留前端内存态

### 知识库导入边界

当前知识库导入接口 `POST /api/knowledge/imports` 仍然支持通用文本导入，并支持显式传入 `knowledge_tier`，适合：

- 主规则
- FAQ
- 固定话术
- 商品素材
- 供应链发货信息
- 正式售后文件
- 风格样本

不适合直接导入商品 Excel。

其中这 3 类已经补了结构化入口，不必先手工整理成 txt：

- `product_material`
- `shipping_info`
- `after_sale_doc`

结构化导入可以通过 `structured_fields` 提交，后端会自动拼装标准化文本并补充关键标签。
前端上传弹窗也已经提供对应专用字段表单，可直接保存结构化条目。

商品 Excel 应走单独的 `import-products` 导入链路，而不是塞进普通知识库。

前端工作台的上传弹窗现在也已经支持显式选择 `knowledge_tier`，不需要再手动依赖分类名推断。

当前也支持命令行导入文本知识：

```powershell
$env:PYTHONPATH='E:\Ai jjfajgsw\AIkefu\src'
python -m moments_inventory.cli import-knowledge --file "E:\Ai jjfajgsw\AIkefu\data\faq\发货规则.md" --category "发货" --tier shipping_info --tags "物流,时效" --ai-kefu-config "E:\Ai jjfajgsw\AIkefu\config\ai_kefu.yaml"
```

### 配置说明

`config/ai_kefu.yaml` 可参考 [config/ai_kefu.example.yaml](/E:/Ai%20jjfajgsw/AIkefu/config/ai_kefu.example.yaml)：

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
  weflow_base_url: "http://127.0.0.1:8080"
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

### 前端启动

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

### 手工运行流程

1. 在工作台里粘贴客户消息
2. 在设置页导入本地规则类文本知识
3. 单独导入商品 Excel 到结构化商品库
4. 点击生成，查看候选回复、风险等级、流程元数据和命中的知识层
5. 人工确认后再复制回微信发送

### WeFlow 会话同步流程

1. 在 `config/ai_kefu.yaml` 里启用 `chat_sync`
2. 启动 `python -m moments_inventory.cli kefu-dev --host 127.0.0.1 --port 8787 --ai-kefu-config config/ai_kefu.yaml`
3. 打开工作台，在“实际运行”页选择一个私聊会话
4. 新消息会自动追加到“客户消息”区域
5. 打开“自动生成”后，新消息进入会自动触发候选回复生成

第一版只支持私聊，不处理群聊，也不会跟随 WeFlow 当前打开窗口自动切换。

### 前端生产构建

```bash
cd frontend/workbench
npm run build
```

构建产物输出到 `frontend/workbench/dist`。

## 当前仍未完成的能力

下面这些还没落地完，不要把当前版本当成完全自动化客服：

- 多台组合推荐器
- 正式人工接管队列或 UI
- 商品资料更细粒度结构化字段
