import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { ConversationPanel } from "./ConversationPanel";

describe("ConversationPanel", () => {
  it("把客户消息区渲染为主工作台文案", () => {
    render(
      <ConversationPanel
        customerMessage="客户在吗"
        loading={false}
        disabledReason={null}
        onCustomerMessageChange={vi.fn()}
        onGenerate={vi.fn()}
      />,
    );

    expect(screen.getByText("当前会话工作台")).toBeTruthy();
    expect(screen.getByPlaceholderText("在这里整理客户刚发来的消息、需求和追问")).toBeTruthy();
  });

  it("客户消息为空时显示禁用原因", () => {
    render(
      <ConversationPanel
        customerMessage=""
        loading={false}
        disabledReason="先输入客户消息后，才能生成候选回复。"
        onCustomerMessageChange={vi.fn()}
        onGenerate={vi.fn()}
      />,
    );

    expect(screen.getByText("先输入客户消息后，才能生成候选回复。")).toBeTruthy();
    expect(screen.queryByText("风格样本")).toBeNull();
  });

  it("生成中时显示等待提示", () => {
    render(
      <ConversationPanel
        customerMessage="客户在吗"
        loading={true}
        disabledReason="正在生成候选回复，请稍等片刻。"
        onCustomerMessageChange={vi.fn()}
        onGenerate={vi.fn()}
      />,
    );

    expect(screen.getByText("正在生成候选回复，请稍等片刻。")).toBeTruthy();
  });
});
