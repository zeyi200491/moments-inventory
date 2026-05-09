import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { ReplyDraftPanel } from "./ReplyDraftPanel";

describe("ReplyDraftPanel", () => {
  it("空状态下展示审阅面板说明", () => {
    render(
      <ReplyDraftPanel
        draft={null}
        errorMessage={null}
        copyFeedback={null}
        copySucceeded={false}
        onCopy={vi.fn()}
        onRetry={vi.fn()}
      />,
    );

    expect(screen.getByText("回复审阅")).toBeTruthy();
    expect(screen.getByText("这里会展示候选回复、流程判断、风险等级和命中依据。")).toBeTruthy();
  });

  it("展示工作流决策信息和知识层级", () => {
    render(
      <ReplyDraftPanel
        draft={{
          reply_text: "可以的，我先帮您核对一下。",
          risk_level: "L2",
          reason: "发货咨询",
          customer_stage: "推单",
          intent: "商品推荐",
          should_handoff: true,
          reply_type: "商品推荐",
          required_data: ["库存", "验机视频"],
          used_knowledge: [
            {
              chunk_id: "chunk-001",
              source_name: "after-sale.md",
              category: "售后",
              knowledge_tier: "after_sale_doc",
              text: "售后问题需先提供订单号和视频。",
              tags: ["售后", "凭证"],
            },
          ],
        }}
        errorMessage={null}
        copyFeedback={null}
        copySucceeded={false}
        onCopy={vi.fn()}
        onRetry={vi.fn()}
      />,
    );

    expect(screen.getByText("推单")).toBeTruthy();
    expect(screen.getAllByText("商品推荐")).toHaveLength(2);
    expect(screen.getByText("需人工接管")).toBeTruthy();
    expect(screen.getByText("正式售后文件库 / after_sale_doc")).toBeTruthy();
    expect(screen.getByText("库存")).toBeTruthy();
    expect(screen.getByText("验机视频")).toBeTruthy();
  });

  it("空回复时展示预警并允许重试", () => {
    const onRetry = vi.fn();

    render(
      <ReplyDraftPanel
        draft={{
          reply_text: "",
          risk_level: "L2",
          reason: "普通问题",
          customer_stage: "推单",
          intent: "其他",
          should_handoff: false,
          reply_type: "简短回答",
          required_data: [],
          used_knowledge: [],
        }}
        errorMessage={null}
        copyFeedback={null}
        copySucceeded={false}
        onCopy={vi.fn()}
        onRetry={onRetry}
      />,
    );

    expect(screen.getByText("模型返回了空回复")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "重试生成" }));
    expect(onRetry).toHaveBeenCalledTimes(1);
  });

  it("复制成功后切换按钮文案", () => {
    render(
      <ReplyDraftPanel
        draft={{
          reply_text: "可以的，我先帮您确认一下。",
          risk_level: "L1",
          reason: "普通问题",
          customer_stage: "开场",
          intent: "其他",
          should_handoff: false,
          reply_type: "简短回答",
          required_data: [],
          used_knowledge: [],
        }}
        errorMessage={null}
        copyFeedback="已复制到剪贴板"
        copySucceeded={true}
        onCopy={vi.fn()}
        onRetry={vi.fn()}
      />,
    );

    expect(screen.getByRole("button", { name: "已复制" })).toBeTruthy();
  });
});
