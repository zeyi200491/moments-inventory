from __future__ import annotations

from collections import defaultdict
from datetime import datetime
import json
from typing import Annotated, Protocol

from fastapi import APIRouter, Depends, File, Form, Header, HTTPException, Query, UploadFile, status
from pydantic import BaseModel, Field

from moments_inventory.ai_kefu.audit import DraftAuditRecord
from moments_inventory.ai_kefu.chat_sync import ChatSessionState
from moments_inventory.ai_kefu.indexing import split_document_to_chunks
from moments_inventory.ai_kefu.knowledge_policy import classify_knowledge_tier
from moments_inventory.ai_kefu.library_ingestion import ingest_library_bytes
from moments_inventory.ai_kefu.models import (
    KnowledgeChunk,
    KnowledgeTier,
    LibraryStateRecord,
    LibraryType,
    ProductRecord,
    VALID_KNOWLEDGE_TIERS,
)
from moments_inventory.ai_kefu.providers import EmbeddingProvider
from moments_inventory.ai_kefu.risk import RiskDecision, RiskLevel, RuleBasedRiskClassifier
from moments_inventory.ai_kefu.service import DraftResult
from moments_inventory.ai_kefu.settings import RetrievalSettings
from moments_inventory.ai_kefu.structured_imports import (
    SUPPORTED_STRUCTURED_TIERS,
    build_structured_import_content,
)


KnowledgeTag = Annotated[str, Field(min_length=1, max_length=32)]


class DraftService(Protocol):
    def generate_draft(
        self,
        *,
        conversation_id: str,
        customer_message: str,
        risk_decision: RiskDecision,
    ) -> DraftResult:
        ...


class KnowledgeRepository(Protocol):
    def list_knowledge_chunks(self) -> list[KnowledgeChunk]:
        ...

    def save_knowledge_chunks(self, chunks: list[KnowledgeChunk]) -> None:
        ...

    def delete_knowledge_chunks_by_source(self, source_name: str) -> None:
        ...

    def delete_knowledge_chunks_by_source_prefix(self, source_prefix: str) -> None:
        ...

    def replace_products(self, products: list[ProductRecord]) -> None:
        ...

    def save_library_state(self, record: LibraryStateRecord) -> None:
        ...

    def get_library_state(self, library_type: str) -> LibraryStateRecord | None:
        ...

    def list_library_states(self) -> list[LibraryStateRecord]:
        ...

    def apply_library_upload(
        self,
        *,
        source_name: str,
        knowledge_chunks: list[KnowledgeChunk],
        product_records: list[ProductRecord],
        library_state: LibraryStateRecord,
    ) -> None:
        ...

    def list_draft_audit_records(self, *, limit: int) -> list[DraftAuditRecord]:
        ...

    def update_draft_audit_record_feedback(
        self,
        *,
        draft_id: str,
        final_status: str,
        operator_note: str,
    ) -> bool:
        ...


class ChatSyncBridge(Protocol):
    def list_sessions(self) -> list[ChatSessionState]:
        ...

    def get_session(self, session_id: str) -> ChatSessionState | None:
        ...

    def set_current_session(self, session_id: str, *, auto_generate: bool) -> ChatSessionState:
        ...


class HealthResponse(BaseModel):
    status: str


class DraftRequest(BaseModel):
    conversation_id: Annotated[str, Field(min_length=1, max_length=128)]
    customer_message: Annotated[str, Field(min_length=1, max_length=5000)]


class UsedKnowledgeResponse(BaseModel):
    chunk_id: str
    source_name: str
    category: str
    knowledge_tier: str
    text: str
    tags: list[str] = Field(default_factory=list)

    @classmethod
    def from_chunk(cls, chunk: KnowledgeChunk) -> "UsedKnowledgeResponse":
        return cls(
            chunk_id=chunk.chunk_id,
            source_name=chunk.source_name,
            category=chunk.category,
            knowledge_tier=classify_knowledge_tier(chunk),
            text=chunk.text,
            tags=list(chunk.tags),
        )


