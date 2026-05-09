from __future__ import annotations

from moments_inventory.ai_kefu.chat_sync import ChatSyncBridge
from moments_inventory.weflow_client import WeFlowMessage, WeFlowSession


class FakeGateway:
    def __init__(self) -> None:
        self.sessions_calls = 0
        self.messages_calls: list[tuple[str, int]] = []

    def fetch_sessions(self, limit: int = 100) -> list[WeFlowSession]:
        self.sessions_calls += 1
        return [
            _build_session(
                session_id="s-1",
                username="wxid_alice",
                display_name="Alice",
                last_timestamp=120,
                unread_count=3,
            )
        ]

    def fetch_session_messages(self, session_id: str, limit: int = 100) -> list[WeFlowMessage]:
        self.messages_calls.append((session_id, limit))
        return [
            _build_message(
                rawid="m-remote-1",
                session_id=session_id,
                talker="wxid_alice",
                content="remote message",
                timestamp=120,
            )
        ]


def _build_session(
    *,
    session_id: str = "s-1",
    username: str = "wxid_alice",
    display_name: str = "Alice",
    session_type: str = "private",
    last_timestamp: int = 0,
    unread_count: int = 0,
) -> WeFlowSession:
    return WeFlowSession(
        session_id=session_id,
        username=username,
        display_name=display_name,
        session_type=session_type,
        last_timestamp=last_timestamp,
        unread_count=unread_count,
    )


def _build_message(
    *,
    rawid: str,
    session_id: str = "s-1",
    talker: str = "wxid_alice",
    content: str = "hello",
    timestamp: int = 1_710_000_000,
    is_self: bool = False,
    message_type: str = "text",
) -> WeFlowMessage:
    return WeFlowMessage(
        rawid=rawid,
        session_id=session_id,
        talker=talker,
        content=content,
        timestamp=timestamp,
        is_self=is_self,
        message_type=message_type,
    )


def test_current_private_session_appends_messages_with_newline_within_merge_window() -> None:
    bridge = ChatSyncBridge(merge_window_seconds=8, now_provider=lambda: 1_710_000_100)
    bridge.sync_sessions([_build_session(session_id="s-1", last_timestamp=100)])
    bridge.set_current_session("s-1", auto_generate=True)

    bridge.sync_messages(
        [
            _build_message(rawid="m-1", content="first", timestamp=1_710_000_000),
            _build_message(rawid="m-2", content="second", timestamp=1_710_000_007),
        ]
    )

    session = bridge.get_session("s-1")
    assert session is not None
    assert session.draft_buffer == "first\nsecond"


def test_messages_after_merge_window_insert_blank_line_separator() -> None:
    bridge = ChatSyncBridge(merge_window_seconds=8, now_provider=lambda: 1_710_000_100)
    bridge.sync_sessions([_build_session(session_id="s-1", last_timestamp=100)])

    bridge.sync_messages(
        [
            _build_message(rawid="m-1", content="first", timestamp=1_710_000_000),
            _build_message(rawid="m-2", content="second", timestamp=1_710_000_009),
        ]
    )

    session = bridge.get_session("s-1")
    assert session is not None
    assert session.draft_buffer == "first\n\nsecond"


def test_group_session_messages_are_ignored() -> None:
    bridge = ChatSyncBridge(merge_window_seconds=8, now_provider=lambda: 1_710_000_100)
    bridge.sync_sessions(
        [
            _build_session(
                session_id="group-1",
                username="team@chatroom",
                display_name="group",
                session_type="group",
                last_timestamp=100,
            )
        ]
    )

    bridge.sync_messages(
        [
            _build_message(
                rawid="m-1",
                session_id="group-1",
                talker="team@chatroom",
                content="group message",
                timestamp=1_710_000_000,
            )
        ]
    )

    assert bridge.get_session("group-1") is None


def test_duplicate_rawid_within_same_session_is_ignored() -> None:
    bridge = ChatSyncBridge(merge_window_seconds=8, now_provider=lambda: 1_710_000_100)
    bridge.sync_sessions([_build_session(session_id="s-1", last_timestamp=100)])

    bridge.sync_messages(
        [
            _build_message(rawid="m-1", content="first", timestamp=1_710_000_000),
            _build_message(rawid="m-1", content="duplicate", timestamp=1_710_000_001),
        ]
    )

    session = bridge.get_session("s-1")
    assert session is not None
    assert session.draft_buffer == "first"


