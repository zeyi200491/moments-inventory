import type { DraftResponse, KnowledgeTier, RiskLevel } from "../types";

type ReplyDraftPanelProps = {
  draft: DraftResponse | null;
  errorMessage: string | null;
  copyFeedback: string | null;
  copySucceeded: boolean;
  onCopy: () => void;
  onRetry: () => void;
};

const RISK_LABELS: Record<RiskLevel, string> = {
  L1: "L1 辅助",
  L2: "L2 白名单",
  L3: "L3 需确认",
  L4: "L4 转人工",
};

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

function renderDecisionStatus(shouldHandoff: boolean) {
  return shouldHandoff ? "需人工接管" : "可继续处理";
}

export function ReplyDraftPanel({
  draft,
  errorMessage,
  copyFeedback,
  copySucceeded,
  onCopy,
  onRetry,
}: ReplyDraftPanelProps) {
  const isEmptyReply = Boolean(draft && !draft.reply_text.trim());

  return (
    <section className="panel panel-emphasis panel-review">
      <div className="panel-heading panel-heading-spread">
        <div>
          <span className="eyebrow">Reply Review / 审阅结果</span>
          <h2>回复审阅</h2>
          <p className="muted">这里会展示候选回复、流程判断、风险等级和命中依据。</p>
        </div>
        {draft ? (
          <button
            className={`secondary-button${copySucceeded ? " secondary-button-success" : ""}`}
            onClick={onCopy}
          >
            {copySucceeded ? "已复制" : "复制回复"}
          </button>
        ) : null}
      </div>

      {errorMessage ? (
        <div className="error-box" role="alert">
          {errorMessage}
        </div>
      ) : null}

      {!draft ? (
        <div className="empty-state">
          <strong>暂时还没有结果</strong>
          <p>输入客户消息并点击生成后，这里会展示候选回复、流程判断和命中的知识片段。</p>
        </div>
      ) : (
        <>
          <div className="reply-card">
            <div className="reply-meta">
              <span className={`risk-badge risk-${draft.risk_level.toLowerCase()}`}>
                {RISK_LABELS[draft.risk_level]}
              </span>
              <span className="muted">{draft.reason}</span>
            </div>

            <div className="reply-meta-grid">
              <div className="meta-chip">
                <span className="meta-chip-label">阶段</span>
                <strong>{draft.customer_stage}</strong>
              </div>
              <div className="meta-chip">
                <span className="meta-chip-label">意图</span>
                <strong>{draft.intent}</strong>
              </div>
              <div className="meta-chip">
                <span className="meta-chip-label">回复类型</span>
                <strong>{draft.reply_type}</strong>
              </div>
              <div className="meta-chip">
                <span className="meta-chip-label">流转建议</span>
                <strong>{renderDecisionStatus(draft.should_handoff)}</strong>
              </div>
            </div>

            {draft.required_data.length > 0 ? (
              <div className="reply-required-data">
                <span className="meta-chip-label">当前缺口</span>
                <div className="tag-row">
                  {draft.required_data.map((item) => (
                    <span key={item} className="mini-tag">
                      {item}
                    </span>
                  ))}
                </div>
              </div>
            ) : null}

            {isEmptyReply ? (
              <div className="warning-box" role="alert">
                <strong>模型返回了空回复</strong>
                <p>这次没有得到可发送的正文，建议重试一次，或检查知识命中是否过少。</p>
                <button className="secondary-button" onClick={onRetry} type="button">
                  重试生成
                </button>
              </div>
            ) : (
              <pre className="reply-text">{draft.reply_text}</pre>
            )}
            {copyFeedback ? (
              <span className="copy-feedback" role="status">
                {copyFeedback}
              </span>
            ) : null}
          </div>

          <div className="evidence-list">
            {draft.used_knowledge.length === 0 ? (
              <div className="evidence-empty">本次没有命中显式知识片段，属于兜底回复。</div>
            ) : (
              draft.used_knowledge.map((item) => (
                <article key={item.chunk_id} className="evidence-card">
                  <div className="evidence-head">
                    <strong>{item.source_name}</strong>
                    <span>{item.category}</span>
                  </div>
                  <div className="tag-row">
                    <span className="mini-tag mini-tag-tier">
                      {KNOWLEDGE_TIER_LABELS[item.knowledge_tier]} / {item.knowledge_tier}
                    </span>
                    {item.tags.map((tag) => (
                      <span key={tag} className="mini-tag">
                        {tag}
                      </span>
                    ))}
                  </div>
                  <p>{item.text}</p>
                </article>
              ))
            )}
          </div>
        </>
      )}
    </section>
  );
}
