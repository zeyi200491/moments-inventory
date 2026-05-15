import { useEffect, useRef, useState } from "react";
import type { ChangeEvent, DragEvent } from "react";

import {
  generateDraft,
  getChatSyncSession,
  listChatSyncSessions,
  listDraftHistory,
  listKnowledgeLibraries,
  refreshChatSyncSession,
  setCurrentChatSyncSession,
  submitDraftFeedback,
  uploadKnowledgeLibrary,
} from "./api";
import { ChatSessionList } from "./components/ChatSessionList";
import { ChatSyncToolbar } from "./components/ChatSyncToolbar";
import { ConversationPanel } from "./components/ConversationPanel";
import { KnowledgeLibraryView } from "./components/KnowledgeLibraryView";
import { KnowledgeUploadModal } from "./components/KnowledgeUploadModal";
import { PlaceholderPanel } from "./components/PlaceholderPanel";
import { RecentRunCard } from "./components/RecentRunCard";
import { ReplyDraftPanel } from "./components/ReplyDraftPanel";
import { RunHistoryPanel } from "./components/RunHistoryPanel";
import { SettingsNav } from "./components/SettingsNav";
import { SettingsShell } from "./components/SettingsShell";
import type {
  ChatSyncSession,
  DraftHistoryItem,
  DraftResponse,
  KnowledgeLibraryState,
  KnowledgeLibraryType,
  KnowledgeLibraryUploadResponse,
} from "./types";

const MAX_IMPORT_FILE_BYTES = 10 * 1024 * 1024;
const CHAT_SYNC_POLL_MS = 2000;
const AUTO_GENERATE_DEBOUNCE_MS = 1200;
const DEFAULT_LIBRARY_TYPE: KnowledgeLibraryType = "master_rule_bundle";

const LIBRARY_TYPE_LABELS: Record<KnowledgeLibraryType, string> = {
  master_rule_bundle: "主规则文件",
  product_inventory_excel: "商品库存库",
  product_material_excel: "商品素材库",
  shipping_info_excel: "供应链发货信息库",
  style_sample_md: "风格样本库",
};

type WorkbenchPage = "runtime" | "settings";
type SettingsSection = "tasks" | "knowledge" | "reports" | "profile";

function buildConversationId() {
  return `manual-${Date.now()}`;
}

function buildDraftFromHistory(entry: DraftHistoryItem): DraftResponse {
  return {
    reply_text: entry.reply_text,
    risk_level: entry.risk_level,
    reason: entry.reason,
    customer_stage: entry.workflow.customer_stage ?? "未知",
    intent: entry.workflow.intent ?? "未知",
    should_handoff: entry.workflow.should_handoff ?? false,
    reply_type: entry.workflow.reply_type ?? "历史记录",
    required_data: entry.workflow.required_data ?? [],
    used_knowledge: [],
  };
}

function mergeCustomerMessage(currentText: string, incomingText: string): string {
  const trimmedIncoming = incomingText.trim();
  if (!trimmedIncoming) {
    return currentText;
  }
  if (!currentText.trim()) {
    return trimmedIncoming;
  }
  if (currentText.includes(trimmedIncoming)) {
    return currentText;
  }
  return `${currentText}\n${trimmedIncoming}`;
}

function extractIncomingChatDelta(previousBuffer: string, nextBuffer: string): string {
  const normalizedPrevious = previousBuffer.trim();
  const normalizedNext = nextBuffer.trim();

  if (!normalizedNext) {
    return "";
  }
  if (!normalizedPrevious) {
    return normalizedNext;
  }
  if (normalizedPrevious === normalizedNext) {
    return "";
  }
  if (normalizedNext.startsWith(normalizedPrevious)) {
    return normalizedNext.slice(normalizedPrevious.length).replace(/^\s+/, "");
  }
  return normalizedNext;
}

