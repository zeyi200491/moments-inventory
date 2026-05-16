from __future__ import annotations

import os
from pathlib import Path
from types import SimpleNamespace

from fastapi import FastAPI

from moments_inventory.ai_kefu.api import ChatSyncBridge as ChatSyncBridgeProtocol
from moments_inventory.ai_kefu.api import DraftService, KnowledgeRepository, create_router
from moments_inventory.ai_kefu.chat_sync import ChatSyncBridge
from moments_inventory.ai_kefu.providers import (
    EmbeddingProvider,
    OpenAICompatibleChatProvider,
    OpenAICompatibleEmbeddingProvider,
)
from moments_inventory.ai_kefu.service import KefuDraftService
from moments_inventory.ai_kefu.settings import (
    AIKefuSettingsError,
    AICustomerServiceSettings,
    ApiAuthSettings,
    RetrievalSettings,
    load_ai_kefu_settings,
)
from moments_inventory.ai_kefu.storage import SQLiteKefuRepository
from moments_inventory.weflow_client import WeFlowClient


class EchoChatProvider:
    def create_reply(self, system_prompt: str, user_prompt: str) -> str:
        return "我先帮您记下需求，稍后给您更准确的回复。"


def _load_api_key(env_name: str) -> str:
    api_key = os.environ.get(env_name, "").strip()
    if not api_key:
        raise AIKefuSettingsError(f"环境变量 {env_name} 未设置，无法初始化 OpenAI 兼容提供方")
    return api_key


def _load_optional_api_key(env_name: str) -> str | None:
    api_key = os.environ.get(env_name, "").strip()
    return api_key or None


def _load_optional_backend_api_key(api_auth: ApiAuthSettings | None) -> str | None:
    if api_auth is None:
        return None
    api_key = os.environ.get(api_auth.api_key_env, "").strip()
    if not api_key:
        raise AIKefuSettingsError(f"环境变量 {api_auth.api_key_env} 未设置，无法启用 API Key 保护")
    return api_key


def _build_chat_sync_bridge(settings: AICustomerServiceSettings) -> ChatSyncBridge | None:
    if settings.chat_sync is None or not settings.chat_sync.enabled:
        return None

    access_token = os.environ.get(settings.chat_sync.weflow_access_token_env, "").strip() or None
    client_settings = SimpleNamespace(
        weflow=SimpleNamespace(
            base_url=settings.chat_sync.weflow_base_url,
            timeout_seconds=20,
            access_token=access_token,
        )
    )
    client = WeFlowClient(client_settings)
    return ChatSyncBridge(
        merge_window_seconds=settings.chat_sync.merge_window_seconds,
        client=client,
        session_poll_limit=settings.chat_sync.session_poll_limit,
        message_poll_limit=settings.chat_sync.session_poll_limit,
    )


def _build_embedding_provider(settings: AICustomerServiceSettings) -> EmbeddingProvider | None:
    if settings.embedding_provider != "openai":
        return None
    if settings.chat_provider_options is None:
        return None

    api_key = _load_optional_api_key(settings.chat_provider_options.api_key_env)
    if api_key is None:
        return None

    return OpenAICompatibleEmbeddingProvider(
        api_base=settings.chat_provider_options.api_base,
        api_key=api_key,
        model=settings.embedding_model,
        timeout_seconds=settings.chat_provider_options.timeout_seconds,
    )


def build_default_service(config_path: str | Path | None = None) -> DraftService:
    service, _, _, _, _, _ = build_default_runtime(config_path)
    return service


def build_default_runtime(
    config_path: str | Path | None = None,
) -> tuple[
    DraftService,
    KnowledgeRepository,
    RetrievalSettings,
    str | None,
    ChatSyncBridge | None,
    EmbeddingProvider | None,
]:
    resolved_path = Path(config_path or "config/ai_kefu.yaml")
    settings = load_ai_kefu_settings(resolved_path)
    repository = SQLiteKefuRepository(settings.database_path)
    repository.initialize()

    if settings.chat_provider != "openai_compatible" or settings.chat_provider_options is None:
        raise AIKefuSettingsError(
            f"当前仅支持 openai_compatible chat_provider，实际为 {settings.chat_provider}"
        )

    chat_provider = OpenAICompatibleChatProvider(
        api_base=settings.chat_provider_options.api_base,
        api_key=_load_api_key(settings.chat_provider_options.api_key_env),
        model=settings.chat_model,
        timeout_seconds=settings.chat_provider_options.timeout_seconds,
    )
    embedding_provider = _build_embedding_provider(settings)
    service = KefuDraftService(
        repository=repository,
        chat_provider=chat_provider,
        embedding_provider=embedding_provider,
    )
    backend_api_key = _load_optional_backend_api_key(settings.api_auth)
    chat_sync_bridge = _build_chat_sync_bridge(settings)
    return (
        service,
        repository,
        settings.retrieval,
        backend_api_key,
        chat_sync_bridge,
        embedding_provider,
    )


def create_app(
    config_path: str | Path | None = None,
    service: DraftService | None = None,
    repository: KnowledgeRepository | None = None,
    retrieval_settings: RetrievalSettings | None = None,
    api_key: str | None = None,
    chat_sync_bridge: ChatSyncBridgeProtocol | None = None,
    embedding_provider: EmbeddingProvider | None = None,
) -> FastAPI:
    has_all_runtime_dependencies = (
        service is not None and repository is not None and retrieval_settings is not None
    )
    has_service_only = (
        service is not None and repository is None and retrieval_settings is None
    )
    has_no_runtime_dependencies = (
        service is None and repository is None and retrieval_settings is None
    )

    if has_all_runtime_dependencies:
        pass
    elif has_service_only:
        repository = SQLiteKefuRepository(":memory:")
        repository.initialize()
        retrieval_settings = RetrievalSettings(
            chunk_size=600,
            chunk_overlap=120,
        )
    elif config_path is not None and has_no_runtime_dependencies:
        (
            service,
            repository,
            retrieval_settings,
            api_key,
            chat_sync_bridge,
            embedding_provider,
        ) = build_default_runtime(config_path)
    elif has_no_runtime_dependencies:
        repository = SQLiteKefuRepository(":memory:")
        repository.initialize()
        service = KefuDraftService(
            repository=repository,
            chat_provider=EchoChatProvider(),
            embedding_provider=embedding_provider,
        )
        retrieval_settings = RetrievalSettings(
            chunk_size=600,
            chunk_overlap=120,
        )
    else:
        raise ValueError("service、repository、retrieval_settings 必须同时提供，或全部省略")

    app = FastAPI(title="AI Kefu Workbench")
    app.include_router(
        create_router(
            service,
            repository,
            retrieval_settings,
            api_key=api_key,
            chat_sync_bridge=chat_sync_bridge,
            embedding_provider=embedding_provider,
        )
    )
    return app


def create_app_from_env() -> FastAPI:
    config_path = os.environ.get("MOMENTS_AI_KEFU_CONFIG_PATH", "").strip() or None
    return create_app(config_path=config_path)
