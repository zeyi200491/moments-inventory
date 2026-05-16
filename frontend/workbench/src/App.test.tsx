import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import App from "./App";

const apiMocks = vi.hoisted(() => ({
  generateDraft: vi.fn(),
  listKnowledgeLibraries: vi.fn(),
  listDraftHistory: vi.fn(),
  submitDraftFeedback: vi.fn(),
  listChatSyncSessions: vi.fn(),
  getChatSyncSession: vi.fn(),
  setCurrentChatSyncSession: vi.fn(),
  refreshChatSyncSession: vi.fn(),
  uploadKnowledgeLibrary: vi.fn(),
}));

vi.mock("./api", () => apiMocks);

function buildChatSessionSummary(overrides: Partial<Record<string, unknown>> = {}) {
  return {
    sessionId: "s-1",
    username: "wxid_zhangsan",
    displayName: "张三",
    sessionType: "private" as const,
    lastTimestamp: 1710000000,
    unreadCount: 2,
    draftBuffer: "",
    autoGenerate: false,
    isCurrent: false,
    lastMessageTimestamp: 1710000000,
    ...overrides,
  };
}

function buildChatSessionDetail(overrides: Partial<Record<string, unknown>> = {}) {
  return {
    sessionId: "s-1",
    username: "wxid_zhangsan",
    displayName: "张三",
    sessionType: "private" as const,
    lastTimestamp: 1710000000,
    unreadCount: 2,
    draftBuffer: "你好，在吗？",
    autoGenerate: false,
    isCurrent: true,
    lastMessageTimestamp: 1710000001,
    ...overrides,
  };
}

