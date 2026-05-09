type ConversationPanelProps = {
  customerMessage: string;
  loading: boolean;
  disabledReason: string | null;
  onCustomerMessageChange: (value: string) => void;
  onGenerate: () => void;
};

const RISK_GUIDE = [
  "L1 辅助模式：生成人工候选回复，由你确认后发送。",
  "L2 低风险白名单：FAQ、产品介绍、营业时间、物流规则。",
  "L4 禁止自动：退款、投诉、价格特批、合同、情绪激烈。",
];

export function ConversationPanel({
  customerMessage,
  loading,
  disabledReason,
  onCustomerMessageChange,
  onGenerate,
}: ConversationPanelProps) {
  return (
    <section className="panel panel-primary panel-stage">
      <div className="panel-heading panel-heading-stage">
        <span className="eyebrow">Current Session / 核心输入</span>
        <h2>当前会话工作台</h2>
        <p className="muted">先整理客户刚发来的消息，再生成一版可审阅的候选回复。</p>
      </div>
      <label className="field field-stage">
        <span>客户消息</span>
        <textarea
          className="text-area text-area-large text-area-stage"
          placeholder="在这里整理客户刚发来的消息、需求和追问"
          value={customerMessage}
          onChange={(event) => onCustomerMessageChange(event.target.value)}
        />
      </label>
      <div className="guide-row">
        {RISK_GUIDE.map((item) => (
          <div key={item} className="guide-pill">
            {item}
          </div>
        ))}
      </div>
      <button
        className="action-button"
        onClick={onGenerate}
        disabled={loading || !customerMessage.trim()}
      >
        {loading ? "生成中..." : "生成候选回复"}
      </button>
      {disabledReason ? (
        <p className="helper-text" role="status">
          {disabledReason}
        </p>
      ) : null}
    </section>
  );
}
