import type { JSX } from "react";
import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { ErrorBoundary } from "./ErrorBoundary";

function ThrowingComponent(): JSX.Element {
  throw new Error("boom");
}

describe("ErrorBoundary", () => {
  it("组件渲染报错时显示兜底界面", () => {
    const errorSpy = vi.spyOn(console, "error").mockImplementation(() => {});

    render(
      <ErrorBoundary>
        <ThrowingComponent />
      </ErrorBoundary>,
    );

    expect(screen.getByText("页面加载失败")).toBeTruthy();
    expect(screen.getByRole("alert")).toHaveTextContent("组件渲染时发生错误，请刷新页面后重试。");

    errorSpy.mockRestore();
  });
});
