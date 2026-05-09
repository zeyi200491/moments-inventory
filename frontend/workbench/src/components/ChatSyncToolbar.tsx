type ChatSyncToolbarProps = {
  currentSessionName: string;
  syncStatus: string;
  autoGenerate: boolean;
  onAutoGenerateChange: () => void;
  onRefresh: () => void;
};

export function ChatSyncToolbar({
  currentSessionName,
  syncStatus,
  autoGenerate,
  onAutoGenerateChange,
  onRefresh,
}: ChatSyncToolbarProps) {
  return (
    <section className="chat-sync-toolbar panel panel-soft">
      <div className="chat-sync-toolbar-copy">
        <span className="eyebrow">Chat Sync / 工作台同步</span>
        <h2>{currentSessionName}</h2>
        <p className="muted">先把最新客户消息拉到中间工作台。当前状态：{syncStatus}</p>
      </div>

      <div className="chat-sync-toolbar-actions">
        <button
          type="button"
          className={`toggle-switch${autoGenerate ? " toggle-switch-on" : ""}`}
          role="switch"
          aria-checked={autoGenerate}
          aria-label="自动生成"
          onClick={onAutoGenerateChange}
        >
          <span className="toggle-switch-track">
            <span className="toggle-switch-thumb" />
          </span>
          <span>{autoGenerate ? "自动生成已开" : "自动生成已关"}</span>
        </button>

        <button type="button" className="secondary-button" onClick={onRefresh}>
          手动刷新消息
        </button>
      </div>
    </section>
  );
}
