import type { KnowledgeLibraryState, KnowledgeLibraryType, KnowledgeLibraryUploadResponse } from "../types";

const LIBRARY_CARDS: Array<{
  libraryType: KnowledgeLibraryType;
  title: string;
  description: string;
  fileTypeHint: string;
}> = [
  {
    libraryType: "master_rule_bundle",
    title: "主规则文件",
    description: "主规则和 FAQ 共用一个 Markdown，上传后会自动拆分入库。",
    fileTypeHint: ".md",
  },
  {
    libraryType: "product_inventory_excel",
    title: "商品库存库",
    description: "型号、品牌、价格、成本、利润空间，以及实拍图和验机视频等素材线索统一从库存表导入。",
    fileTypeHint: ".xlsx / .xls",
  },
  {
    libraryType: "shipping_info_excel",
    title: "供应链发货信息库",
    description: "供应商发货地、快递方式和偏远限制，按每行一条发货规则入库。",
    fileTypeHint: ".xlsx",
  },
  {
    libraryType: "style_sample_md",
    title: "风格样本库",
    description: "只影响语气，不参与业务规则判断。",
    fileTypeHint: ".md",
  },
];

type KnowledgeLibraryViewProps = {
  libraries: KnowledgeLibraryState[];
  importMessage: string | null;
  importError: string | null;
  lastUpload: KnowledgeLibraryUploadResponse | null;
  onOpenUpload: (libraryType?: KnowledgeLibraryType) => void;
};

function formatUploadedAt(value: string | null | undefined) {
  if (!value) {
    return "未上传";
  }

  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) {
    return value;
  }

  return parsed.toLocaleString("zh-CN", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  });
}

function renderStatusClass(status: string | undefined) {
  if (status === "active") {
    return "library-status library-status-active";
  }
  return "library-status";
}

export function KnowledgeLibraryView({
  libraries,
  importMessage,
  importError,
  lastUpload,
  onOpenUpload,
}: KnowledgeLibraryViewProps) {
  const libraryByType = new Map(libraries.map((item) => [item.library_type, item]));

  return (
    <section className="panel knowledge-panel">
      <div className="knowledge-toolbar">
        <div>
          <span className="eyebrow">Knowledge Center / 知识库管理</span>
          <h2>知识库管理</h2>
          <p className="muted">上传一次就记住，商品库存库支持随时重新上传并全量覆盖。</p>
        </div>
        <button type="button" className="add-button" onClick={() => onOpenUpload()}>
          上传知识库
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

      <div className="knowledge-library-grid">
        {LIBRARY_CARDS.map((card) => {
          const library = libraryByType.get(card.libraryType);
          const uploaded = Boolean(library);
          const isLatest = lastUpload?.library_type === card.libraryType;

          return (
            <article key={card.libraryType} className="knowledge-library-card">
              <div className="knowledge-library-card-head">
                <div>
                  <span className="knowledge-library-filetype">{card.fileTypeHint}</span>
                  <h3>{card.title}</h3>
                </div>
                <span className={renderStatusClass(library?.status)}>
                  {uploaded ? (isLatest ? "刚刚更新" : "已上传") : "未上传"}
                </span>
              </div>

              <p className="muted knowledge-library-description">{card.description}</p>

              <dl className="knowledge-library-meta">
                <div>
                  <dt>当前文件</dt>
                  <dd>{library?.original_filename ?? "未上传"}</dd>
                </div>
                <div>
                  <dt>上传时间</dt>
                  <dd>{formatUploadedAt(library?.uploaded_at)}</dd>
                </div>
                <div>
                  <dt>数据条数</dt>
                  <dd>{library?.imported_count ?? 0}</dd>
                </div>
                <div>
                  <dt>跳过行数</dt>
                  <dd>{library?.skipped_count ?? 0}</dd>
                </div>
              </dl>

              {card.libraryType === "product_inventory_excel" ? (
                <div className="warning-box knowledge-library-warning">
                  重新上传会全量覆盖当前商品库
                </div>
              ) : null}

              <div className="knowledge-library-actions">
                <button
                  type="button"
                  className="action-button action-button-inline"
                  onClick={() => onOpenUpload(card.libraryType)}
                >
                  {uploaded ? "重新上传" : "上传"}
                </button>
              </div>
            </article>
          );
        })}
      </div>
    </section>
  );
}