describe("App", () => {
  beforeEach(() => {
    apiMocks.generateDraft.mockReset();
    apiMocks.listKnowledgeLibraries.mockReset();
    apiMocks.listDraftHistory.mockReset();
    apiMocks.submitDraftFeedback.mockReset();
    apiMocks.listChatSyncSessions.mockReset();
    apiMocks.getChatSyncSession.mockReset();
    apiMocks.setCurrentChatSyncSession.mockReset();
    apiMocks.refreshChatSyncSession.mockReset();
    apiMocks.uploadKnowledgeLibrary.mockReset();

    apiMocks.generateDraft.mockResolvedValue({
      reply_text: "好的，我先帮您确认一下。",
      risk_level: "L1",
      reason: "普通问题",
      customer_stage: "开场",
      intent: "其他",
      should_handoff: false,
      reply_type: "简短回答",
      required_data: [],
      used_knowledge: [],
    });
    apiMocks.listKnowledgeLibraries.mockResolvedValue([]);
    apiMocks.listDraftHistory.mockResolvedValue([]);
    apiMocks.submitDraftFeedback.mockResolvedValue({ ok: true });
    apiMocks.listChatSyncSessions.mockResolvedValue([]);
    apiMocks.uploadKnowledgeLibrary.mockResolvedValue({
      library_type: "product_inventory_excel",
      source_name: "library:product_inventory_excel",
      original_filename: "inventory.xlsx",
      imported_count: 120,
      skipped_count: 0,
      status: "active",
      replaced: true,
      message: "商品库存库已更新",
      uploaded_at: "2026-05-15T20:00:00+08:00",
    });
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("运行页优先展示当前会话工作台和回复审阅区", async () => {
    render(<App />);

    expect(await screen.findByText("当前会话工作台")).toBeTruthy();
    expect(screen.getByText("回复审阅")).toBeTruthy();
    expect(screen.getByText("会话导航")).toBeTruthy();
  });

  it("切换到设置页后显示知识库管理", async () => {
    render(<App />);

    fireEvent.click(screen.getByRole("tab", { name: "设置页面" }));

    expect(await screen.findByText("知识库管理")).toBeTruthy();
    expect(screen.getByRole("button", { name: "知识库" })).toHaveAttribute("aria-pressed", "true");
  });

  it("选择私聊会话后会加载客户消息", async () => {
    apiMocks.listChatSyncSessions.mockResolvedValue([buildChatSessionSummary()]);
    apiMocks.getChatSyncSession.mockResolvedValue(buildChatSessionDetail());

    render(<App />);

    fireEvent.click(await screen.findByRole("button", { name: "张三" }));

    await waitFor(() => {
      expect(apiMocks.getChatSyncSession).toHaveBeenCalledWith("s-1");
    });
    expect(await screen.findByDisplayValue("你好，在吗？")).toBeTruthy();
  });

  it("生成请求不会提交 style_messages", async () => {
    apiMocks.listChatSyncSessions.mockResolvedValue([buildChatSessionSummary()]);
    apiMocks.getChatSyncSession.mockResolvedValue(buildChatSessionDetail());

    render(<App />);

    fireEvent.click(await screen.findByRole("button", { name: "张三" }));
    await screen.findByDisplayValue("你好，在吗？");

    fireEvent.click(screen.getByRole("button", { name: "生成候选回复" }));

    await waitFor(() => {
      expect(apiMocks.generateDraft).toHaveBeenCalledWith({
        conversation_id: "s-1",
        customer_message: "你好，在吗？",
      });
    });
  });

  it("自动生成会在新消息到来后延迟触发", async () => {
    apiMocks.listChatSyncSessions.mockResolvedValue([
      buildChatSessionSummary({ autoGenerate: true, isCurrent: true }),
    ]);
    apiMocks.getChatSyncSession.mockResolvedValue(
      buildChatSessionDetail({ autoGenerate: true, isCurrent: true }),
    );

    render(<App />);

    fireEvent.click(await screen.findByRole("button", { name: "张三" }));
    await screen.findByDisplayValue("你好，在吗？");

    expect(apiMocks.generateDraft).not.toHaveBeenCalled();
    await act(async () => {
      await new Promise((resolve) => window.setTimeout(resolve, 1300));
    });

    await waitFor(() => {
      expect(apiMocks.generateDraft).toHaveBeenCalledTimes(1);
    });
  }, 10000);

  it("知识库上传弹窗会按业务库类型提交文件", async () => {
    apiMocks.listKnowledgeLibraries
      .mockResolvedValueOnce([])
      .mockResolvedValueOnce([
        {
          library_type: "product_inventory_excel",
          source_name: "library:product_inventory_excel",
          original_filename: "inventory.xlsx",
          imported_count: 120,
          skipped_count: 0,
          status: "active",
          uploaded_at: "2026-05-15T20:00:00+08:00",
        },
      ]);

    render(<App />);

    fireEvent.click(screen.getByRole("tab", { name: "设置页面" }));
    fireEvent.click(await screen.findByRole("button", { name: "上传知识库" }));

    fireEvent.change(screen.getByLabelText("业务库类型"), {
      target: { value: "product_inventory_excel" },
    });

    const file = new File(["sku"], "inventory.xlsx", {
      type: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    });
    fireEvent.change(screen.getByLabelText("选择文件"), {
      target: { files: [file] },
    });

    await waitFor(() => {
      expect(apiMocks.uploadKnowledgeLibrary).toHaveBeenCalledWith("product_inventory_excel", file);
    });
    expect(await screen.findByText("inventory.xlsx")).toBeInTheDocument();
  });

  it("shows backend detail when knowledge upload fails", async () => {
    apiMocks.uploadKnowledgeLibrary.mockRejectedValue(
      new Error("风格样本库文件必须是 UTF-8 编码的 Markdown"),
    );

    render(<App />);

    fireEvent.click(screen.getByRole("tab", { name: "设置页面" }));
    fireEvent.click(await screen.findByRole("button", { name: "上传知识库" }));
    fireEvent.change(screen.getByLabelText("业务库类型"), {
      target: { value: "style_sample_md" },
    });

    const file = new File(["style"], "style.md", { type: "text/markdown" });
    fireEvent.change(screen.getByLabelText("选择文件"), { target: { files: [file] } });

    expect(
      (await screen.findAllByText("风格样本库文件必须是 UTF-8 编码的 Markdown")).length,
    ).toBeGreaterThan(0);
  });

  it("历史记录支持提交反馈到后端", async () => {
    apiMocks.listDraftHistory.mockResolvedValue([
      {
        draft_id: "draft-001",
        conversation_id: "conv-001",
        customer_message: "客户问这台机器多久发货",
        reply_text: "现货通常 24 小时内发出，我先给您确认仓库。",
        risk_level: "L2",
        reason: "涉及发货时效说明",
        workflow: {
          customer_stage: "发货确认",
          intent: "发货咨询",
          should_handoff: false,
          reply_type: "简短回答",
          required_data: ["发货信息"],
        },
        used_chunk_ids: ["shipping-001"],
        final_status: "generated",
        operator_note: "",
        created_at: "2026-05-07T12:00:00+08:00",
      },
    ]);

    render(<App />);

    fireEvent.click(screen.getByRole("tab", { name: "设置页面" }));
    fireEvent.click(await screen.findByRole("button", { name: "标记为采用" }));

    await waitFor(() => {
      expect(apiMocks.submitDraftFeedback).toHaveBeenCalledWith({
        draft_id: "draft-001",
        final_status: "adopted",
        operator_note: "",
      });
    });
  });
});
