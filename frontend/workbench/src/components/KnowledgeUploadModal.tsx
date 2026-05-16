import type { ChangeEvent, DragEvent } from "react";

import type { KnowledgeLibraryType } from "../types";

const LIBRARY_OPTIONS: Array<{
  value: KnowledgeLibraryType;
  label: string;
  hint: string;
  accept: ".md" | ".xlsx" | ".xlsx,.xls";
}> = [
  {
    value: "master_rule_bundle",
    label: "主规则文件",
    hint: "支持 Markdown，系统会自动拆分主规则和 FAQ。",
    accept: ".md",
  },
  {
    value: "product_inventory_excel",
    label: "商品库存库",
    hint: "支持 .xlsx 和 .xls，上传后会同时更新库存信息与素材信息。",
    accept: ".xlsx,.xls",
  },
  {
    value: "shipping_info_excel",
    label: "供应链发货信息库",
    hint: "支持 Excel，按每行一条发货规则入库。",
    accept: ".xlsx,.xls",
  },
  {
    value: "style_sample_md",
    label: "风格样本库",
    hint: "支持 Markdown，只影响语气，不参与业务规则判断。",
    accept: ".md",
  },
];

type KnowledgeUploadModalProps = {
  open: boolean;
  importLoading: boolean;
  importError: string | null;
  selectedLibraryType: KnowledgeLibraryType;
  onLibraryTypeChange: (value: KnowledgeLibraryType) => void;
  onFileChange: (event: ChangeEvent<HTMLInputElement>) => void;
  onDrop: (event: DragEvent<HTMLDivElement>) => void;
  onClose: () => void;
};

export function KnowledgeUploadModal({
  open,
  importLoading,
  importError,
  selectedLibraryType,
  onLibraryTypeChange,
  onFileChange,
  onDrop,
  onClose,
}: KnowledgeUploadModalProps) {
  if (!open) {
    return null;
  }

  const currentOption =
    LIBRARY_OPTIONS.find((option) => option.value === selectedLibraryType) ?? LIBRARY_OPTIONS[0];

  return (
    <div className="upload-modal-backdrop">
      <div className="upload-modal" role="dialog" aria-modal="true" aria-labelledby="upload-modal-title">
        <div className="upload-modal-header">
          <div>
            <span className="eyebrow">Business Library / 业务知识库上传</span>
            <h2 id="upload-modal-title">上传知识库文件</h2>
          </div>
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

        <label className="field">
          <span>业务库类型</span>
          <select
            className="text-input"
            value={currentOption.value}
            onChange={(event) => onLibraryTypeChange(event.target.value as KnowledgeLibraryType)}
            disabled={importLoading}
            aria-label="业务库类型"
          >
            {LIBRARY_OPTIONS.map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
          </select>
        </label>

        <div className="knowledge-library-hint-card">
          <strong>{currentOption.label}</strong>
          <p>{currentOption.hint}</p>
          <span>文件格式：{currentOption.accept}</span>
        </div>

        {selectedLibraryType === "product_inventory_excel" ? (
          <div className="warning-box knowledge-library-warning">重新上传会全量覆盖当前商品库</div>
        ) : null}

        <div className="upload-dropzone" onDragOver={(event) => event.preventDefault()} onDrop={onDrop}>
          <div className="upload-icon" aria-hidden="true">
            ⇪
          </div>
          <strong>{importLoading ? "上传中..." : "点击或将文件拖拽到此进行上传"}</strong>
          <span>当前仅支持 {currentOption.accept} 文件</span>
          <span>单文件不超过 10MB</span>
          <label className="upload-picker">
            <span>选择文件</span>
            <input
              type="file"
              accept={currentOption.accept}
              onChange={onFileChange}
              disabled={importLoading}
              aria-label="选择文件"
            />
          </label>
        </div>

        {importError ? (
          <div className="error-box" role="alert">
            {importError}
          </div>
        ) : null}
      </div>
    </div>
  );
}
