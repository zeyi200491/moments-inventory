import type { ReactNode } from "react";

type SettingsShellProps = {
  nav: ReactNode;
  content: ReactNode;
};

export function SettingsShell({ nav, content }: SettingsShellProps) {
  return (
    <div className="settings-shell">
      <aside className="settings-sidebar">{nav}</aside>
      <section className="settings-content">{content}</section>
    </div>
  );
}
