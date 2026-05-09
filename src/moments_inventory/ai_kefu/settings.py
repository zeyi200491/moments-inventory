from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml


class AIKefuSettingsError(ValueError):
    pass


@dataclass(slots=True)
class RetrievalSettings:
    chunk_size: int
    chunk_overlap: int


@dataclass(slots=True)
class ChatProviderOptions:
    api_base: str
    api_key_env: str
    timeout_seconds: int = 30


@dataclass(slots=True)
class ApiAuthSettings:
    api_key_env: str


@dataclass(slots=True)
class ChatSyncSettings:
    enabled: bool = False
    weflow_base_url: str = ""
    weflow_access_token_env: str = "WEFLOW_ACCESS_TOKEN"
    session_poll_limit: int = 100
    merge_window_seconds: int = 8


@dataclass(slots=True)
class AICustomerServiceSettings:
    workspace_dir: str
    database_path: str
    embedding_provider: str
    embedding_model: str
    chat_provider: str
    chat_model: str
    chat_provider_options: ChatProviderOptions | None
    retrieval: RetrievalSettings
    api_auth: ApiAuthSettings | None = None
    chat_sync: ChatSyncSettings | None = None


def _expect_mapping(value: object, path: str) -> dict[str, object]:
    if not isinstance(value, dict):
        raise AIKefuSettingsError(f"{path} 必须是对象")
    return value


def _expect_non_empty_string(value: object, path: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise AIKefuSettingsError(f"{path} 必须是非空字符串")
    return value.strip()


def _expect_positive_int(value: object, path: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise AIKefuSettingsError(f"{path} 必须是正整数")
    return value


def _expect_bool(value: object, path: str) -> bool:
    if not isinstance(value, bool):
        raise AIKefuSettingsError(f"{path} 必须是布尔值")
    return value


def _expect_non_negative_int(value: object, path: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise AIKefuSettingsError(f"{path} 必须是大于等于 0 的整数")
    return value


def _resolve_path(base_dir: Path, raw_path: str) -> str:
    path = Path(raw_path)
    if path.is_absolute():
        return str(path)
    return str((base_dir / path).resolve())


def _load_chat_provider_options(
    settings_raw: dict[str, object],
    chat_provider: str,
) -> ChatProviderOptions | None:
    raw_options = settings_raw.get("chat_provider_options")
    if chat_provider != "openai_compatible":
        if raw_options is None:
            return None
        options_raw = _expect_mapping(raw_options, "chat_provider_options")
        return ChatProviderOptions(
            api_base=_expect_non_empty_string(
                options_raw.get("api_base"),
                "chat_provider_options.api_base",
            ),
            api_key_env=_expect_non_empty_string(
                options_raw.get("api_key_env"),
                "chat_provider_options.api_key_env",
            ),
            timeout_seconds=_expect_positive_int(
                options_raw.get("timeout_seconds", 30),
                "chat_provider_options.timeout_seconds",
            ),
        )

    options_raw = _expect_mapping(raw_options, "chat_provider_options")
    return ChatProviderOptions(
        api_base=_expect_non_empty_string(
            options_raw.get("api_base"),
            "chat_provider_options.api_base",
        ),
        api_key_env=_expect_non_empty_string(
            options_raw.get("api_key_env"),
            "chat_provider_options.api_key_env",
        ),
        timeout_seconds=_expect_positive_int(
            options_raw.get("timeout_seconds", 30),
            "chat_provider_options.timeout_seconds",
        ),
    )


def _load_api_auth(settings_raw: dict[str, object]) -> ApiAuthSettings | None:
    raw_auth = settings_raw.get("api_auth")
    if raw_auth is None:
        return None
    auth_raw = _expect_mapping(raw_auth, "api_auth")
    return ApiAuthSettings(
        api_key_env=_expect_non_empty_string(
            auth_raw.get("api_key_env"),
            "api_auth.api_key_env",
        )
    )


def _load_chat_sync(settings_raw: dict[str, object]) -> ChatSyncSettings | None:
    raw_chat_sync = settings_raw.get("chat_sync")
    if raw_chat_sync is None:
        return None
    chat_sync_raw = _expect_mapping(raw_chat_sync, "chat_sync")
    enabled = _expect_bool(chat_sync_raw.get("enabled", False), "chat_sync.enabled")
    return ChatSyncSettings(
        enabled=enabled,
        weflow_base_url=(
            _expect_non_empty_string(
                chat_sync_raw.get("weflow_base_url", ""),
                "chat_sync.weflow_base_url",
            )
            if enabled
            else str(chat_sync_raw.get("weflow_base_url", "") or "").strip()
        ),
        weflow_access_token_env=_expect_non_empty_string(
            chat_sync_raw.get("weflow_access_token_env", "WEFLOW_ACCESS_TOKEN"),
            "chat_sync.weflow_access_token_env",
        ),
        session_poll_limit=_expect_positive_int(
            chat_sync_raw.get("session_poll_limit", 100),
            "chat_sync.session_poll_limit",
        ),
        merge_window_seconds=_expect_positive_int(
            chat_sync_raw.get("merge_window_seconds", 8),
            "chat_sync.merge_window_seconds",
        ),
    )


def load_ai_kefu_settings(path: str | Path) -> AICustomerServiceSettings:
    config_path = Path(path)
    raw = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    settings_raw = _expect_mapping(raw, "<root>")
    retrieval_raw = _expect_mapping(settings_raw.get("retrieval"), "<root>.retrieval")
    base_dir = config_path.parent.resolve()
    chunk_size = _expect_positive_int(
        retrieval_raw.get("chunk_size"),
        "retrieval.chunk_size",
    )
    chunk_overlap = _expect_non_negative_int(
        retrieval_raw.get("chunk_overlap"),
        "retrieval.chunk_overlap",
    )
    if chunk_overlap >= chunk_size:
        raise AIKefuSettingsError("retrieval.chunk_overlap 必须小于 retrieval.chunk_size")

    chat_provider = _expect_non_empty_string(
        settings_raw.get("chat_provider"),
        "chat_provider",
    )

    return AICustomerServiceSettings(
        workspace_dir=_resolve_path(
            base_dir,
            _expect_non_empty_string(settings_raw.get("workspace_dir"), "workspace_dir"),
        ),
        database_path=_resolve_path(
            base_dir,
            _expect_non_empty_string(settings_raw.get("database_path"), "database_path"),
        ),
        embedding_provider=_expect_non_empty_string(
            settings_raw.get("embedding_provider"),
            "embedding_provider",
        ),
        embedding_model=_expect_non_empty_string(
            settings_raw.get("embedding_model", "text-embedding-3-small"),
            "embedding_model",
        ),
        chat_provider=chat_provider,
        chat_model=_expect_non_empty_string(
            settings_raw.get("chat_model"),
            "chat_model",
        ),
        chat_provider_options=_load_chat_provider_options(settings_raw, chat_provider),
        retrieval=RetrievalSettings(
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
        ),
        api_auth=_load_api_auth(settings_raw),
        chat_sync=_load_chat_sync(settings_raw),
    )
