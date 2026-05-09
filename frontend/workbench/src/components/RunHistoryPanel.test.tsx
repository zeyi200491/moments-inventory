import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { RunHistoryPanel } from "./RunHistoryPanel";

function buildHistoryEntry() {
  return {
    draft_id: "draft-001",
    conversation_id: "conv-1",
    customer_message: "客户想问退款多久到账，还想确认售后流程。",
    reply_text: "您好，这边先帮您确认一下，退款一般 1 到 3 个工作日到账。",
    risk_level: "L2" as const,
    reason: "涉及退款时效说明",
    workflow: {
      customer_stage: "售后",
      intent: "售后咨询",
      should_handoff: true,
      reply_type: "简短回答",
      required_data: ["订单号"],
    },
    used_chunk_ids: ["faq-001"],
    final_status: "generated",
    operator_note: "",
    created_at: "2026-05-03T09:30:00+08:00",
  };
}

describe("RunHistoryPanel", () => {
  it("没有历史时显示空状态", () => {
    render(<RunHistoryPanel history={[]} onReuse={vi.fn()} onFeedback={vi.fn()} />);

    expect(screen.getByText("还没有历史记录。每次生成成功后，这里会自动保留最近几次会话。")).toBeTruthy();
  });

  it("可以展开完整内容、复用记录并提交反馈", () => {
    const onReuse = vi.fn();
    const onFeedback = vi.fn();
    const entry = buildHistoryEntry();

    render(<RunHistoryPanel history={[entry]} onReuse={onReuse} onFeedback={onFeedback} />);

    fireEvent.click(screen.getByRole("button", { name: "展开完整内容" }));
    expect(screen.getByText(entry.customer_message)).toBeTruthy();
    expect(screen.getByText(entry.reply_text)).toBeTruthy();

    fireEvent.click(screen.getByRole("button", { name: "重新载入 05/03 09:30 的历史记录" }));
    expect(onReuse).toHaveBeenCalledWith(entry);

    fireEvent.click(screen.getByRole("button", { name: "标记为采用" }));
    expect(onFeedback).toHaveBeenCalledWith(entry, "adopted");
  });
});
