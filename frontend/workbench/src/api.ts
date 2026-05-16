import type {
  ChatSyncSession,
  DraftFeedbackRequest,
  DraftFeedbackResponse,
  DraftHistoryItem,
  DraftRequest,
  DraftResponse,
  KnowledgeImportRequest,
  KnowledgeImportResponse,
  KnowledgeLibraryState,
  KnowledgeLibraryType,
  KnowledgeLibraryUploadResponse,
  KnowledgeSourceSummary,
  SetCurrentChatSyncSessionRequest,
} from "./types";

const API_KEY = import.meta.env.VITE_AI_KEFU_API_KEY?.trim() || "";

function buildHeaders(extraHeaders?: HeadersInit): HeadersInit {
  return {
    "Content-Type": "application/json",
    ...(API_KEY ? { "X-API-Key": API_KEY } : {}),
    ...extraHeaders,
  };
}

async function buildErrorMessage(response: Response, fallback: string): Promise<string> {
  try {
    const payload = (await response.clone().json()) as { detail?: unknown; message?: unknown };
    if (typeof payload.detail === "string" && payload.detail.trim()) {
      return payload.detail.trim();
    }
    if (typeof payload.message === "string" && payload.message.trim()) {
      return payload.message.trim();
    }
  } catch {
    // 忽略非 JSON 响应，继续尝试读取纯文本。
  }

  try {
    const text = (await response.text()).trim();
    if (text) {
      return text;
    }
  } catch {
    // 读取失败时回退到通用文案。
  }

  return `${fallback}，HTTP ${response.status}`;
}

async function requestJson<T>(
  input: string,
  init?: Omit<RequestInit, "headers"> & { headers?: HeadersInit },
): Promise<T> {
  const response = await fetch(input, {
    ...init,
    headers: buildHeaders(init?.headers),
  });

  if (!response.ok) {
    throw new Error(await buildErrorMessage(response, "请求失败"));
  }

  return (await response.json()) as T;
}

export async function generateDraft(
  payload: DraftRequest,
  signal?: AbortSignal,
): Promise<DraftResponse> {
  return requestJson<DraftResponse>("/api/drafts", {
    method: "POST",
    body: JSON.stringify(payload),
    signal,
  });
}

export async function importKnowledge(
  payload: KnowledgeImportRequest,
): Promise<KnowledgeImportResponse> {
  return requestJson<KnowledgeImportResponse>("/api/knowledge/imports", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export async function listKnowledgeSources(): Promise<KnowledgeSourceSummary[]> {
  return requestJson<KnowledgeSourceSummary[]>("/api/knowledge/sources");
}

export async function listKnowledgeLibraries(): Promise<KnowledgeLibraryState[]> {
  return requestJson<KnowledgeLibraryState[]>("/api/knowledge/libraries");
}

export async function uploadKnowledgeLibrary(
  libraryType: KnowledgeLibraryType,
  file: File,
): Promise<KnowledgeLibraryUploadResponse> {
  const formData = new FormData();
  formData.append("library_type", libraryType);
  formData.append("file", file);

  const response = await fetch("/api/knowledge/uploads", {
    method: "POST",
    headers: API_KEY ? { "X-API-Key": API_KEY } : undefined,
    body: formData,
  });

  if (!response.ok) {
    throw new Error(await buildErrorMessage(response, "上传失败"));
  }

  return (await response.json()) as KnowledgeLibraryUploadResponse;
}

export async function listDraftHistory(): Promise<DraftHistoryItem[]> {
  return requestJson<DraftHistoryItem[]>("/api/drafts/history");
}

export async function submitDraftFeedback(
  payload: DraftFeedbackRequest,
): Promise<DraftFeedbackResponse> {
  return requestJson<DraftFeedbackResponse>("/api/drafts/feedback", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export async function listChatSyncSessions(): Promise<ChatSyncSession[]> {
  return requestJson<ChatSyncSession[]>("/api/chat-sync/sessions");
}

export async function getChatSyncSession(sessionId: string): Promise<ChatSyncSession> {
  return requestJson<ChatSyncSession>(`/api/chat-sync/sessions/${sessionId}`);
}

export async function setCurrentChatSyncSession(
  payload: SetCurrentChatSyncSessionRequest,
): Promise<ChatSyncSession> {
  return requestJson<ChatSyncSession>("/api/chat-sync/current-session", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export async function refreshChatSyncSession(sessionId: string): Promise<ChatSyncSession> {
  return requestJson<ChatSyncSession>(`/api/chat-sync/sessions/${sessionId}/refresh`, {
    method: "POST",
  });
}
