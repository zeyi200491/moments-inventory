from pathlib import Path
import sqlite3

import pytest

from moments_inventory.ai_kefu.loaders import load_text_document
from moments_inventory.ai_kefu.models import KnowledgeChunk, LibraryStateRecord
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


def test_sqlite_kefu_repository_round_trips_library_state_record(tmp_path: Path):
    repository = SQLiteKefuRepository(tmp_path / "ai-kefu.db")
    record = LibraryStateRecord(
        library_type="master_rule_bundle",
        source_name="library:master_rule_bundle",
        original_filename="master_rule_bundle_2026-05-15.md",
        imported_count=3,
        skipped_count=1,
        status="active",
        uploaded_at="2026-05-15T10:05:00+08:00",
    )

    repository.save_library_state(record)

    assert repository.get_library_state("master_rule_bundle") == record
    assert repository.list_library_states() == [record]


def test_sqlite_kefu_repository_replaces_library_state_by_library_type(tmp_path: Path):
    repository = SQLiteKefuRepository(tmp_path / "ai-kefu.db")
    repository.save_library_state(
        LibraryStateRecord(
            library_type="shipping_info_excel",
            source_name="library:shipping_info_excel:2026-05-14",
            original_filename="shipping_info_2026-05-14.xlsx",
            imported_count=12,
            skipped_count=0,
            status="active",
            uploaded_at="2026-05-14T09:00:00+08:00",
        )
    )

    repository.save_library_state(
        LibraryStateRecord(
            library_type="shipping_info_excel",
            source_name="library:shipping_info_excel:2026-05-15",
            original_filename="shipping_info_2026-05-15.xlsx",
            imported_count=15,
            skipped_count=2,
            status="active",
            uploaded_at="2026-05-15T09:00:00+08:00",
        )
    )

    assert repository.get_library_state("shipping_info_excel") == LibraryStateRecord(
        library_type="shipping_info_excel",
        source_name="library:shipping_info_excel:2026-05-15",
        original_filename="shipping_info_2026-05-15.xlsx",
        imported_count=15,
        skipped_count=2,
        status="active",
        uploaded_at="2026-05-15T09:00:00+08:00",
    )
    assert repository.list_library_states() == [
        LibraryStateRecord(
            library_type="shipping_info_excel",
            source_name="library:shipping_info_excel:2026-05-15",
            original_filename="shipping_info_2026-05-15.xlsx",
            imported_count=15,
            skipped_count=2,
            status="active",
            uploaded_at="2026-05-15T09:00:00+08:00",
        )
    ]


def test_sqlite_kefu_repository_can_delete_chunks_by_source_prefix(tmp_path: Path):
    repository = SQLiteKefuRepository(tmp_path / "ai-kefu.db")
    repository.save_knowledge_chunks(
        [
            KnowledgeChunk(
                chunk_id="chunk-001",
                source_name="library:master_rule_bundle",
                category="总规则",
                text="主规则索引",
                tags=[],
            ),
            KnowledgeChunk(
                chunk_id="chunk-002",
                source_name="library:master_rule_bundle:section-001",
                category="总规则",
                text="主规则正文",
                tags=[],
            ),
            KnowledgeChunk(
                chunk_id="chunk-003",
                source_name="library:other_bundle:section-001",
                category="其他规则",
                text="保留内容",
                tags=[],
            ),
        ]
    )

    repository.delete_knowledge_chunks_by_source_prefix("library:master_rule_bundle")

    assert repository.list_knowledge_chunks() == [
        KnowledgeChunk(
            chunk_id="chunk-003",
            source_name="library:other_bundle:section-001",
            category="其他规则",
            text="保留内容",
            tags=[],
        )
    ]


def test_sqlite_kefu_repository_list_knowledge_chunks_order_remains_stable_after_prefix_delete(
    tmp_path: Path,
):
    repository = SQLiteKefuRepository(tmp_path / "ai-kefu.db")
    repository.save_knowledge_chunks(
        [
            KnowledgeChunk(
                chunk_id="chunk-002",
                source_name="library:master_rule_bundle:section-001",
                category="总规则",
                text="会被删除",
                tags=[],
            ),
            KnowledgeChunk(
                chunk_id="chunk-001",
                source_name="faq.txt",
                category="售后",
                text="应继续保留",
                tags=[],
            ),
            KnowledgeChunk(
                chunk_id="chunk-003",
                source_name="product.txt",
                category="商品",
                text="仍按 chunk_id 排序",
                tags=[],
            ),
        ]
    )

    repository.delete_knowledge_chunks_by_source_prefix("library:master_rule_bundle")

    assert repository.list_knowledge_chunks() == [
        KnowledgeChunk(
            chunk_id="chunk-001",
            source_name="faq.txt",
            category="售后",
            text="应继续保留",
            tags=[],
        ),
        KnowledgeChunk(
            chunk_id="chunk-003",
            source_name="product.txt",
            category="商品",
            text="仍按 chunk_id 排序",
            tags=[],
        ),
    ]
