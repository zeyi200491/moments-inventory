import type { ChatSyncSession } from "../types";

type ChatSessionListProps = {
  sessions: ChatSyncSession[];
  currentSessionId: string | null;
  onSelect: (sessionId: string) => void;
};

function formatSessionTime(timestamp: number) {
  if (!timestamp) {
    return "--";
  }

  return new Intl.DateTimeFormat("zh-CN", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  }).format(new Date(timestamp * 1000));
}

export function ChatSessionList({
  sessions,
  currentSessionId,
  onSelect,
}: ChatSessionListProps) {
  return (
    <aside className="chat-session-panel panel panel-soft panel-nav">
      <div className="panel-heading panel-heading-compact">
        <span className="eyebrow">Session Nav / 会话导航</span>
        <h2>会话导航</h2>
        <p className="muted">先选客户，再把最新消息同步到中间工作台。</p>
      </div>

      {sessions.length === 0 ? (
        <div className="empty-state">
          <strong>还没有可用会话</strong>
          <p>如果 WeFlow 已经有私聊消息，这里会显示可同步的客户会话。</p>
        </div>
      ) : (
        <div className="chat-session-list">
          {sessions.map((session) => (
            <button
              key={session.sessionId}
              type="button"
              className="chat-session-item"
              aria-label={session.displayName}
              aria-pressed={currentSessionId === session.sessionId}
              onClick={() => onSelect(session.sessionId)}
            >
              <div className="chat-session-head">
                <strong>{session.displayName}</strong>
                <span>{formatSessionTime(session.lastTimestamp)}</span>
              </div>
              <div className="chat-session-meta">
                <span>{session.unreadCount > 0 ? `未读 ${session.unreadCount}` : "已读"}</span>
                <span>{session.draftBuffer.trim() ? "已聚合消息" : "等待新消息"}</span>
              </div>
            </button>
          ))}
        </div>
      )}
    </aside>
  );
}
