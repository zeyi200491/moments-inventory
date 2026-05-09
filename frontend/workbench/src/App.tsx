import { useEffect, useRef, useState } from "react";
import type { ChangeEvent, DragEvent } from "react";

import {
  generateDraft,
  getChatSyncSession,
  importKnowledge,
  listDraftHistory,
  listChatSyncSessions,
  listKnowledgeSources,
  refreshChatSyncSession,
  setCurrentChatSyncSession,
  submitDraftFeedback,
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
import {
  STRUCTURED_KNOWLEDGE_SCHEMAS,
  createEmptyStructuredFields,
  isStructuredKnowledgeTier,
} from "./structuredKnowledge";
import type {
  ChatSyncSession,
  DraftHistoryItem,
  DraftResponse,
  KnowledgeTier,
  KnowledgeImportResponse,
  KnowledgeSourceSummary,
} from "./types";

const MAX_IMPORT_FILE_BYTES = 10 * 1024 * 1024;
const CHAT_SYNC_POLL_MS = 2000;
const AUTO_GENERATE_DEBOUNCE_MS = 1200;
const DEFAULT_IMPORT_CATEGORY = "产品";
const DEFAULT_IMPORT_KNOWLEDGE_TIER: KnowledgeTier = "product_material";
const DEFAULT_STRUCTURED_SOURCE_NAME = "";

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

function resolveDefaultCategoryByTier(knowledgeTier: KnowledgeTier): string {
  if (isStructuredKnowledgeTier(knowledgeTier)) {
    return STRUCTURED_KNOWLEDGE_SCHEMAS[knowledgeTier].defaultCategory;
  }
  return DEFAULT_IMPORT_CATEGORY;
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

  const [importCategory, setImportCategory] = useState(DEFAULT_IMPORT_CATEGORY);
  const [importKnowledgeTier, setImportKnowledgeTier] = useState<KnowledgeTier>(
    DEFAULT_IMPORT_KNOWLEDGE_TIER,
  );
  const [importTagsText, setImportTagsText] = useState("");
  const [structuredSourceName, setStructuredSourceName] = useState(DEFAULT_STRUCTURED_SOURCE_NAME);
  const [structuredFields, setStructuredFields] = useState<Record<string, string>>(
    createEmptyStructuredFields("product_material"),
  );
  const [importLoading, setImportLoading] = useState(false);
  const [importMessage, setImportMessage] = useState<string | null>(null);
  const [importError, setImportError] = useState<string | null>(null);
  const [lastImport, setLastImport] = useState<KnowledgeImportResponse | null>(null);
  const [importedSources, setImportedSources] = useState<KnowledgeSourceSummary[]>([]);

  useEffect(() => {
    loadingRef.current = loading;
  }, [loading]);

  useEffect(() => {
    void refreshKnowledgeSources();
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
  ]);

  async function refreshKnowledgeSources() {
    try {
      const sources = await listKnowledgeSources();
      setImportedSources(sources);
    } catch (error) {
      setImportError(error instanceof Error ? error.message : "读取知识列表失败");
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
    setImportCategory(DEFAULT_IMPORT_CATEGORY);
    setImportKnowledgeTier(DEFAULT_IMPORT_KNOWLEDGE_TIER);
    setImportTagsText("");
    setStructuredSourceName(DEFAULT_STRUCTURED_SOURCE_NAME);
    setStructuredFields(createEmptyStructuredFields("product_material"));
    setImportError(null);
  }

  function closeUploadModal() {
    setUploadModalOpen(false);
    resetImportForm();
  }

  function handleImportKnowledgeTierChange(value: KnowledgeTier) {
    setImportKnowledgeTier(value);
    setImportCategory(resolveDefaultCategoryByTier(value));
    if (isStructuredKnowledgeTier(value)) {
      setStructuredFields(createEmptyStructuredFields(value));
    } else {
      setStructuredFields(createEmptyStructuredFields("product_material"));
    }
    setStructuredSourceName(DEFAULT_STRUCTURED_SOURCE_NAME);
  }

  function handleStructuredFieldChange(fieldKey: string, value: string) {
    setStructuredFields((current) => ({
      ...current,
      [fieldKey]: value,
    }));
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
      const content = await file.text();
      const response = await importKnowledge({
        source_name: file.name,
        category: importCategory.trim() || DEFAULT_IMPORT_CATEGORY,
        knowledge_tier: importKnowledgeTier,
        content,
        tags: importTagsText
          .split(",")
          .map((item) => item.trim())
          .filter(Boolean),
      });

      setLastImport(response);
      setImportMessage(`导入完成：${response.source_name}，共切分 ${response.chunk_count} 段。`);
      closeUploadModal();
      await refreshKnowledgeSources();
    } catch (error) {
      setImportError(error instanceof Error ? error.message : "导入知识失败");
    } finally {
      setImportLoading(false);
    }
  }

  async function handleStructuredSubmit() {
    if (!isStructuredKnowledgeTier(importKnowledgeTier)) {
      return;
    }

    const sourceName = structuredSourceName.trim();
    if (!sourceName) {
      setImportError("结构化条目必须填写条目名称。");
      return;
    }

    const normalizedFields = Object.fromEntries(
      Object.entries(structuredFields)
        .map(([key, value]) => [key, value.trim()])
        .filter(([, value]) => value),
    );
    if (Object.keys(normalizedFields).length === 0) {
      setImportError("结构化条目至少填写一个业务字段。");
      return;
    }

    setImportLoading(true);
    setImportError(null);
    setImportMessage(null);

    try {
      const response = await importKnowledge({
        source_name: sourceName,
        category: importCategory.trim() || resolveDefaultCategoryByTier(importKnowledgeTier),
        knowledge_tier: importKnowledgeTier,
        content: "",
        structured_fields: normalizedFields,
        tags: importTagsText
          .split(",")
          .map((item) => item.trim())
          .filter(Boolean),
      });
      setLastImport(response);
      setImportMessage(`导入完成：${response.source_name}，共切分 ${response.chunk_count} 段。`);
      closeUploadModal();
      await refreshKnowledgeSources();
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
          importedSources={importedSources}
          importMessage={importMessage}
          importError={importError ?? historyMessage}
          lastImport={lastImport}
          onOpenUpload={() => setUploadModalOpen(true)}
        />
        <RunHistoryPanel
          history={history}
          onReuse={handleReuse}
          onFeedback={handleHistoryFeedback}
        />
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
        <section
          id="panel-runtime"
          className="runtime-layout"
          role="tabpanel"
          aria-labelledby="tab-runtime"
        >
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
        <section
          id="panel-settings"
          className="settings-page"
          role="tabpanel"
          aria-labelledby="tab-settings"
        >
          <SettingsShell
            nav={
              <SettingsNav
                activeSection={activeSettingsSection}
                onChange={setActiveSettingsSection}
              />
            }
            content={renderSettingsContent()}
          />
          <KnowledgeUploadModal
            open={uploadModalOpen}
            importLoading={importLoading}
            importError={importError}
            importCategory={importCategory}
            importKnowledgeTier={importKnowledgeTier}
            importTagsText={importTagsText}
            structuredSourceName={structuredSourceName}
            structuredFields={structuredFields}
            onImportCategoryChange={setImportCategory}
            onImportKnowledgeTierChange={handleImportKnowledgeTierChange}
            onImportTagsTextChange={setImportTagsText}
            onStructuredSourceNameChange={setStructuredSourceName}
            onStructuredFieldChange={handleStructuredFieldChange}
            onStructuredSubmit={handleStructuredSubmit}
            onFileChange={handleImportFileChange}
            onDrop={handleImportDrop}
            onClose={closeUploadModal}
          />
        </section>
      )}
    </main>
  );
}
