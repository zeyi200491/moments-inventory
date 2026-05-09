from pathlib import Path

import pytest
import yaml

from moments_inventory.ai_kefu.models import ConversationDraft, KnowledgeChunk
from moments_inventory.ai_kefu.settings import AIKefuSettingsError, load_ai_kefu_settings


def _write_settings_file(tmp_path: Path, payload: dict[str, object]) -> Path:
    config_file = tmp_path / "ai_kefu.yaml"
    config_file.write_text(
        yaml.safe_dump(payload, allow_unicode=True),
        encoding="utf-8",
    )
    return config_file


def _build_base_settings() -> dict[str, object]:
    return {
        "workspace_dir": "./workspace",
        "database_path": "./data/ai-kefu.db",
        "embedding_provider": "openai",
        "chat_provider": "openai_compatible",
        "chat_model": "gpt-4.1-mini",
        "chat_provider_options": {
            "api_base": "https://example.com/v1",
            "api_key_env": "AI_KEFU_OPENAI_API_KEY",
            "timeout_seconds": 45,
        },
        "retrieval": {
            "chunk_size": 600,
            "chunk_overlap": 120,
        },
    }


def test_load_ai_kefu_settings_resolves_relative_paths_and_retrieval(tmp_path: Path):
    payload = _build_base_settings()
    config_file = _write_settings_file(tmp_path, payload)

    settings = load_ai_kefu_settings(config_file)

    assert settings.workspace_dir == str((tmp_path / "workspace").resolve())
    assert settings.database_path == str((tmp_path / "data" / "ai-kefu.db").resolve())
    assert settings.chat_provider_options is not None
    assert settings.chat_provider_options.timeout_seconds == 45
    assert settings.retrieval.chunk_size == 600
    assert settings.retrieval.chunk_overlap == 120


def test_load_ai_kefu_settings_allows_disabled_chat_sync_without_base_url(tmp_path: Path):
    payload = _build_base_settings()
    payload["chat_sync"] = {
        "enabled": False,
        "weflow_access_token_env": "WEFLOW_ACCESS_TOKEN",
        "session_poll_limit": 100,
        "merge_window_seconds": 8,
    }
    config_file = _write_settings_file(tmp_path, payload)

    settings = load_ai_kefu_settings(config_file)

    assert settings.chat_sync is not None
    assert settings.chat_sync.enabled is False
    assert settings.chat_sync.weflow_base_url == ""


def test_load_ai_kefu_settings_rejects_invalid_bool_with_readable_message(tmp_path: Path):
    payload = _build_base_settings()
    payload["chat_sync"] = {
        "enabled": "yes",
        "weflow_base_url": "http://127.0.0.1:5031",
    }
    config_file = _write_settings_file(tmp_path, payload)

    with pytest.raises(AIKefuSettingsError, match="必须是布尔值"):
        load_ai_kefu_settings(config_file)


def test_load_ai_kefu_settings_rejects_overlap_not_smaller_than_chunk_size(tmp_path: Path):
    payload = _build_base_settings()
    payload["retrieval"] = {
        "chunk_size": 600,
        "chunk_overlap": 600,
    }
    config_file = _write_settings_file(tmp_path, payload)

    with pytest.raises(AIKefuSettingsError, match="retrieval.chunk_overlap"):
        load_ai_kefu_settings(config_file)


def test_conversation_draft_uses_independent_default_used_chunk_ids():
    first = ConversationDraft(
        conversation_id="conv-001",
        customer_message="在吗",
        final_reply="在的",
    )
    second = ConversationDraft(
        conversation_id="conv-002",
        customer_message="你好",
        final_reply="你好",
    )

    first.used_chunk_ids.append("chunk-001")

    assert first.risk_level == "L1"
    assert first.used_chunk_ids == ["chunk-001"]
    assert second.used_chunk_ids == []


def test_knowledge_chunk_keeps_category_and_tags():
    chunk = KnowledgeChunk(
        chunk_id="chunk-001",
        source_name="faq.txt",
        category="售后",
        text="支持七天内问题排查。",
        tags=["售后", "时效"],
    )

    assert chunk.category == "售后"
    assert chunk.tags == ["售后", "时效"]
