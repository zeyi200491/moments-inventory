import type { ChangeEvent, DragEvent } from "react";

import { STRUCTURED_KNOWLEDGE_SCHEMAS, isStructuredKnowledgeTier } from "../structuredKnowledge";
import type { KnowledgeTier } from "../types";

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

type KnowledgeUploadModalProps = {
  open: boolean;
  importLoading: boolean;
  importError: string | null;
  importCategory: string;
  importKnowledgeTier: KnowledgeTier;
  importTagsText: string;
  structuredSourceName: string;
  structuredFields: Record<string, string>;
  onImportCategoryChange: (value: string) => void;
  onImportKnowledgeTierChange: (value: KnowledgeTier) => void;
  onImportTagsTextChange: (value: string) => void;
  onStructuredSourceNameChange: (value: string) => void;
  onStructuredFieldChange: (fieldKey: string, value: string) => void;
  onStructuredSubmit: () => void;
  onFileChange: (event: ChangeEvent<HTMLInputElement>) => void;
  onDrop: (event: DragEvent<HTMLDivElement>) => void;
  onClose: () => void;
};

export function KnowledgeUploadModal({
  open,
  importLoading,
  importError,
  importCategory,
  importKnowledgeTier,
  importTagsText,
  structuredSourceName,
  structuredFields,
  onImportCategoryChange,
  onImportKnowledgeTierChange,
  onImportTagsTextChange,
  onStructuredSourceNameChange,
  onStructuredFieldChange,
  onStructuredSubmit,
  onFileChange,
  onDrop,
  onClose,
}: KnowledgeUploadModalProps) {
  if (!open) {
    return null;
  }

  const structuredSchema = isStructuredKnowledgeTier(importKnowledgeTier)
    ? STRUCTURED_KNOWLEDGE_SCHEMAS[importKnowledgeTier]
    : null;

  return (
    <div className="upload-modal-backdrop">
      <div className="upload-modal" role="dialog" aria-modal="true" aria-labelledby="upload-modal-title">
        <div className="upload-modal-header">
          <h2 id="upload-modal-title">请选择要添加的文件</h2>
          <button
            type="button"
            className="modal-close"
            onClick={onClose}
            aria-label="关闭上传面板"
            disabled={importLoading}
          >
            ×
          </button>
        </div>

        <div
          className="upload-dropzone"
          onDragOver={(event) => event.preventDefault()}
          onDrop={onDrop}
        >
          <div className="upload-icon" aria-hidden="true">
            ⬆
          </div>
          <strong>{importLoading ? "上传中..." : "点击或将文件拖拽至此进行上传"}</strong>
          <span>支持 txt / md / csv</span>
          <span>单文件不超过 10MB</span>
          <label className="upload-picker">
            <span>选择文件</span>
            <input type="file" accept=".txt,.md,.csv" onChange={onFileChange} disabled={importLoading} />
          </label>
        </div>

        <div className="upload-form-grid">
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
        </div>

        {structuredSchema ? (
          <section className="structured-import-panel">
            <div className="panel-heading panel-heading-compact">
              <span className="eyebrow">Structured Entry / 专用录入</span>
              <h2>{structuredSchema.title}</h2>
              <p className="muted">这三类知识建议直接按字段录入，避免后续检索时文本结构混乱。</p>
            </div>
            <div className="upload-form-grid">
              <label className="field">
                <span>条目名称</span>
                <input
                  className="text-input"
                  value={structuredSourceName}
                  onChange={(event) => onStructuredSourceNameChange(event.target.value)}
                  placeholder="例如：supplier-laowang-shenzhen"
                />
              </label>
              {structuredSchema.fields.map((field) => (
                <label key={field.key} className="field">
                  <span>{field.label}</span>
                  <input
                    className="text-input"
                    value={structuredFields[field.key] ?? ""}
                    onChange={(event) => onStructuredFieldChange(field.key, event.target.value)}
                    placeholder={field.placeholder}
                  />
                </label>
              ))}
            </div>
            <div className="history-actions">
              <button
                type="button"
                className="action-button action-button-inline"
                onClick={onStructuredSubmit}
                disabled={importLoading}
              >
                保存结构化条目
              </button>
            </div>
          </section>
        ) : null}

        {importError ? (
          <div className="error-box" role="alert">
            {importError}
          </div>
        ) : null}
      </div>
    </div>
  );
}