def test_old_messages_outside_recent_window_are_ignored() -> None:
    bridge = ChatSyncBridge(
        merge_window_seconds=8,
        recent_message_window_seconds=3600,
        now_provider=lambda: 10_000,
    )
    bridge.sync_sessions([_build_session(session_id="s-1", last_timestamp=9_900)])

    bridge.sync_messages(
        [
            _build_message(rawid="m-old", content="old", timestamp=6_000),
            _build_message(rawid="m-new", content="new", timestamp=9_500),
        ]
    )

    session = bridge.get_session("s-1")
    assert session is not None
    assert session.draft_buffer == "new"
    assert session.last_message_timestamp == 9_500


def test_processed_message_keys_and_draft_buffer_are_bounded() -> None:
    bridge = ChatSyncBridge(
        merge_window_seconds=8,
        max_processed_message_keys=2,
        max_draft_buffer_chars=10,
        now_provider=lambda: 1_710_000_100,
    )
    bridge.sync_sessions([_build_session(session_id="s-1", last_timestamp=100)])

    bridge.sync_messages(
        [
            _build_message(rawid="m-1", content="12345", timestamp=1_710_000_000),
            _build_message(rawid="m-2", content="67890", timestamp=1_710_000_001),
            _build_message(rawid="m-3", content="abcde", timestamp=1_710_000_002),
        ]
    )

    session = bridge.get_session("s-1")
    assert session is not None
    assert len(bridge._processed_message_keys) == 2
    assert list(bridge._processed_message_keys.keys()) == [("s-1", "m-2"), ("s-1", "m-3")]
    assert session.draft_buffer == "7890\nabcde"


def test_bridge_refreshes_sessions_and_messages_from_gateway() -> None:
    gateway = FakeGateway()
    bridge = ChatSyncBridge(
        merge_window_seconds=8,
        client=gateway,
        session_poll_limit=20,
        message_poll_limit=30,
        now_provider=lambda: 3_700,
    )

    sessions = bridge.list_sessions()
    detail = bridge.get_session("s-1")
    current = bridge.set_current_session("s-1", auto_generate=True)

    assert gateway.sessions_calls >= 3
    assert ("s-1", 30) in gateway.messages_calls
    assert sessions[0].session_id == "s-1"
    assert detail is not None
    assert detail.draft_buffer == "remote message"
    assert current.auto_generate is True


def test_set_current_session_raises_for_unknown_private_session() -> None:
    bridge = ChatSyncBridge(merge_window_seconds=8, now_provider=lambda: 1_710_000_100)

    try:
        bridge.set_current_session("missing", auto_generate=False)
    except KeyError as exc:
        assert exc.args == ("missing",)
    else:
        raise AssertionError("预期未知会话时抛出 KeyError")


def test_missing_stale_session_is_evicted_after_multiple_refreshes() -> None:
    bridge = ChatSyncBridge(
        merge_window_seconds=8,
        recent_message_window_seconds=3600,
        session_missing_eviction_threshold=3,
        now_provider=lambda: 10_000,
    )
    bridge.sync_sessions(
        [
            _build_session(
                session_id="stale",
                username="wxid_stale",
                display_name="Stale",
                last_timestamp=5_000,
            )
        ]
    )

    bridge.sync_sessions([])
    bridge.sync_sessions([])
    assert bridge.get_session("stale") is not None

    bridge.sync_sessions([])
    assert bridge.get_session("stale") is None


def test_missing_current_or_buffered_session_is_not_evicted() -> None:
    bridge = ChatSyncBridge(
        merge_window_seconds=8,
        recent_message_window_seconds=3600,
        session_missing_eviction_threshold=2,
        now_provider=lambda: 10_000,
    )
    bridge.sync_sessions(
        [
            _build_session(
                session_id="current",
                username="wxid_current",
                display_name="Current",
                last_timestamp=5_000,
            ),
            _build_session(
                session_id="buffered",
                username="wxid_buffered",
                display_name="Buffered",
                last_timestamp=5_000,
            ),
        ]
    )
    bridge.set_current_session("current", auto_generate=False)
    bridge.sync_messages(
        [
            _build_message(
                rawid="m-buffer",
                session_id="buffered",
                talker="wxid_buffered",
                content="待处理消息",
                timestamp=9_900,
            )
        ]
    )

    bridge.sync_sessions([])
    bridge.sync_sessions([])

    assert bridge.get_session("current") is not None
    buffered = bridge.get_session("buffered")
    assert buffered is not None
    assert buffered.draft_buffer == "待处理消息"
