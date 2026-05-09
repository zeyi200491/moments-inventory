import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import App from "./App";

const apiMocks = vi.hoisted(() => ({
  generateDraft: vi.fn(),
  importKnowledge: vi.fn(),
  listKnowledgeSources: vi.fn(),
  listDraftHistory: vi.fn(),
  submitDraftFeedback: vi.fn(),
  listChatSyncSessions: vi.fn(),
  getChatSyncSession: vi.fn(),
  setCurrentChatSyncSession: vi.fn(),
  refreshChatSyncSession: vi.fn(),
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
    apiMocks.importKnowledge.mockReset();
    apiMocks.listKnowledgeSources.mockReset();
    apiMocks.listDraftHistory.mockReset();
    apiMocks.submitDraftFeedback.mockReset();
    apiMocks.listChatSyncSessions.mockReset();
    apiMocks.getChatSyncSession.mockReset();
    apiMocks.setCurrentChatSyncSession.mockReset();
    apiMocks.refreshChatSyncSession.mockReset();

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
    apiMocks.listKnowledgeSources.mockResolvedValue([]);
    apiMocks.listDraftHistory.mockResolvedValue([]);
    apiMocks.submitDraftFeedback.mockResolvedValue({ ok: true });
    apiMocks.listChatSyncSessions.mockResolvedValue([]);
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

  it("切换到设置页后显示知识文件管理", async () => {
    render(<App />);

    fireEvent.click(screen.getByRole("tab", { name: "设置页面" }));

    expect(await screen.findByText("知识文件管理")).toBeTruthy();
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

  it("运行页不再显示风格样本输入区", async () => {
    render(<App />);

    expect(await screen.findByText("当前会话工作台")).toBeTruthy();
    expect(screen.queryByText("风格样本")).toBeNull();
  });

  it("生成请求不再提交 style_messages", async () => {
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

  it("关闭上传弹窗时会重置表单内容", async () => {
    render(<App />);

    fireEvent.click(screen.getByRole("tab", { name: "设置页面" }));
    fireEvent.click(await screen.findByRole("button", { name: "+ 添加" }));

    const categoryInput = await screen.findByDisplayValue("产品");
    const tagsInput = screen.getByLabelText("标签");
    const tierSelect = screen.getByLabelText("知识层级");

    fireEvent.change(categoryInput, { target: { value: "回复风格" } });
    fireEvent.change(tagsInput, { target: { value: "活人感,聊天" } });
    fireEvent.change(tierSelect, { target: { value: "style_sample" } });

    fireEvent.click(screen.getByRole("button", { name: "关闭上传面板" }));
    fireEvent.click(screen.getByRole("button", { name: "+ 添加" }));

    expect(await screen.findByDisplayValue("产品")).toBeTruthy();
    expect(screen.getByLabelText("标签")).toHaveValue("");
    expect(screen.getByLabelText("知识层级")).toHaveValue("product_material");
  });

  it("设置页会加载后端审计历史并展示记录", async () => {
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

    expect(await screen.findByText("客户问这台机器多久发货")).toBeTruthy();
    expect(screen.getByText("现货通常 24 小时内发出，我先给您确认仓库。")).toBeTruthy();
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

  it("发货信息支持结构化录入并提交到后端", async () => {
    apiMocks.importKnowledge.mockResolvedValue({
      source_name: "supplier-laowang-shenzhen",
      category: "供应链发货",
      knowledge_tier: "shipping_info",
      chunk_count: 1,
      tags: ["老王", "深圳华强北", "现货"],
    });

    render(<App />);

    fireEvent.click(screen.getByRole("tab", { name: "设置页面" }));
    fireEvent.click(await screen.findByRole("button", { name: "+ 添加" }));

    fireEvent.change(screen.getByLabelText("知识层级"), {
      target: { value: "shipping_info" },
    });
    fireEvent.change(screen.getByLabelText("条目名称"), {
      target: { value: "supplier-laowang-shenzhen" },
    });
    fireEvent.change(screen.getByLabelText("供应商"), {
      target: { value: "老王" },
    });
    fireEvent.change(screen.getByLabelText("仓库位置"), {
      target: { value: "深圳华强北" },
    });
    fireEvent.change(screen.getByLabelText("发货时效"), {
      target: { value: "24 小时内发出" },
    });
    fireEvent.change(screen.getByLabelText("配送范围"), {
      target: { value: "全国可发" },
    });
    fireEvent.change(screen.getByLabelText("异常说明"), {
      target: { value: "周日只处理加急单" },
    });
    fireEvent.change(screen.getByLabelText("联系时间"), {
      target: { value: "09:00-21:00" },
    });
    fireEvent.change(screen.getByLabelText("补充备注"), {
      target: { value: "缺货时先确认补货周期" },
    });
    fireEvent.change(screen.getByLabelText("标签"), {
      target: { value: "现货,加急" },
    });

    fireEvent.click(screen.getByRole("button", { name: "保存结构化条目" }));

    await waitFor(() => {
      expect(apiMocks.importKnowledge).toHaveBeenCalledWith({
        source_name: "supplier-laowang-shenzhen",
        category: "供应链发货",
        knowledge_tier: "shipping_info",
        content: "",
        structured_fields: {
          supplier_name: "老王",
          warehouse_location: "深圳华强北",
          dispatch_sla: "24 小时内发出",
          delivery_scope: "全国可发",
          exceptions: "周日只处理加急单",
          contact_window: "09:00-21:00",
          notes: "缺货时先确认补货周期",
        },
        tags: ["现货", "加急"],
      });
    });
  });
});
