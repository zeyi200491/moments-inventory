import type { DraftHistoryItem } from "../types";

type RecentRunCardProps = {
  entry: DraftHistoryItem | null;
  onReuse: (entry: DraftHistoryItem) => void;
};

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

export function RecentRunCard({ entry, onReuse }: RecentRunCardProps) {
  return (
    <section className="panel recent-run-panel">
      <div className="panel-heading panel-heading-spread">
        <div>
          <span className="eyebrow">Quick Recall / 最近一条</span>
          <h2>最近一条生成记录</h2>
          <p className="muted">保留最近一次审计记录，方便快速回看并重新载入当前工作台。</p>
        </div>
        {entry ? <span className="recent-risk">{entry.risk_level}</span> : null}
      </div>

      {!entry ? (
        <div className="empty-state">
          <strong>还没有快捷记录</strong>
          <p>当你生成第一条候选回复后，这里会固定显示最近一条，方便马上复用。</p>
        </div>
      ) : (
        <article className="recent-run-card">
          <div className="history-meta">
            <span>{formatHistoryTimeLabel(entry.created_at)}</span>
            <span>{entry.reason}</span>
          </div>
          <strong>{entry.customer_message}</strong>
          <p>{truncateText(entry.reply_text || "空回复", 88)}</p>
          <div className="history-actions">
            <button className="secondary-button" type="button" onClick={() => onReuse(entry)}>
              载入最近一条
            </button>
          </div>
        </article>
      )}
    </section>
  );
}