export default function App() {
  const [activePage, setActivePage] = useState<WorkbenchPage>("runtime");
  const [activeSettingsSection, setActiveSettingsSection] = useState<SettingsSection>("knowledge");
  const [uploadModalOpen, setUploadModalOpen] = useState(false);

  const [chatSessions, setChatSessions] = useState<ChatSyncSession[]>([]);
  const [currentChatSession, setCurrentChatSession] = useState<ChatSyncSession | null>(null);
  const currentChatSessionIdRef = useRef<string | null>(null);
  const appliedDraftBufferBySessionRef = useRef<Record<string, string>>({});
  const appliedMessageTimestampBySessionRef = useRef<Record<string, number>>({});
  const autoGenerateTimerRef = useRef<number | null>(null);
  const loadingRef = useRef(false);

  const [customerMessage, setCustomerMessage] = useState("");
  const [draft, setDraft] = useState<DraftResponse | null>(null);
  const [history, setHistory] = useState<DraftHistoryItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [copyFeedback, setCopyFeedback] = useState<string | null>(null);
  const [copySucceeded, setCopySucceeded] = useState(false);
  const [historyMessage, setHistoryMessage] = useState<string | null>(null);

  const [selectedLibraryType, setSelectedLibraryType] =
    useState<KnowledgeLibraryType>(DEFAULT_LIBRARY_TYPE);
  const [importLoading, setImportLoading] = useState(false);
  const [importMessage, setImportMessage] = useState<string | null>(null);
  const [importError, setImportError] = useState<string | null>(null);
  const [lastLibraryUpload, setLastLibraryUpload] = useState<KnowledgeLibraryUploadResponse | null>(
    null,
  );
  const [libraries, setLibraries] = useState<KnowledgeLibraryState[]>([]);

  useEffect(() => {
    loadingRef.current = loading;
  }, [loading]);

  useEffect(() => {
    void refreshKnowledgeLibraries();
    void refreshDraftHistory();
    void refreshChatSessions();

    const timer = window.setInterval(() => {
      void refreshChatSessions();
      if (currentChatSessionIdRef.current) {
        void loadChatSessionDetail(currentChatSessionIdRef.current, { mergeIntoCustomerMessage: true });
      }
    }, CHAT_SYNC_POLL_MS);

    return () => window.clearInterval(timer);
  }, []);

  useEffect(() => {
    if (!copyFeedback) {
      return;
    }
    const timer = window.setTimeout(() => {
      setCopyFeedback(null);
      setCopySucceeded(false);
    }, 3000);
    return () => window.clearTimeout(timer);
  }, [copyFeedback]);

  useEffect(() => {
    if (!historyMessage) {
      return;
    }
    const timer = window.setTimeout(() => {
      setHistoryMessage(null);
    }, 3000);
    return () => window.clearTimeout(timer);
  }, [historyMessage]);

  useEffect(() => {
    if (!importMessage) {
      return;
    }
    const timer = window.setTimeout(() => {
      setImportMessage(null);
    }, 3000);
    return () => window.clearTimeout(timer);
  }, [importMessage]);

  useEffect(() => {
    if (autoGenerateTimerRef.current !== null) {
      window.clearTimeout(autoGenerateTimerRef.current);
      autoGenerateTimerRef.current = null;
    }

    if (!currentChatSession?.autoGenerate) {
      return;
    }
    if (!customerMessage.trim()) {
      return;
    }

    autoGenerateTimerRef.current = window.setTimeout(() => {
      autoGenerateTimerRef.current = null;
      void handleGenerate();
    }, AUTO_GENERATE_DEBOUNCE_MS);

    return () => {
      if (autoGenerateTimerRef.current !== null) {
        window.clearTimeout(autoGenerateTimerRef.current);
        autoGenerateTimerRef.current = null;
      }
    };
  }, [
    currentChatSession?.sessionId,
    currentChatSession?.autoGenerate,
    currentChatSession?.lastMessageTimestamp,
    customerMessage,
  ]);

  async function refreshKnowledgeLibraries() {
    try {
      const nextLibraries = await listKnowledgeLibraries();
      setLibraries(nextLibraries);
    } catch (error) {
      setImportError(error instanceof Error ? error.message : "读取知识库状态失败");
    }
  }

  async function refreshDraftHistory() {
    try {
      const items = await listDraftHistory();
      setHistory(items);
    } catch {
      setHistory([]);
    }
  }

  async function refreshChatSessions() {
    try {
      const sessions = await listChatSyncSessions();
      setChatSessions(sessions);
    } catch {
      setChatSessions([]);
    }
  }

  function resetImportForm() {
    setSelectedLibraryType(DEFAULT_LIBRARY_TYPE);
    setImportError(null);
  }

  function closeUploadModal() {
    setUploadModalOpen(false);
    resetImportForm();
  }

  function openUploadModal(libraryType: KnowledgeLibraryType = DEFAULT_LIBRARY_TYPE) {
    setSelectedLibraryType(libraryType);
    setImportError(null);
    setUploadModalOpen(true);
  }

  async function loadChatSessionDetail(
    sessionId: string,
    options: { mergeIntoCustomerMessage?: boolean } = {},
  ) {
    const detail = await getChatSyncSession(sessionId);
    const previousBuffer = appliedDraftBufferBySessionRef.current[detail.sessionId] ?? "";
    const previousTimestamp = appliedMessageTimestampBySessionRef.current[detail.sessionId] ?? 0;

    currentChatSessionIdRef.current = detail.sessionId;
    setCurrentChatSession(detail);
    setChatSessions((current) =>
      current.map((session) =>
        session.sessionId === detail.sessionId
          ? { ...session, ...detail, isCurrent: true }
          : { ...session, isCurrent: false },
      ),
    );

    if (options.mergeIntoCustomerMessage) {
      if (detail.lastMessageTimestamp > previousTimestamp) {
        const incomingDelta = extractIncomingChatDelta(previousBuffer, detail.draftBuffer);
        if (incomingDelta) {
          setCustomerMessage((current) => mergeCustomerMessage(current, incomingDelta));
        }
      }
    } else {
      setCustomerMessage(detail.draftBuffer.trim());
    }

    appliedDraftBufferBySessionRef.current[detail.sessionId] = detail.draftBuffer.trim();
    appliedMessageTimestampBySessionRef.current[detail.sessionId] = detail.lastMessageTimestamp;
    setDraft(null);
    setErrorMessage(null);
  }

  async function handleSelectChatSession(sessionId: string) {
    currentChatSessionIdRef.current = sessionId;
    setChatSessions((current) =>
      current.map((session) => ({
        ...session,
        isCurrent: session.sessionId === sessionId,
      })),
    );
    setCurrentChatSession((current) =>
      current?.sessionId === sessionId ? { ...current, isCurrent: true } : current,
    );
    await loadChatSessionDetail(sessionId);
  }

  async function handleToggleAutoGenerate() {
    if (!currentChatSession) {
      return;
    }
    const next = await setCurrentChatSyncSession({
      sessionId: currentChatSession.sessionId,
      autoGenerate: !currentChatSession.autoGenerate,
    });
    setCurrentChatSession(next);
    currentChatSessionIdRef.current = next.sessionId;
    setChatSessions((current) =>
      current.map((session) =>
        session.sessionId === next.sessionId
          ? { ...session, autoGenerate: next.autoGenerate, isCurrent: true }
          : { ...session, isCurrent: false },
      ),
    );
  }

  async function handleRefreshCurrentChatSession() {
    if (!currentChatSession) {
      return;
    }
    const next = await refreshChatSyncSession(currentChatSession.sessionId);
    const previousBuffer = appliedDraftBufferBySessionRef.current[next.sessionId] ?? "";
    const previousTimestamp = appliedMessageTimestampBySessionRef.current[next.sessionId] ?? 0;

    setCurrentChatSession(next);
    setChatSessions((current) =>
      current.map((session) =>
        session.sessionId === next.sessionId
          ? { ...session, ...next, isCurrent: true }
          : session,
      ),
    );

    if (next.lastMessageTimestamp > previousTimestamp) {
      const incomingDelta = extractIncomingChatDelta(previousBuffer, next.draftBuffer);
      if (incomingDelta) {
        setCustomerMessage((current) => mergeCustomerMessage(current, incomingDelta));
      }
    }

    appliedDraftBufferBySessionRef.current[next.sessionId] = next.draftBuffer.trim();
    appliedMessageTimestampBySessionRef.current[next.sessionId] = next.lastMessageTimestamp;
  }

  async function handleGenerate() {
    const trimmedCustomerMessage = customerMessage.trim();
    if (!trimmedCustomerMessage || loadingRef.current) {
      return;
    }

    const request = {
      conversation_id: currentChatSession?.sessionId || buildConversationId(),
      customer_message: trimmedCustomerMessage,
    };

    loadingRef.current = true;
    setLoading(true);
    setErrorMessage(null);
    setCopyFeedback(null);

    try {
      const response = await generateDraft(request);
      setDraft(response);
      await refreshDraftHistory();
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : "生成候选回复失败");
    } finally {
      loadingRef.current = false;
      setLoading(false);
    }
  }

  async function handleCopy() {
    if (!draft?.reply_text) {
      return;
    }

    try {
      await navigator.clipboard.writeText(draft.reply_text);
      setCopyFeedback("已复制到剪贴板");
      setCopySucceeded(true);
    } catch {
      setCopyFeedback("复制失败，请手动复制");
      setCopySucceeded(false);
    }
  }

  async function importKnowledgeFile(file: File) {
    if (file.size > MAX_IMPORT_FILE_BYTES) {
      setImportError("文件不能超过 10MB，请先拆分后再导入。");
      setImportMessage(null);
      return;
    }

    setImportLoading(true);
    setImportError(null);
    setImportMessage(null);

    try {
      const response = await uploadKnowledgeLibrary(selectedLibraryType, file);
      setLastLibraryUpload(response);
      setImportMessage(response.message || `已更新 ${LIBRARY_TYPE_LABELS[response.library_type]}`);
      closeUploadModal();
      await refreshKnowledgeLibraries();
    } catch (error) {
      setImportError(error instanceof Error ? error.message : "导入知识失败");
    } finally {
      setImportLoading(false);
    }
  }

  async function handleImportFileChange(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    event.target.value = "";
    if (!file) {
      return;
    }
    await importKnowledgeFile(file);
  }

  async function handleImportDrop(event: DragEvent<HTMLDivElement>) {
    event.preventDefault();
    const file = event.dataTransfer.files?.[0];
    if (!file) {
      return;
    }
    await importKnowledgeFile(file);
  }

  async function handleHistoryFeedback(
    entry: DraftHistoryItem,
    finalStatus: "adopted" | "edited" | "handoff" | "discarded",
  ) {
    try {
      await submitDraftFeedback({
        draft_id: entry.draft_id,
        final_status: finalStatus,
        operator_note: "",
      });
      setHistory((current) =>
        current.map((item) =>
          item.draft_id === entry.draft_id ? { ...item, final_status: finalStatus } : item,
        ),
      );
      setHistoryMessage("历史反馈已保存");
    } catch (error) {
      setHistoryMessage(error instanceof Error ? error.message : "保存历史反馈失败");
    }
  }

  function handleReuse(entry: DraftHistoryItem) {
    setCustomerMessage(entry.customer_message);
    setDraft(buildDraftFromHistory(entry));
    setErrorMessage(null);
    setCopyFeedback(null);
    setCopySucceeded(false);
    setActivePage("runtime");
  }

  function getGenerateDisabledReason() {
    if (loading) {
      return "正在生成候选回复，请稍等片刻。";
    }
    if (!customerMessage.trim()) {
      return "先输入客户消息后，才能生成候选回复。";
    }
    return null;
  }

  function renderSettingsContent() {
    if (activeSettingsSection === "tasks") {
      return (
        <PlaceholderPanel
          title="任务设置"
          description="即将开放"
          note="后续会在这里接入知识同步策略、人工审核偏好和流程开关。"
        />
      );
    }

    if (activeSettingsSection === "reports") {
      return (
        <PlaceholderPanel
          title="运营报告"
          description="即将开放"
          note="后续会在这里接入日报、趋势和人工复盘。"
        />
      );
    }

    if (activeSettingsSection === "profile") {
      return (
        <PlaceholderPanel
          title="我的"
          description="即将开放"
          note="后续扩展个人偏好、账户信息与快捷配置。"
        />
      );
    }

    return (
      <div className="settings-stack">
        <KnowledgeLibraryView
          libraries={libraries}
          importMessage={importMessage}
          importError={importError ?? historyMessage}
          lastUpload={lastLibraryUpload}
          onOpenUpload={openUploadModal}
        />
        <RunHistoryPanel history={history} onReuse={handleReuse} onFeedback={handleHistoryFeedback} />
      </div>
    );
  }

  const latestHistoryEntry = history[0] ?? null;

  return (
    <main className="shell">
      <section className="workspace-tabs" role="tablist" aria-label="工作台页面">
        <button
          id="tab-runtime"
          className="tab-button"
          role="tab"
          type="button"
          aria-selected={activePage === "runtime"}
          aria-controls="panel-runtime"
          onClick={() => setActivePage("runtime")}
        >
          实际运行
        </button>
        <button
          id="tab-settings"
          className="tab-button"
          role="tab"
          type="button"
          aria-selected={activePage === "settings"}
          aria-controls="panel-settings"
          onClick={() => setActivePage("settings")}
        >
          设置页面
        </button>
      </section>

      {activePage === "runtime" ? (
        <section id="panel-runtime" className="runtime-layout" role="tabpanel" aria-labelledby="tab-runtime">
          <ChatSessionList
            sessions={chatSessions}
            currentSessionId={currentChatSession?.sessionId ?? null}
            onSelect={handleSelectChatSession}
          />
          <div className="runtime-stage">
            <ChatSyncToolbar
              currentSessionName={currentChatSession?.displayName ?? "未选择会话"}
              syncStatus={currentChatSession ? "已连接" : "未连接"}
              autoGenerate={currentChatSession?.autoGenerate ?? false}
              onAutoGenerateChange={handleToggleAutoGenerate}
              onRefresh={handleRefreshCurrentChatSession}
            />
            <ConversationPanel
              customerMessage={customerMessage}
              loading={loading}
              disabledReason={getGenerateDisabledReason()}
              onCustomerMessageChange={setCustomerMessage}
              onGenerate={handleGenerate}
            />
            <RecentRunCard entry={latestHistoryEntry} onReuse={handleReuse} />
          </div>
          <div className="runtime-review">
            <ReplyDraftPanel
              draft={draft}
              errorMessage={errorMessage}
              copyFeedback={copyFeedback}
              copySucceeded={copySucceeded}
              onCopy={handleCopy}
              onRetry={handleGenerate}
            />
          </div>
        </section>
      ) : (
        <section id="panel-settings" className="settings-page" role="tabpanel" aria-labelledby="tab-settings">
          <SettingsShell
            nav={<SettingsNav activeSection={activeSettingsSection} onChange={setActiveSettingsSection} />}
            content={renderSettingsContent()}
          />
          <KnowledgeUploadModal
            open={uploadModalOpen}
            importLoading={importLoading}
            importError={importError}
            selectedLibraryType={selectedLibraryType}
            onLibraryTypeChange={setSelectedLibraryType}
            onFileChange={handleImportFileChange}
            onDrop={handleImportDrop}
            onClose={closeUploadModal}
          />
        </section>
      )}
    </main>
  );
}
