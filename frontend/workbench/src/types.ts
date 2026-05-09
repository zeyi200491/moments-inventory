export type RiskLevel = "L1" | "L2" | "L3" | "L4";

export type KnowledgeTier =
  | "master_rule"
  | "fixed_reply"
  | "faq"
  | "product_inventory"
  | "product_material"
  | "shipping_info"
  | "after_sale_doc"
  | "style_sample";

export type UsedKnowledge = {
  chunk_id: string;
  source_name: string;
  category: string;
  knowledge_tier: KnowledgeTier;
  text: string;
  tags: string[];
};

export type DraftRequest = {
  conversation_id: string;
  customer_message: string;
};

export type DraftResponse = {
  reply_text: string;
  risk_level: RiskLevel;
  reason: string;
  customer_stage: string;
  intent: string;
  should_handoff: boolean;
  reply_type: string;
  required_data: string[];
  used_knowledge: UsedKnowledge[];
};

export type KnowledgeImportRequest = {
  source_name: string;
  category: string;
  knowledge_tier: KnowledgeTier;
  content: string;
  structured_fields?: Record<string, string>;
  tags: string[];
};

export type KnowledgeImportResponse = {
  source_name: string;
  category: string;
  knowledge_tier: KnowledgeTier;
  chunk_count: number;
  tags: string[];
};

export type KnowledgeSourceSummary = {
  source_name: string;
  category: string;
  knowledge_tier: KnowledgeTier;
  chunk_count: number;
  tags: string[];
};

export type DraftHistoryWorkflow = {
  customer_stage?: string;
  intent?: string;
  should_handoff?: boolean;
  reply_type?: string;
  required_data?: string[];
};

export type DraftHistoryStatus =
  | "generated"
  | "adopted"
  | "edited"
  | "handoff"
  | "discarded";

export type DraftHistoryItem = {
  draft_id: string;
  conversation_id: string;
  customer_message: string;
  reply_text: string;
  risk_level: RiskLevel;
  reason: string;
  workflow: DraftHistoryWorkflow;
  used_chunk_ids: string[];
  final_status: DraftHistoryStatus | string;
  operator_note: string;
  created_at: string;
};

export type DraftFeedbackRequest = {
  draft_id: string;
  final_status: DraftHistoryStatus | string;
  operator_note: string;
};

export type DraftFeedbackResponse = {
  ok: boolean;
};

export type ChatSyncSession = {
  sessionId: string;
  username: string;
  displayName: string;
  sessionType: string;
  lastTimestamp: number;
  unreadCount: number;
  draftBuffer: string;
  autoGenerate: boolean;
  isCurrent: boolean;
  lastMessageTimestamp: number;
};

export type SetCurrentChatSyncSessionRequest = {
  sessionId: string;
  autoGenerate: boolean;
};
