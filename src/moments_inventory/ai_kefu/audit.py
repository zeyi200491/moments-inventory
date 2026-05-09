from __future__ import annotations

from dataclasses import dataclass

from moments_inventory.ai_kefu.risk import RiskLevel


@dataclass(slots=True)
class DraftAuditRecord:
    draft_id: str
    conversation_id: str
    customer_message: str
    reply_text: str
    risk_level: RiskLevel
    reason: str
    workflow_json: str
    used_chunk_ids_json: str
    final_status: str
    operator_note: str
    created_at: str
