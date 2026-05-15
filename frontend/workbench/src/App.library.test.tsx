import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

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

describe("App knowledge libraries", () => {
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
      reply_text: "ok",
      risk_level: "L1",
      reason: "ok",
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
  });

  it("loads business library cards from the library status endpoint", async () => {
    apiMocks.listKnowledgeLibraries.mockResolvedValue([
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

    expect(await screen.findByText("商品库存库")).toBeInTheDocument();
    expect(screen.getByText("inventory.xlsx")).toBeInTheDocument();
  });
});
