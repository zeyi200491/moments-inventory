from __future__ import annotations

import pytest

from moments_inventory.config import PathSettings, RuleSettings, Settings, TaskSettings, WeFlowSettings
from moments_inventory.weflow_client import WeFlowClient


def _build_settings() -> Settings:
    return Settings(
        weflow=WeFlowSettings(
            base_url="http://127.0.0.1:5031",
            timeout_seconds=20,
            access_token="demo-token",
        ),
        task=TaskSettings(),
        targets=[],
        rules=RuleSettings(),
        paths=PathSettings(sqlite_db="inventory.db", model_dict="models.txt"),
        model_keywords=[],
    )


def test_fetch_sessions_returns_private_sessions(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = _build_settings()
    client = WeFlowClient(settings)

    monkeypatch.setattr(
        client,
        "_get_json",
        lambda path, query=None: {
            "sessions": [
                {
                    "id": "s-1",
                    "username": "wxid_a",
                    "displayName": "customer-a",
                    "type": "private",
                    "lastTimestamp": 1710000000,
                    "unreadCount": 2,
                },
                {
                    "id": "s-2",
                    "username": "room@chatroom",
                    "displayName": "group-room",
                    "type": "group",
                    "lastTimestamp": 1710000001,
                    "unreadCount": 5,
                },
            ]
        },
    )

    sessions = client.fetch_sessions(limit=100)

    assert [item.session_id for item in sessions] == ["s-1"]
    assert sessions[0].display_name == "customer-a"
    assert sessions[0].unread_count == 2


def test_fetch_sessions_falls_back_to_username_when_session_id_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = _build_settings()
    client = WeFlowClient(settings)

    monkeypatch.setattr(
        client,
        "_get_json",
        lambda path, query=None: {
            "sessions": [
                {
                    "username": "wxid_private_a",
                    "displayName": "customer-b",
                    "type": 0,
                    "lastTimestamp": 1710000002,
                    "unreadCount": 1,
                },
                {
                    "username": "room@chatroom",
                    "displayName": "group-room",
                    "type": 0,
                    "lastTimestamp": 1710000003,
                    "unreadCount": 9,
                },
            ]
        },
    )

    sessions = client.fetch_sessions(limit=100)

    assert [item.session_id for item in sessions] == ["wxid_private_a"]
    assert sessions[0].username == "wxid_private_a"
    assert sessions[0].display_name == "customer-b"


def test_fetch_session_messages_returns_message_items(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = _build_settings()
    client = WeFlowClient(settings)

    monkeypatch.setattr(
        client,
        "_get_json",
        lambda path, query=None: {
            "messages": [
                {
                    "rawid": "m-001",
                    "sessionId": "s-1",
                    "talker": "wxid_a",
                    "type": "text",
                    "isSelf": False,
                    "content": "hello",
                    "timestamp": 1710000000,
                }
            ]
        },
    )

    messages = client.fetch_session_messages("s-1", limit=50)

    assert messages[0].rawid == "m-001"
    assert messages[0].session_id == "s-1"
    assert messages[0].content == "hello"
    assert messages[0].is_self is False


def test_fetch_session_messages_supports_chatlab_payload(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = _build_settings()
    client = WeFlowClient(settings)

    monkeypatch.setattr(
        client,
        "_get_json",
        lambda path, query=None: {
            "meta": {
                "name": "customer-b",
                "platform": "wechat",
                "type": "private",
                "ownerId": "wxid_owner_1217",
            },
            "members": [
                {"platformId": "wxid_owner", "accountName": "我"},
                {"platformId": "wxid_customer", "accountName": "customer-b"},
            ],
            "messages": [
                {
                    "sender": "wxid_owner",
                    "timestamp": 1710000010,
                    "type": 0,
                    "content": "self message",
                    "platformMessageId": "pm-001",
                },
                {
                    "sender": "wxid_customer",
                    "timestamp": 1710000020,
                    "type": 0,
                    "content": "customer message",
                    "platformMessageId": "pm-002",
                },
            ],
        },
    )

    messages = client.fetch_session_messages("wxid_customer", limit=50)

    assert [item.rawid for item in messages] == ["pm-001", "pm-002"]
    assert messages[0].session_id == "wxid_customer"
    assert messages[0].is_self is True
    assert messages[0].message_type == "text"
    assert messages[1].content == "customer message"
    assert messages[1].is_self is False