class DraftResponse(BaseModel):
    reply_text: str
    risk_level: RiskLevel
    reason: str
    customer_stage: str
    intent: str
    should_handoff: bool
    reply_type: str
    required_data: list[str] = Field(default_factory=list)
    used_knowledge: list[UsedKnowledgeResponse] = Field(default_factory=list)

    @classmethod
    def from_result(cls, result: DraftResult) -> "DraftResponse":
        return cls(
            reply_text=result.reply_text,
            risk_level=result.risk_level,
            reason=result.reason,
            customer_stage=result.analysis.customer_stage,
            intent=result.analysis.intent,
            should_handoff=result.analysis.should_handoff,
            reply_type=result.analysis.reply_type,
            required_data=list(result.analysis.required_data),
            used_knowledge=[
                UsedKnowledgeResponse.from_chunk(chunk)
                for chunk in result.used_knowledge
            ],
        )


class DraftHistoryItemResponse(BaseModel):
    draft_id: str
    conversation_id: str
    customer_message: str
    reply_text: str
    risk_level: RiskLevel
    reason: str
    workflow: dict[str, object] = Field(default_factory=dict)
    used_chunk_ids: list[str] = Field(default_factory=list)
    final_status: str
    operator_note: str
    created_at: str

    @classmethod
    def from_record(cls, record: DraftAuditRecord) -> "DraftHistoryItemResponse":
        workflow = json.loads(record.workflow_json)
        used_chunk_ids = json.loads(record.used_chunk_ids_json)
        return cls(
            draft_id=record.draft_id,
            conversation_id=record.conversation_id,
            customer_message=record.customer_message,
            reply_text=record.reply_text,
            risk_level=record.risk_level,
            reason=record.reason,
            workflow=workflow if isinstance(workflow, dict) else {},
            used_chunk_ids=used_chunk_ids if isinstance(used_chunk_ids, list) else [],
            final_status=record.final_status,
            operator_note=record.operator_note,
            created_at=record.created_at,
        )


class DraftFeedbackRequest(BaseModel):
    draft_id: Annotated[str, Field(min_length=1, max_length=128)]
    final_status: Annotated[str, Field(min_length=1, max_length=32)]
    operator_note: Annotated[str, Field(max_length=1000)] = ""


class DraftFeedbackResponse(BaseModel):
    ok: bool


class KnowledgeImportRequest(BaseModel):
    source_name: Annotated[str, Field(min_length=1, max_length=128)]
    category: Annotated[str, Field(min_length=1, max_length=64)]
    knowledge_tier: KnowledgeTier | None = None
    content: Annotated[str, Field(max_length=50000)] = ""
    structured_fields: dict[str, str] = Field(default_factory=dict)
    tags: Annotated[list[KnowledgeTag], Field(default_factory=list, max_length=20)]


class KnowledgeImportResponse(BaseModel):
    source_name: str
    category: str
    knowledge_tier: str
    chunk_count: int
    tags: list[str] = Field(default_factory=list)


class KnowledgeSourceSummaryResponse(BaseModel):
    source_name: str
    category: str
    knowledge_tier: str
    chunk_count: int
    tags: list[str] = Field(default_factory=list)


class LibraryStateResponse(BaseModel):
    library_type: LibraryType
    source_name: str
    original_filename: str
    imported_count: int
    skipped_count: int
    status: str
    uploaded_at: str

    @classmethod
    def from_record(cls, record: LibraryStateRecord) -> "LibraryStateResponse":
        return cls(
            library_type=record.library_type,
            source_name=record.source_name,
            original_filename=record.original_filename,
            imported_count=record.imported_count,
            skipped_count=record.skipped_count,
            status=record.status,
            uploaded_at=record.uploaded_at,
        )


class LibraryUploadResponse(LibraryStateResponse):
    replaced: bool
    message: str


