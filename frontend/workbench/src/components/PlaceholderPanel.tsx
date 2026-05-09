type PlaceholderPanelProps = {
  title: string;
  description: string;
  note: string;
};

export function PlaceholderPanel({ title, description, note }: PlaceholderPanelProps) {
  return (
    <section className="panel panel-soft placeholder-panel">
      <div className="panel-heading">
        <span className="eyebrow">Service Placeholder / 预留区域</span>
        <h2>{title}</h2>
      </div>
      <div className="placeholder-card">
        <strong>{description}</strong>
        <p>{note}</p>
      </div>
    </section>
  );
}
