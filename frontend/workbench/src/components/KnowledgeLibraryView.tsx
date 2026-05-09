import type { KnowledgeImportResponse, KnowledgeSourceSummary, KnowledgeTier } from "../types";

const KNOWLEDGE_TIER_LABELS: Record<KnowledgeTier, string> = {
  master_rule: "主规则文",
  fixed_reply: "固定话术",
  faq: "FAQ 规则库",
  product_inventory: "商品库存库",
  product_material: "商品素材库",
  shipping_info: "供应链发货信息库",
  after_sale_doc: "正式售后文件库",
  style_sample: "风格样本库",
};

type KnowledgeLibraryViewProps = {
  importedSources: KnowledgeSourceSummary[];
  importMessage: string | null;
  importError: string | null;
  lastImport: KnowledgeImportResponse | null;
  onOpenUpload: () => void;
};

function renderTags(item: KnowledgeSourceSummary) {
  if (item.tags.length === 0) {
    return "-";
  }

  return item.tags.join(" / ");
}

export function KnowledgeLibraryView({
  importedSources,
  importMessage,
  importError,
  lastImport,
  onOpenUpload,
}: KnowledgeLibraryViewProps) {
  return (
    <section className="panel knowledge-panel">
      <div className="knowledge-toolbar">
        <div>
          <span className="eyebrow">Knowledge Center / 文件管理</span>
          <h2>知识文件管理</h2>
          <p className="muted">把知识资料整理成清晰表格，导入后立即参与回复生成。</p>
        </div>
        <button type="button" className="add-button" onClick={onOpenUpload}>
          + 添加
        </button>
      </div>

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

      <div className="knowledge-table-wrap">
        <table className="knowledge-table">
          <thead>
            <tr>
              <th>文件名</th>
              <th>分类</th>
              <th>知识层</th>
              <th>分段数</th>
              <th>备注</th>
            </tr>
          </thead>
          <tbody>
            {importedSources.length === 0 ? (
              <tr>
                <td colSpan={5}>
                  <div className="empty-state">
                    <strong>还没有知识文件</strong>
                    <p>点击右上角“添加”，把 txt / md / csv 文件导入进来。</p>
                  </div>
                </td>
              </tr>
            ) : (
              importedSources.map((item) => (
                <tr key={`${item.source_name}-${item.category}`}>
                  <td className="knowledge-file-cell">
                    <strong>{item.source_name}</strong>
                    <span>{lastImport?.source_name === item.source_name ? "刚刚导入" : "已入库"}</span>
                  </td>
                  <td>{item.category}</td>
                  <td>
                    {KNOWLEDGE_TIER_LABELS[item.knowledge_tier]} / {item.knowledge_tier}
                  </td>
                  <td>{item.chunk_count}</td>
                  <td>{renderTags(item)}</td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>
    </section>
  );
}
