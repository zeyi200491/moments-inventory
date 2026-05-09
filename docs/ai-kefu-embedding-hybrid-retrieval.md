# AI 客服 Embedding 混合检索说明

## 当前能力

系统已经接入可降级的 `embedding_provider` 链路：

- 知识导入时，会按 chunk 文本批量尝试生成 embedding。
- embedding 会直接存入 SQLite 的 `knowledge_chunks.embedding_json`。
- 草稿生成时，会先为用户消息生成 query embedding。
- 检索阶段会在现有关键词 / BM25 风格打分基础上，叠加 query embedding 与 chunk embedding 的余弦相似度。

这意味着当前检索已经从“纯关键词路由”升级为“关键词 + 向量混合召回”。

## 降级策略

以下任一情况发生时，系统会自动回退到原有关键词检索，不阻断导入或草稿生成：

- 未配置 `AI_KEFU_OPENAI_API_KEY`
- `embedding_provider` 未启用或不受支持
- provider 请求失败
- provider 返回向量数量与输入数量不一致
- 某个 chunk 还没有 embedding

## 配置方式

`config/ai_kefu.yaml` 或 `config/ai_kefu.example.yaml` 需要包含：

```yaml
embedding_provider: "openai"
embedding_model: "text-embedding-3-small"
chat_provider: "openai_compatible"
chat_provider_options:
  api_base: "https://api.openai.com/v1"
  api_key_env: "AI_KEFU_OPENAI_API_KEY"
  timeout_seconds: 30
```

说明：

- 当前 embedding 复用 OpenAI-compatible 的 `api_base` 和 `api_key_env`。
- 如果只想跑关键词检索，不配置 key 也可以正常启动。
- 当前没有引入独立向量数据库，embedding 直接保存在 SQLite。

## 当前边界

这次实现解决的是“向量链路接通 + 混合召回可用”，还没做到以下增强项：

- 独立向量索引或 ANN 检索
- 外部 reranker
- 多 provider 切换策略
- embedding 刷新任务与批量重建工具

这些属于下一阶段增强，不影响当前版本投入内部验证。
