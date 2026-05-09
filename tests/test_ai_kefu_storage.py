from pathlib import Path
import sqlite3

import pytest

from moments_inventory.ai_kefu.loaders import load_text_document
from moments_inventory.ai_kefu.models import KnowledgeChunk
from moments_inventory.ai_kefu.storage import SQLiteKefuRepository


def test_load_text_document_reads_utf8_and_trims_whitespace(tmp_path: Path):
    document_path = tmp_path / "faq.txt"
    document_path.write_text("\n  第一行\n第二行 \n", encoding="utf-8")

    content = load_text_document(document_path)

    assert content == "第一行\n第二行"


def test_sqlite_kefu_repository_supports_in_memory_database():
    repository = SQLiteKefuRepository(":memory:")
    repository.initialize()
    repository.save_knowledge_chunks(
        [
            KnowledgeChunk(
                chunk_id="chunk-001",
                source_name="faq.txt",
                category="售后",
                text="支持七天内问题排查。",
                tags=["售后", "时效"],
            )
        ]
    )

    assert repository.list_knowledge_chunks() == [
        KnowledgeChunk(
            chunk_id="chunk-001",
            source_name="faq.txt",
            category="售后",
            text="支持七天内问题排查。",
            tags=["售后", "时效"],
        )
    ]


def test_sqlite_kefu_repository_stores_tags_as_json_string(tmp_path: Path):
    database_path = tmp_path / "ai-kefu.db"
    repository = SQLiteKefuRepository(database_path)
    repository.save_knowledge_chunks(
        [
            KnowledgeChunk(
                chunk_id="chunk-001",
                source_name="faq.txt",
                category="售后",
                text="支持七天内问题排查。",
                tags=["售后", "时效"],
            )
        ]
    )

    with sqlite3.connect(database_path) as conn:
        row = conn.execute(
            "select tags_json from knowledge_chunks where chunk_id = ?",
            ("chunk-001",),
        ).fetchone()

    assert row == ('["售后", "时效"]',)


def test_sqlite_kefu_repository_rejects_invalid_tags_json_shape(tmp_path: Path):
    database_path = tmp_path / "ai-kefu.db"
    repository = SQLiteKefuRepository(database_path)
    repository.initialize()

    with sqlite3.connect(database_path) as conn:
        conn.execute(
            """
            insert into knowledge_chunks (
              chunk_id, source_name, category, text, tags_json
            ) values (?, ?, ?, ?, ?)
            """,
            ("chunk-001", "faq.txt", "售后", "支持七天内问题排查。", '{"tag": "售后"}'),
        )

    with pytest.raises(ValueError, match="tags_json"):
        repository.list_knowledge_chunks()


def test_sqlite_kefu_repository_updates_existing_chunk(tmp_path: Path):
    database_path = tmp_path / "ai-kefu.db"
    repository = SQLiteKefuRepository(database_path)
    repository.save_knowledge_chunks(
        [
            KnowledgeChunk(
                chunk_id="chunk-001",
                source_name="faq-v1.txt",
                category="售后",
                text="旧内容",
                tags=["售后"],
            )
        ]
    )

    repository.save_knowledge_chunks(
        [
            KnowledgeChunk(
                chunk_id="chunk-001",
                source_name="faq-v2.txt",
                category="物流",
                text="新内容",
                tags=["物流", "时效"],
            )
        ]
    )

    assert repository.list_knowledge_chunks() == [
        KnowledgeChunk(
            chunk_id="chunk-001",
            source_name="faq-v2.txt",
            category="物流",
            text="新内容",
            tags=["物流", "时效"],
        )
    ]


def test_sqlite_kefu_repository_can_delete_chunks_by_source(tmp_path: Path):
    repository = SQLiteKefuRepository(tmp_path / "ai-kefu.db")
    repository.save_knowledge_chunks(
        [
            KnowledgeChunk(
                chunk_id="chunk-001",
                source_name="faq.txt",
                category="售后",
                text="旧内容一",
                tags=[],
            ),
            KnowledgeChunk(
                chunk_id="chunk-002",
                source_name="faq.txt",
                category="售后",
                text="旧内容二",
                tags=[],
            ),
            KnowledgeChunk(
                chunk_id="chunk-003",
                source_name="product.txt",
                category="产品",
                text="产品内容",
                tags=[],
            ),
        ]
    )

    repository.delete_knowledge_chunks_by_source("faq.txt")

    assert repository.list_knowledge_chunks() == [
        KnowledgeChunk(
            chunk_id="chunk-003",
            source_name="product.txt",
            category="产品",
            text="产品内容",
            tags=[],
        )
    ]


def test_sqlite_kefu_repository_can_persist_conversation_workflow_state(tmp_path: Path):
    from moments_inventory.ai_kefu.workflow import ConversationWorkflowState

    repository = SQLiteKefuRepository(tmp_path / "ai-kefu.db")
    repository.initialize()

    repository.save_conversation_workflow_state(
        ConversationWorkflowState(
            conversation_id="conv-001",
            customer_stage="确认购买",
            intent="购买流程",
            should_handoff=False,
        )
    )

    state = repository.get_conversation_workflow_state("conv-001")

    assert state is not None
    assert state.conversation_id == "conv-001"
    assert state.customer_stage == "确认购买"
    assert state.intent == "购买流程"
    assert state.should_handoff is False
def test_sqlite_kefu_repository_persists_explicit_knowledge_tier(tmp_path: Path):
    repository = SQLiteKefuRepository(tmp_path / "ai-kefu.db")
    repository.save_knowledge_chunks(
        [
            KnowledgeChunk(
                chunk_id="chunk-001",
                source_name="shipping-rules.md",
                category="供应链发货",
                knowledge_tier="shipping_info",
                text="深圳仓现货通常 24 小时内发出。",
                tags=["supplier:老王", "深圳仓"],
            )
        ]
    )

    assert repository.list_knowledge_chunks() == [
        KnowledgeChunk(
            chunk_id="chunk-001",
            source_name="shipping-rules.md",
            category="供应链发货",
            knowledge_tier="shipping_info",
            text="深圳仓现货通常 24 小时内发出。",
            tags=["supplier:老王", "深圳仓"],
        )
    ]


def test_sqlite_kefu_repository_round_trips_chunk_embeddings(tmp_path: Path):
    repository = SQLiteKefuRepository(tmp_path / "ai-kefu.db")
    repository.save_knowledge_chunks(
        [
            KnowledgeChunk(
                chunk_id="chunk-embedding-001",
                source_name="faq.txt",
                category="售后",
                text="退款到账通常需要 1 到 3 个工作日。",
                tags=["退款", "到账"],
                embedding=[0.1, 0.2, 0.3],
            )
        ]
    )

    chunks = repository.list_knowledge_chunks()

    assert len(chunks) == 1
    assert chunks[0].embedding == [0.1, 0.2, 0.3]