class ChatSyncSessionResponse(BaseModel):
    sessionId: str
    username: str
    displayName: str
    sessionType: str
    lastTimestamp: int
    unreadCount: int
    draftBuffer: str
    autoGenerate: bool
    isCurrent: bool
    lastMessageTimestamp: int

    @classmethod
    def from_state(cls, state: ChatSessionState) -> "ChatSyncSessionResponse":
        return cls(
            sessionId=state.session_id,
            username=state.username,
            displayName=state.display_name,
            sessionType=state.session_type,
            lastTimestamp=state.last_timestamp,
            unreadCount=state.unread_count,
            draftBuffer=state.draft_buffer,
            autoGenerate=state.auto_generate,
            isCurrent=state.is_current,
            lastMessageTimestamp=state.last_message_timestamp,
        )


class CurrentChatSessionRequest(BaseModel):
    sessionId: Annotated[str, Field(min_length=1, max_length=128)]
    autoGenerate: bool = False


def _normalize_tags(tags: list[str]) -> list[str]:
    normalized: list[str] = []
    seen: set[str] = set()
    for raw_tag in tags:
        tag = raw_tag.strip()
        if not tag or tag in seen:
            continue
        seen.add(tag)
        normalized.append(tag)
    return normalized


def _resolve_knowledge_tier(
    *,
    source_name: str,
    category: str,
    knowledge_tier: KnowledgeTier | None,
    tags: list[str],
) -> KnowledgeTier:
    if knowledge_tier is not None:
        return knowledge_tier
    probe = KnowledgeChunk(
        chunk_id="tier-probe",
        source_name=source_name,
        category=category,
        knowledge_tier=None,
        text="",
        tags=list(tags),
    )
    resolved = classify_knowledge_tier(probe)
    if resolved not in VALID_KNOWLEDGE_TIERS:
        return "faq"
    return resolved


def _build_knowledge_summaries(
    knowledge_chunks: list[KnowledgeChunk],
) -> list[KnowledgeSourceSummaryResponse]:
    grouped: dict[tuple[str, str], list[KnowledgeChunk]] = defaultdict(list)
    for chunk in knowledge_chunks:
        grouped[(chunk.source_name, chunk.category)].append(chunk)

    summaries: list[KnowledgeSourceSummaryResponse] = []
    for (source_name, category), chunks in sorted(grouped.items(), key=lambda item: item[0]):
        tags: list[str] = []
        seen_tags: set[str] = set()
        for chunk in chunks:
            for tag in chunk.tags:
                if tag in seen_tags:
                    continue
                seen_tags.add(tag)
                tags.append(tag)
        summaries.append(
            KnowledgeSourceSummaryResponse(
                source_name=source_name,
                category=category,
                knowledge_tier=classify_knowledge_tier(chunks[0]),
                chunk_count=len(chunks),
                tags=tags,
            )
        )
    return summaries


def _build_library_source_name(library_type: LibraryType) -> str:
    return f"library:{library_type}"


def _apply_embeddings(
    chunks: list[KnowledgeChunk],
    embedding_provider: EmbeddingProvider | None,
) -> None:
    if embedding_provider is None or not chunks:
        return
    try:
        embeddings = embedding_provider.embed_texts([chunk.text for chunk in chunks])
    except Exception:
        return
    if len(embeddings) != len(chunks):
        return
    for chunk, embedding in zip(chunks, embeddings, strict=True):
        chunk.embedding = embedding


