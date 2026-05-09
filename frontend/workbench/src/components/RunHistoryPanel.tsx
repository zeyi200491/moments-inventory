import { useState } from "react";

import type { DraftHistoryItem } from "../types";

type DraftFeedbackStatus = "adopted" | "edited" | "handoff" | "discarded";

type RunHistoryPanelProps = {
  history: DraftHistoryItem[];
  onReuse: (entry: DraftHistoryItem) => void;
  onFeedback: (entry: DraftHistoryItem, finalStatus: DraftFeedbackStatus) => void | Promise<void>;
};

const STATUS_LABELS: Record<string, string> = {
  generated: "待处理",
  adopted: "已采用",
  edited: "已改写",
  handoff: "已转人工",
  discarded: "已丢弃",
};

const FEEDBACK_ACTIONS: Array<{ label: string; status: DraftFeedbackStatus }> = [
  { label: "标记为采用", status: "adopted" },
  { label: "标记为改写", status: "edited" },
  { label: "标记为转人工", status: "handoff" },
  { label: "标记为丢弃", status: "discarded" },
];

function truncateText(value: string, maxLength: number) {
  return value.length > maxLength ? `${value.slice(0, maxLength)}…` : value;
}

function formatHistoryTimeLabel(value: string) {
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) {
    return value;
  }
  return new Intl.DateTimeFormat("zh-CN", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  }).format(parsed);
}

export function RunHistoryPanel({ history, onReuse, onFeedback }: RunHistoryPanelProps) {
  const [expandedIds, setExpandedIds] = useState<Set<string>>(new Set());

  function toggleExpanded(id: string) {
    setExpandedIds((current) => {
      const next = new Set(current);
      if (next.has(id)) {
        next.delete(id);
      } else {
        next.add(id);
      }
      return next;
    });
  }

  return (
    <section className="panel">
      <div className="panel-heading">
        <span className="eyebrow">Session Memory / 最近记录</span>
        <h2>最近生成历史</h2>
      </div>
      {history.length === 0 ? (
        <p className="muted">还没有历史记录。每次生成成功后，这里会自动保留最近几次会话。</p>
      ) : (
        <div className="history-list">
          {history.map((item) => {
            const isExpanded = expandedIds.has(item.draft_id);
            const createdAtLabel = formatHistoryTimeLabel(item.created_at);
            return (
              <article key={item.draft_id} className="history-card">
                <div className="history-meta">
                  <span>{item.risk_level}</span>
                  <time dateTime={item.created_at}>{createdAtLabel}</time>
                </div>
                <div className="history-status-row">
                  <span className="history-status-badge">
                    {STATUS_LABELS[item.final_status] ?? item.final_status}
                  </span>
                  <span className="muted">{item.reason}</span>
                </div>
                <strong title={item.customer_message}>
                  {isExpanded ? item.customer_message : truncateText(item.customer_message, 28)}
                </strong>
                <p title={item.reply_text || "空回复"}>
                  {isExpanded ? item.reply_text || "空回复" : truncateText(item.reply_text || "空回复", 42)}
                </p>
                <div className="history-actions">
                  <button
                    className="secondary-button"
                    onClick={() => toggleExpanded(item.draft_id)}
                    type="button"
                    aria-label={isExpanded ? "收起完整内容" : "展开完整内容"}
                  >
                    {isExpanded ? "收起" : "展开"}
                  </button>
                  <button
                    className="secondary-button"
                    onClick={() => onReuse(item)}
                    type="button"
                    aria-label={`重新载入 ${createdAtLabel} 的历史记录`}
                  >
                    载入此记录
                  </button>
                </div>
                <div className="history-feedback-actions">
                  {FEEDBACK_ACTIONS.map((action) => (
                    <button
                      key={action.status}
                      className="secondary-button"
                      type="button"
                      onClick={() => onFeedback(item, action.status)}
                      aria-label={action.label}
                    >
                      {action.label}
                    </button>
                  ))}
                </div>
              </article>
            );
          })}
        </div>
      )}
    </section>
  );
}
