from __future__ import annotations

import json
import sqlite3
import threading
from pathlib import Path

from moments_inventory.ai_kefu.audit import DraftAuditRecord
from moments_inventory.ai_kefu.models import KnowledgeChunk, LibraryStateRecord, ProductRecord
from moments_inventory.ai_kefu.workflow import ConversationWorkflowState


class SQLiteKefuRepository:
    def __init__(self, database_path: str | Path) -> None:
        self._database_path = str(database_path)
        self._connection: sqlite3.Connection | None = None
        self._lock = threading.RLock()

    def _get_connection(self) -> sqlite3.Connection:
        with self._lock:
            if self._connection is None:
                if self._database_path != ":memory:":
                    Path(self._database_path).parent.mkdir(parents=True, exist_ok=True)
                self._connection = sqlite3.connect(
                    self._database_path,
                    check_same_thread=False,
                )
            return self._connection

    def close(self) -> None:
        with self._lock:
            if self._connection is not None:
                self._connection.close()
                self._connection = None

    def __del__(self) -> None:
        self.close()

    def initialize(self) -> None:
        with self._lock:
            with self._get_connection() as conn:
                conn.execute(
                    """
                    create table if not exists knowledge_chunks (
                      chunk_id text primary key,
                      source_name text not null,
                      category text not null,
                      knowledge_tier text,
                      text text not null,
                      tags_json text not null,
                      embedding_json text
                    )
                    """
                )
                columns = {
                    row[1]
                    for row in conn.execute("pragma table_info(knowledge_chunks)").fetchall()
                }
                if "knowledge_tier" not in columns:
                    conn.execute("alter table knowledge_chunks add column knowledge_tier text")
                if "embedding_json" not in columns:
                    conn.execute("alter table knowledge_chunks add column embedding_json text")
                conn.execute(
                    """
                    create table if not exists conversation_workflow_state (
                      conversation_id text primary key,
                      customer_stage text not null,
                      intent text not null,
                      should_handoff integer not null
                    )
                    """
                )
                conn.execute(
                    """
                    create table if not exists products (
                      product_id text primary key,
                      source_record_id text not null,
                      brand text not null,
                      model_std text not null,
                      sale_status text not null,
                      is_functional integer not null,
                      has_inspection_video integer not null,
                      has_sample_output integer not null,
                      cost_price integer not null,
                      sale_price integer not null,
                      profit_amount integer not null,
                      source_name text not null,
                      source_wxid text not null,
                      published_at text not null,
                      image_path text not null,
                      video_path text not null,
                      raw_copy text not null,
                      manual_review_needed integer not null
                    )
                    """
                )
                conn.execute(
                    """
                    create table if not exists library_state (
                      library_type text primary key,
                      source_name text not null,
                      original_filename text not null,
                      imported_count integer not null,
                      skipped_count integer not null,
                      status text not null,
                      uploaded_at text not null
                    )
                    """
                )
                conn.execute(
                    """
                    create table if not exists draft_audit_records (
                      draft_id text primary key,
                      conversation_id text not null,
                      customer_message text not null,
                      reply_text text not null,
                      risk_level text not null,
                      reason text not null,
                      workflow_json text not null,
                      used_chunk_ids_json text not null,
                      final_status text not null,
                      operator_note text not null,
                      created_at text not null
                    )
                    """
                )

    def save_knowledge_chunks(self, chunks: list[KnowledgeChunk]) -> None:
        self.initialize()
        with self._lock:
            with self._get_connection() as conn:
                conn.executemany(
                    """
                    insert into knowledge_chunks (
                      chunk_id, source_name, category, knowledge_tier, text, tags_json, embedding_json
                    ) values (?, ?, ?, ?, ?, ?, ?)
                    on conflict(chunk_id) do update set
                      source_name = excluded.source_name,
                      category = excluded.category,
                      knowledge_tier = excluded.knowledge_tier,
                      text = excluded.text,
                      tags_json = excluded.tags_json,
                      embedding_json = excluded.embedding_json
                    """,
                    [
                        (
                            chunk.chunk_id,
                            chunk.source_name,
                            chunk.category,
                            chunk.knowledge_tier,
                            chunk.text,
                            json.dumps(chunk.tags, ensure_ascii=False),
                            json.dumps(chunk.embedding, ensure_ascii=False)
                            if chunk.embedding is not None
                            else None,
                        )
                        for chunk in chunks
                    ],
                )

    def delete_knowledge_chunks_by_source(self, source_name: str) -> None:
        self.initialize()
        with self._lock:
            with self._get_connection() as conn:
                conn.execute(
                    "delete from knowledge_chunks where source_name = ?",
                    (source_name,),
                )

    def delete_knowledge_chunks_by_source_prefix(self, source_prefix: str) -> None:
        self.initialize()
        with self._lock:
            with self._get_connection() as conn:
                conn.execute(
                    """
                    delete from knowledge_chunks
                    where source_name = ?
                       or source_name like ? escape '\\'
                    """,
                    (source_prefix, f"{source_prefix}:%"),
                )

    def _load_tags(self, tags_json: str, chunk_id: str) -> list[str]:
        try:
            raw_tags = json.loads(tags_json)
        except json.JSONDecodeError as exc:
            raise ValueError(f"chunk {chunk_id} 的 tags_json 不是合法 JSON") from exc
        if not isinstance(raw_tags, list) or any(not isinstance(tag, str) for tag in raw_tags):
            raise ValueError(f"chunk {chunk_id} 的 tags_json 必须是 list[str]")
        return raw_tags

    def _load_embedding(self, embedding_json: str | None, chunk_id: str) -> list[float] | None:
        if embedding_json is None:
            return None
        try:
            raw_embedding = json.loads(embedding_json)
        except json.JSONDecodeError as exc:
            raise ValueError(f"chunk {chunk_id} 的 embedding_json 不是合法 JSON") from exc
        if (
            not isinstance(raw_embedding, list)
            or any(not isinstance(value, (int, float)) for value in raw_embedding)
        ):
            raise ValueError(f"chunk {chunk_id} 的 embedding_json 必须是 list[float]")
        return [float(value) for value in raw_embedding]

    def list_knowledge_chunks(self) -> list[KnowledgeChunk]:
        self.initialize()
        with self._lock:
            with self._get_connection() as conn:
                rows = conn.execute(
                    """
                    select chunk_id, source_name, category, knowledge_tier, text, tags_json, embedding_json
                    from knowledge_chunks
                    order by chunk_id asc
                    """
                ).fetchall()

        return [
            KnowledgeChunk(
                chunk_id=row[0],
                source_name=row[1],
                category=row[2],
                knowledge_tier=row[3],
                text=row[4],
                tags=self._load_tags(row[5], row[0]),
                embedding=self._load_embedding(row[6], row[0]),
            )
            for row in rows
        ]

    def get_conversation_workflow_state(
        self,
        conversation_id: str,
    ) -> ConversationWorkflowState | None:
        self.initialize()
        with self._lock:
            with self._get_connection() as conn:
                row = conn.execute(
                    """
                    select conversation_id, customer_stage, intent, should_handoff
                    from conversation_workflow_state
                    where conversation_id = ?
                    """,
                    (conversation_id,),
                ).fetchone()
        if row is None:
            return None
        return ConversationWorkflowState(
            conversation_id=row[0],
            customer_stage=row[1],
            intent=row[2],
            should_handoff=bool(row[3]),
        )

    def save_conversation_workflow_state(self, state: ConversationWorkflowState) -> None:
        self.initialize()
        with self._lock:
            with self._get_connection() as conn:
                conn.execute(
                    """
                    insert into conversation_workflow_state (
                      conversation_id, customer_stage, intent, should_handoff
                    ) values (?, ?, ?, ?)
                    on conflict(conversation_id) do update set
                      customer_stage = excluded.customer_stage,
                      intent = excluded.intent,
                      should_handoff = excluded.should_handoff
                    """,
                    (
                        state.conversation_id,
                        state.customer_stage,
                        state.intent,
                        1 if state.should_handoff else 0,
                    ),
                )

    def save_library_state(self, record: LibraryStateRecord) -> None:
        self.initialize()
        with self._lock:
            with self._get_connection() as conn:
                conn.execute(
                    """
                    insert into library_state (
                      library_type, source_name, original_filename, imported_count,
                      skipped_count, status, uploaded_at
                    ) values (?, ?, ?, ?, ?, ?, ?)
                    on conflict(library_type) do update set
                      source_name = excluded.source_name,
                      original_filename = excluded.original_filename,
                      imported_count = excluded.imported_count,
                      skipped_count = excluded.skipped_count,
                      status = excluded.status,
                      uploaded_at = excluded.uploaded_at
                    """,
                    (
                        record.library_type,
                        record.source_name,
                        record.original_filename,
                        record.imported_count,
                        record.skipped_count,
                        record.status,
                        record.uploaded_at,
                    ),
                )

    def get_library_state(self, library_type: str) -> LibraryStateRecord | None:
        self.initialize()
        with self._lock:
            with self._get_connection() as conn:
                row = conn.execute(
                    """
                    select library_type, source_name, original_filename, imported_count,
                           skipped_count, status, uploaded_at
                    from library_state
                    where library_type = ?
                    """,
                    (library_type,),
                ).fetchone()
        if row is None:
            return None
        return LibraryStateRecord(
            library_type=row[0],
            source_name=row[1],
            original_filename=row[2],
            imported_count=row[3],
            skipped_count=row[4],
            status=row[5],
            uploaded_at=row[6],
        )

    def list_library_states(self) -> list[LibraryStateRecord]:
        self.initialize()
        with self._lock:
            with self._get_connection() as conn:
                rows = conn.execute(
                    """
                    select library_type, source_name, original_filename, imported_count,
                           skipped_count, status, uploaded_at
                    from library_state
                    order by library_type asc
                    """
                ).fetchall()
        return [
            LibraryStateRecord(
                library_type=row[0],
                source_name=row[1],
                original_filename=row[2],
                imported_count=row[3],
                skipped_count=row[4],
                status=row[5],
                uploaded_at=row[6],
            )
            for row in rows
        ]

    def save_draft_audit_record(self, record: DraftAuditRecord) -> None:
        self.initialize()
        with self._lock:
            with self._get_connection() as conn:
                conn.execute(
                    """
                    insert into draft_audit_records (
                      draft_id, conversation_id, customer_message, reply_text,
                      risk_level, reason, workflow_json, used_chunk_ids_json,
                      final_status, operator_note, created_at
                    ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    on conflict(draft_id) do update set
                      conversation_id = excluded.conversation_id,
                      customer_message = excluded.customer_message,
                      reply_text = excluded.reply_text,
                      risk_level = excluded.risk_level,
                      reason = excluded.reason,
                      workflow_json = excluded.workflow_json,
                      used_chunk_ids_json = excluded.used_chunk_ids_json,
                      final_status = excluded.final_status,
                      operator_note = excluded.operator_note,
                      created_at = excluded.created_at
                    """,
                    (
                        record.draft_id,
                        record.conversation_id,
                        record.customer_message,
                        record.reply_text,
                        record.risk_level,
                        record.reason,
                        record.workflow_json,
                        record.used_chunk_ids_json,
                        record.final_status,
                        record.operator_note,
                        record.created_at,
                    ),
                )

    def list_draft_audit_records(self, *, limit: int) -> list[DraftAuditRecord]:
        self.initialize()
        with self._lock:
            with self._get_connection() as conn:
                rows = conn.execute(
                    """
                    select draft_id, conversation_id, customer_message, reply_text,
                           risk_level, reason, workflow_json, used_chunk_ids_json,
                           final_status, operator_note, created_at
                    from draft_audit_records
                    order by created_at desc, draft_id desc
                    limit ?
                    """,
                    (limit,),
                ).fetchall()
        return [
            DraftAuditRecord(
                draft_id=row[0],
                conversation_id=row[1],
                customer_message=row[2],
                reply_text=row[3],
                risk_level=row[4],
                reason=row[5],
                workflow_json=row[6],
                used_chunk_ids_json=row[7],
                final_status=row[8],
                operator_note=row[9],
                created_at=row[10],
            )
            for row in rows
        ]

    def update_draft_audit_record_feedback(
        self,
        *,
        draft_id: str,
        final_status: str,
        operator_note: str,
    ) -> bool:
        self.initialize()
        with self._lock:
            with self._get_connection() as conn:
                cursor = conn.execute(
                    """
                    update draft_audit_records
                    set final_status = ?, operator_note = ?
                    where draft_id = ?
                    """,
                    (final_status, operator_note, draft_id),
                )
        return cursor.rowcount > 0

    def replace_products(self, products: list[ProductRecord]) -> None:
        self.initialize()
        with self._lock:
            with self._get_connection() as conn:
                conn.execute("delete from products")
                self._insert_products(conn, products)

    def save_products(self, products: list[ProductRecord]) -> None:
        self.initialize()
        with self._lock:
            with self._get_connection() as conn:
                self._insert_products(conn, products)

    def _insert_products(
        self,
        conn: sqlite3.Connection,
        products: list[ProductRecord],
    ) -> None:
        conn.executemany(
            """
            insert into products (
              product_id, source_record_id, brand, model_std, sale_status,
              is_functional, has_inspection_video, has_sample_output,
              cost_price, sale_price, profit_amount,
              source_name, source_wxid, published_at,
              image_path, video_path, raw_copy, manual_review_needed
            ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            on conflict(product_id) do update set
              source_record_id = excluded.source_record_id,
              brand = excluded.brand,
              model_std = excluded.model_std,
              sale_status = excluded.sale_status,
              is_functional = excluded.is_functional,
              has_inspection_video = excluded.has_inspection_video,
              has_sample_output = excluded.has_sample_output,
              cost_price = excluded.cost_price,
              sale_price = excluded.sale_price,
              profit_amount = excluded.profit_amount,
              source_name = excluded.source_name,
              source_wxid = excluded.source_wxid,
              published_at = excluded.published_at,
              image_path = excluded.image_path,
              video_path = excluded.video_path,
              raw_copy = excluded.raw_copy,
              manual_review_needed = excluded.manual_review_needed
            """,
            [
                (
                    product.product_id,
                    product.source_record_id,
                    product.brand,
                    product.model_std,
                    product.sale_status,
                    1 if product.is_functional else 0,
                    1 if product.has_inspection_video else 0,
                    1 if product.has_sample_output else 0,
                    product.cost_price,
                    product.sale_price,
                    product.profit_amount,
                    product.source_name,
                    product.source_wxid,
                    product.published_at,
                    product.image_path,
                    product.video_path,
                    product.raw_copy,
                    1 if product.manual_review_needed else 0,
                )
                for product in products
            ],
        )

    def list_products(self) -> list[ProductRecord]:
        self.initialize()
        with self._lock:
            with self._get_connection() as conn:
                rows = conn.execute(
                    """
                    select
                      product_id, source_record_id, brand, model_std, sale_status,
                      is_functional, has_inspection_video, has_sample_output,
                      cost_price, sale_price, profit_amount,
                      source_name, source_wxid, published_at,
                      image_path, video_path, raw_copy, manual_review_needed
                    from products
                    order by published_at asc, product_id asc
                    """
                ).fetchall()

        return [
            ProductRecord(
                product_id=row[0],
                source_record_id=row[1],
                brand=row[2],
                model_std=row[3],
                sale_status=row[4],
                is_functional=bool(row[5]),
                has_inspection_video=bool(row[6]),
                has_sample_output=bool(row[7]),
                cost_price=row[8],
                sale_price=row[9],
                profit_amount=row[10],
                source_name=row[11],
                source_wxid=row[12],
                published_at=row[13],
                image_path=row[14],
                video_path=row[15],
                raw_copy=row[16],
                manual_review_needed=bool(row[17]),
            )
            for row in rows
        ]