def create_router(
    service: DraftService,
    repository: KnowledgeRepository,
    retrieval_settings: RetrievalSettings,
    api_key: str | None = None,
    chat_sync_bridge: ChatSyncBridge | None = None,
    embedding_provider: EmbeddingProvider | None = None,
) -> APIRouter:
    router = APIRouter(prefix="/api")
    classifier = RuleBasedRiskClassifier()

    def verify_api_key(
        x_api_key: Annotated[str | None, Header(alias="X-API-Key")] = None,
    ) -> None:
        if api_key is None:
            return
        if x_api_key != api_key:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="缺少有效的 API Key",
            )

    @router.get("/health", response_model=HealthResponse)
    def health() -> HealthResponse:
        return HealthResponse(status="ok")

    protected_dependencies = [Depends(verify_api_key)] if api_key is not None else []

    def require_chat_sync_bridge() -> ChatSyncBridge:
        if chat_sync_bridge is None:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="chat sync bridge is not enabled",
            )
        return chat_sync_bridge

    def get_chat_sync_session_or_404(session_id: str) -> ChatSessionState:
        bridge = require_chat_sync_bridge()
        session = bridge.get_session(session_id)
        if session is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="chat sync session not found",
            )
        return session

    @router.post("/drafts", response_model=DraftResponse, dependencies=protected_dependencies)
    def generate_draft(payload: DraftRequest) -> DraftResponse:
        result = service.generate_draft(
            conversation_id=payload.conversation_id,
            customer_message=payload.customer_message,
            risk_decision=classifier.classify(payload.customer_message),
        )
        return DraftResponse.from_result(result)

    @router.get(
        "/drafts/history",
        response_model=list[DraftHistoryItemResponse],
        dependencies=protected_dependencies,
    )
    def list_draft_history(
        limit: Annotated[int, Query(ge=1, le=200)] = 50,
    ) -> list[DraftHistoryItemResponse]:
        return [
            DraftHistoryItemResponse.from_record(record)
            for record in repository.list_draft_audit_records(limit=limit)
        ]

    @router.post(
        "/drafts/feedback",
        response_model=DraftFeedbackResponse,
        dependencies=protected_dependencies,
    )
    def submit_draft_feedback(payload: DraftFeedbackRequest) -> DraftFeedbackResponse:
        updated = repository.update_draft_audit_record_feedback(
            draft_id=payload.draft_id,
            final_status=payload.final_status.strip(),
            operator_note=payload.operator_note.strip(),
        )
        if not updated:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="draft audit record not found",
            )
        return DraftFeedbackResponse(ok=True)

    @router.get(
        "/knowledge/libraries",
        response_model=list[LibraryStateResponse],
        dependencies=protected_dependencies,
    )
    def list_knowledge_libraries() -> list[LibraryStateResponse]:
        return [
            LibraryStateResponse.from_record(record)
            for record in repository.list_library_states()
        ]

    @router.get(
        "/knowledge/sources",
        response_model=list[KnowledgeSourceSummaryResponse],
        dependencies=protected_dependencies,
    )
    def list_knowledge_sources() -> list[KnowledgeSourceSummaryResponse]:
        return _build_knowledge_summaries(repository.list_knowledge_chunks())

    @router.post(
        "/knowledge/imports",
        response_model=KnowledgeImportResponse,
        dependencies=protected_dependencies,
    )
    def import_knowledge(payload: KnowledgeImportRequest) -> KnowledgeImportResponse:
        source_name = payload.source_name.strip()
        category = payload.category.strip()
        content = payload.content.strip()
        if not source_name:
            raise HTTPException(status_code=400, detail="知识来源不能为空")
        if not category:
            raise HTTPException(status_code=400, detail="知识分类不能为空")
        tags = _normalize_tags(payload.tags)
        resolved_tier = _resolve_knowledge_tier(
            source_name=source_name,
            category=category,
            knowledge_tier=payload.knowledge_tier,
            tags=tags,
        )
        if not content and payload.structured_fields:
            if resolved_tier not in SUPPORTED_STRUCTURED_TIERS:
                raise HTTPException(status_code=400, detail="当前知识层级不支持结构化导入")
            structured_content, structured_tags = build_structured_import_content(
                knowledge_tier=resolved_tier,
                fields=payload.structured_fields,
            )
            content = structured_content.strip()
            tags = _normalize_tags([*tags, *structured_tags])

        if not content:
            raise HTTPException(status_code=400, detail="知识内容不能为空")

        chunks = split_document_to_chunks(
            source_name=source_name,
            category=category,
            text=content,
            chunk_size=retrieval_settings.chunk_size,
            chunk_overlap=retrieval_settings.chunk_overlap,
            knowledge_tier=resolved_tier,
        )
        for chunk in chunks:
            chunk.tags = list(tags)
        _apply_embeddings(chunks, embedding_provider)

        repository.delete_knowledge_chunks_by_source(source_name)
        repository.save_knowledge_chunks(chunks)
        return KnowledgeImportResponse(
            source_name=source_name,
            category=category,
            knowledge_tier=resolved_tier,
            chunk_count=len(chunks),
            tags=tags,
        )

    @router.post(
        "/knowledge/uploads",
        response_model=LibraryUploadResponse,
        dependencies=protected_dependencies,
    )
    def upload_knowledge_library(
        library_type: Annotated[LibraryType, Form(...)],
        file: Annotated[UploadFile, File(...)],
    ) -> LibraryUploadResponse:
        filename = file.filename or "upload.bin"
        payload = file.file.read()
        existing_record = repository.get_library_state(library_type)
        uploaded_at = datetime.now().astimezone().isoformat(timespec="seconds")
        source_name = _build_library_source_name(library_type)

        try:
            result = ingest_library_bytes(
                library_type=library_type,
                filename=filename,
                payload=payload,
                chunk_size=retrieval_settings.chunk_size,
                chunk_overlap=retrieval_settings.chunk_overlap,
            )
        except NotImplementedError as exc:
            raise HTTPException(
                status_code=status.HTTP_501_NOT_IMPLEMENTED,
                detail=str(exc),
            ) from exc
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=str(exc),
            ) from exc

        record = LibraryStateRecord(
            library_type=library_type,
            source_name=source_name,
            original_filename=filename,
            imported_count=result.imported_count,
            skipped_count=result.skipped_count,
            status="active",
            uploaded_at=uploaded_at,
        )
        _apply_embeddings(result.knowledge_chunks, embedding_provider)
        repository.apply_library_upload(
            source_name=source_name,
            knowledge_chunks=result.knowledge_chunks,
            product_records=result.product_records,
            library_state=record,
        )
        return LibraryUploadResponse(
            library_type=record.library_type,
            source_name=record.source_name,
            original_filename=record.original_filename,
            imported_count=record.imported_count,
            skipped_count=record.skipped_count,
            status=record.status,
            uploaded_at=record.uploaded_at,
            replaced=existing_record is not None,
            message="上传成功",
        )

    @router.get(
        "/chat-sync/sessions",
        response_model=list[ChatSyncSessionResponse],
        dependencies=protected_dependencies,
    )
    def list_chat_sync_sessions() -> list[ChatSyncSessionResponse]:
        if chat_sync_bridge is None:
            return []
        return [ChatSyncSessionResponse.from_state(session) for session in chat_sync_bridge.list_sessions()]

    @router.get(
        "/chat-sync/sessions/{session_id}",
        response_model=ChatSyncSessionResponse,
        dependencies=protected_dependencies,
    )
    def get_chat_sync_session(session_id: str) -> ChatSyncSessionResponse:
        return ChatSyncSessionResponse.from_state(get_chat_sync_session_or_404(session_id))

    @router.post(
        "/chat-sync/current-session",
        response_model=ChatSyncSessionResponse,
        dependencies=protected_dependencies,
    )
    def set_current_chat_sync_session(payload: CurrentChatSessionRequest) -> ChatSyncSessionResponse:
        bridge = require_chat_sync_bridge()
        try:
            session = bridge.set_current_session(payload.sessionId, auto_generate=payload.autoGenerate)
        except KeyError as exc:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="chat sync session not found",
            ) from exc
        return ChatSyncSessionResponse.from_state(session)

    @router.post(
        "/chat-sync/sessions/{session_id}/refresh",
        response_model=ChatSyncSessionResponse,
        dependencies=protected_dependencies,
    )
    def refresh_chat_sync_session(session_id: str) -> ChatSyncSessionResponse:
        return ChatSyncSessionResponse.from_state(get_chat_sync_session_or_404(session_id))

    return router
