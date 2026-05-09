type SettingsSection = "tasks" | "knowledge" | "reports" | "profile";

type SettingsNavProps = {
  activeSection: SettingsSection;
  onChange: (section: SettingsSection) => void;
};

const PRIMARY_ITEMS: Array<{ key: Exclude<SettingsSection, "profile">; label: string }> = [
  { key: "tasks", label: "任务设置" },
  { key: "knowledge", label: "知识库" },
  { key: "reports", label: "运营报告" },
];

export function SettingsNav({ activeSection, onChange }: SettingsNavProps) {
  return (
    <div className="settings-nav">
      <div className="panel-heading panel-heading-compact">
        <span className="eyebrow">Workbench / 设置导航</span>
        <h2>设置工作台</h2>
        <p className="muted">保持和运行页一致的深色工作台结构，按模块切换配置内容。</p>
      </div>

      <div className="settings-nav-list">
        {PRIMARY_ITEMS.map((item) => (
          <button
            key={item.key}
            type="button"
            className="settings-nav-item"
            aria-pressed={activeSection === item.key}
            onClick={() => onChange(item.key)}
          >
            <span className="settings-nav-icon" aria-hidden="true">
              ▣
            </span>
            {item.label}
          </button>
        ))}
      </div>

      <button
        type="button"
        className="settings-nav-item settings-nav-item-profile"
        aria-pressed={activeSection === "profile"}
        onClick={() => onChange("profile")}
      >
        <span className="settings-nav-icon" aria-hidden="true">
          ◉
        </span>
        我的
      </button>
    </div>
  );
}
