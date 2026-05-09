from __future__ import annotations

import json

from moments_inventory.ai_kefu.models import KnowledgeChunk
from moments_inventory.ai_kefu.risk import RiskDecision
from moments_inventory.ai_kefu.storage import SQLiteKefuRepository


class RecordingChatProvider:
    def __init__(self, reply_text: str) -> None:
        self._reply_text = reply_text

    def create_reply(self, system_prompt: str, user_prompt: str) -> str:
        return self._reply_text


def test_generate_draft_persists_audit_record(tmp_path):
    from moments_inventory.ai_kefu.service import KefuDraftService

    repository = SQLiteKefuRepository(tmp_path / "ai-kefu.db")
    repository.initialize()
    repository.save_knowledge_chunks(
        [
            KnowledgeChunk(
                chunk_id="faq-001",
                source_name="faq.txt",
                category="发货",
                text="现货订单通常会在 24 小时内发货。",
                tags=["发货", "物流"],
            )
        ]
    )
    service = KefuDraftService(
        repository=repository,
        chat_provider=RecordingChatProvider("今天拍的话一般 24 小时内能安排发出。"),
    )

    result = service.generate_draft(
        conversation_id="conv-audit-001",
        customer_message="今天拍的话多久发货",
        risk_decision=RiskDecision(risk_level="L2", reason="发货咨询"),
    )

    records = repository.list_draft_audit_records(limit=10)

    assert len(records) == 1
    assert records[0].draft_id == result.draft_id
    assert records[0].conversation_id == "conv-audit-001"
    assert records[0].reply_text == "今天拍的话一般 24 小时内能安排发出。"
    assert records[0].risk_level == "L2"
    assert json.loads(records[0].used_chunk_ids_json) == ["faq-001"]


def test_repository_can_update_draft_feedback(tmp_path):
    from moments_inventory.ai_kefu.audit import DraftAuditRecord

    repository = SQLiteKefuRepository(tmp_path / "ai-kefu.db")
    repository.initialize()
    repository.save_draft_audit_record(
        DraftAuditRecord(
            draft_id="draft-001",
            conversation_id="conv-001",
            customer_message="测试消息",
            reply_text="测试回复",
            risk_level="L1",
            reason="普通咨询",
            workflow_json="{}",
            used_chunk_ids_json="[]",
            final_status="generated",
            operator_note="",
            created_at="2026-05-07T12:00:00+08:00",
        )
    )

    repository.update_draft_audit_record_feedback(
        draft_id="draft-001",
        final_status="edited",
        operator_note="价格说明改成更保守",
    )
    records = repository.list_draft_audit_records(limit=10)

    assert len(records) == 1
    assert records[0].final_status == "edited"
    assert records[0].operator_note == "价格说明改成更保守"
