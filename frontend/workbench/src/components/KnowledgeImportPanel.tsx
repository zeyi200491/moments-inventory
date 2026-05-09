import type { ChangeEvent } from "react";

import type {
  KnowledgeImportResponse,
  KnowledgeSourceSummary,
  KnowledgeTier,
} from "../types";

const KNOWLEDGE_TIER_OPTIONS: Array<{ value: KnowledgeTier; label: string }> = [
  { value: "master_rule", label: "主规则文" },
  { value: "fixed_reply", label: "固定话术" },
  { value: "faq", label: "FAQ 规则库" },
  { value: "product_inventory", label: "商品库存库" },
  { value: "product_material", label: "商品素材库" },
  { value: "shipping_info", label: "供应链发货信息库" },
  { value: "after_sale_doc", label: "正式售后文件库" },
  { value: "style_sample", label: "风格样本库" },
];

type KnowledgeImportPanelProps = {
  importCategory: string;
  importKnowledgeTier: KnowledgeTier;
  importTagsText: string;
  importLoading: boolean;
  importMessage: string | null;
  importError: string | null;
  importedSources: KnowledgeSourceSummary[];
  lastImport: KnowledgeImportResponse | null;
  onImportCategoryChange: (value: string) => void;
  onImportKnowledgeTierChange: (value: KnowledgeTier) => void;
  onImportTagsTextChange: (value: string) => void;
  onImportFileChange: (event: ChangeEvent<HTMLInputElement>) => void;
};

const SUPPORTED_SOURCES = [
  "话术库 / FAQ",
  "产品参数与库存说明",
  "历史聊天记录（用于拟人风格）",
  "售后规则、物流规则、营业时间",
];

export function KnowledgeImportPanel({
  importCategory,
  importKnowledgeTier,
  importTagsText,
  importLoading,
  importMessage,
  importError,
  importedSources,
  lastImport,
  onImportCategoryChange,
  onImportKnowledgeTierChange,
  onImportTagsTextChange,
  onImportFileChange,
}: KnowledgeImportPanelProps) {
  return (
    <section className="panel panel-soft">
      <div className="panel-heading">
        <span className="eyebrow">Phase 1 / 知识准备</span>
        <h2>知识库导入</h2>
      </div>
      <p className="muted">
        选择本地文本文件后，工作台会把文件内容发给后端切分入库。当前适合先导入 `txt`、`md`、
        轻量规则说明和整理过的聊天文本。
      </p>

      <div className="source-grid">
        {SUPPORTED_SOURCES.map((item) => (
          <div key={item} className="source-card">
            <span className="source-badge">支持</span>
            <strong>{item}</strong>
          </div>
        ))}
      </div>

      <label className="field">
        <span>知识分类</span>
        <input
          className="text-input"
          value={importCategory}
          onChange={(event) => onImportCategoryChange(event.target.value)}
          placeholder="例如：售后 / 产品 / 物流 / 话术"
        />
      </label>

      <label className="field">
        <span>知识层级</span>
        <select
          className="text-input"
          value={importKnowledgeTier}
          onChange={(event) => onImportKnowledgeTierChange(event.target.value as KnowledgeTier)}
        >
          {KNOWLEDGE_TIER_OPTIONS.map((option) => (
            <option key={option.value} value={option.value}>
              {option.label} / {option.value}
            </option>
          ))}
        </select>
      </label>

      <label className="field">
        <span>标签</span>
        <input
          className="text-input"
          value={importTagsText}
          onChange={(event) => onImportTagsTextChange(event.target.value)}
          placeholder="用逗号分隔，例如：退款,到账,售后"
        />
      </label>

      <label className="upload-box">
        <span>{importLoading ? "导入中..." : "选择知识文件并导入"}</span>
        <input type="file" accept=".txt,.md,.csv" onChange={onImportFileChange} disabled={importLoading} />
      </label>

      {importMessage ? (
        <div className="success-box" role="status">
          {importMessage}
        </div>
      ) : null}
      {importError ? (
        <div className="error-box" role="alert">
          {importError}
        </div>
      ) : null}

      {lastImport ? (
        <div className="note-box">
          <span>最近一次导入</span>
          <p>
            {lastImport.source_name} / {lastImport.category} / {lastImport.knowledge_tier} / 共{" "}
            {lastImport.chunk_count} 段
          </p>
        </div>
      ) : null}

      <div className="panel-heading">
        <h2>已导入知识源</h2>
      </div>
      {importedSources.length === 0 ? (
        <p className="muted">还没有导入知识文件。</p>
      ) : (
        <div className="history-list">
          {importedSources.map((item) => (
            <article key={`${item.source_name}-${item.category}`} className="source-summary-card">
              <div className="evidence-head">
                <strong>{item.source_name}</strong>
                <span>
                  {item.category} / {item.knowledge_tier} / {item.chunk_count} 段
                </span>
              </div>
              {item.tags.length > 0 ? (
                <div className="tag-row">
                  {item.tags.map((tag) => (
                    <span key={tag} className="mini-tag">
                      {tag}
                    </span>
                  ))}
                </div>
              ) : null}
            </article>
          ))}
        </div>
      )}
    </section>
  );
}
