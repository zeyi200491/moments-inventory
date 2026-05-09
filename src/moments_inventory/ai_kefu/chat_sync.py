from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass, replace
import time
from typing import Callable, Protocol

from moments_inventory.weflow_client import WeFlowMessage, WeFlowRequestError, WeFlowSession


class ChatSyncGateway(Protocol):
    def fetch_sessions(self, limit: int = 100) -> list[WeFlowSession]:
        ...

    def fetch_session_messages(self, session_id: str, limit: int = 100) -> list[WeFlowMessage]:
        ...


@dataclass(slots=True)
class ChatSessionState:
    session_id: str
    username: str
    display_name: str
    session_type: str = "private"
    last_timestamp: int = 0
    unread_count: int = 0
    draft_buffer: str = ""
    auto_generate: bool = False
    is_current: bool = False
    last_message_timestamp: int = 0


class ChatSyncBridge:
    def __init__(
        self,
        merge_window_seconds: int = 8,
        *,
        client: ChatSyncGateway | None = None,
        session_poll_limit: int = 100,
        message_poll_limit: int = 100,
        recent_message_window_seconds: int = 3600,
        max_processed_message_keys: int = 5000,
        max_draft_buffer_chars: int = 5000,
        session_missing_eviction_threshold: int = 3,
        now_provider: Callable[[], float] | None = None,
    ) -> None:
        self._merge_window_seconds = merge_window_seconds
        self._client = client
        self._session_poll_limit = session_poll_limit
        self._message_poll_limit = message_poll_limit
        self._recent_message_window_seconds = recent_message_window_seconds
        self._max_processed_message_keys = max_processed_message_keys
        self._max_draft_buffer_chars = max_draft_buffer_chars
        self._session_missing_eviction_threshold = session_missing_eviction_threshold
        self._now_provider = now_provider or time.time
        self._sessions: dict[str, ChatSessionState] = {}
        self._missing_session_refresh_counts: dict[str, int] = {}
        self._processed_message_keys: OrderedDict[tuple[str, str], None] = OrderedDict()
        self.current_session_id: str | None = None

    def sync_sessions(self, sessions: list[WeFlowSession]) -> None:
        seen_session_ids: set[str] = set()
        for session in sessions:
            if not self._is_private_session(session):
                continue
            seen_session_ids.add(session.session_id)
            self._missing_session_refresh_counts[session.session_id] = 0
            existing = self._sessions.get(session.session_id)
            if existing is None:
                self._sessions[session.session_id] = ChatSessionState(
                    session_id=session.session_id,
                    username=session.username,
                    display_name=session.display_name or session.username or session.session_id,
                    session_type=session.session_type or "private",
                    last_timestamp=session.last_timestamp,
                    unread_count=session.unread_count,
                )
                continue

            existing.username = session.username or existing.username
            existing.display_name = (
                session.display_name or existing.display_name or existing.username or existing.session_id
            )
            existing.session_type = session.session_type or existing.session_type
            existing.last_timestamp = max(existing.last_timestamp, session.last_timestamp)
            existing.unread_count = session.unread_count

        for session_id in list(self._sessions):
            if session_id in seen_session_ids:
                continue
            missing_count = self._missing_session_refresh_counts.get(session_id, 0) + 1
            self._missing_session_refresh_counts[session_id] = missing_count
            if self._should_evict_missing_session(session_id, missing_count):
                self._sessions.pop(session_id, None)
                self._missing_session_refresh_counts.pop(session_id, None)

    def sync_messages(self, messages: list[WeFlowMessage]) -> None:
        for message in messages:
            if not self._should_process_message(message):
                continue
            message_key = (message.session_id, message.rawid)
            if message_key in self._processed_message_keys:
                continue

            session = self._ensure_private_session(message.session_id, username=message.talker)
            content = message.content.strip()
            self._remember_processed_message(message_key)
            if not content or not self._is_recent_message(message):
                continue

            if session.draft_buffer:
                gap = message.timestamp - session.last_message_timestamp
                separator = "\n" if gap <= self._merge_window_seconds else "\n\n"
                session.draft_buffer = self._trim_draft_buffer(
                    f"{session.draft_buffer}{separator}{content}"
                )
            else:
                session.draft_buffer = self._trim_draft_buffer(content)

            session.last_message_timestamp = message.timestamp
            session.last_timestamp = max(session.last_timestamp, message.timestamp)

    def list_sessions(self) -> list[ChatSessionState]:
        self._refresh_sessions()
        return [
            replace(session)
            for session in sorted(
                self._sessions.values(),
                key=self._sort_key,
            )
        ]

    def get_session(self, session_id: str) -> ChatSessionState | None:
        self._refresh_sessions()
        self._refresh_session_messages(session_id)
        session = self._sessions.get(session_id)
        if session is None:
            return None
        return replace(session)

    def set_current_session(self, session_id: str, *, auto_generate: bool) -> ChatSessionState:
        self._refresh_sessions()
        self._refresh_session_messages(session_id)
        target = self._sessions.get(session_id)
        if target is None or target.session_type != "private":
            raise KeyError(session_id)
        for existing in self._sessions.values():
            existing.is_current = existing.session_id == session_id
            existing.auto_generate = existing.session_id == session_id and auto_generate
        self.current_session_id = session_id
        return replace(target)

    def _refresh_sessions(self) -> None:
        if self._client is None:
            return
        try:
            self.sync_sessions(self._client.fetch_sessions(limit=self._session_poll_limit))
        except WeFlowRequestError:
            return

    def _refresh_session_messages(self, session_id: str) -> None:
        if self._client is None:
            return
        try:
            self.sync_messages(
                self._client.fetch_session_messages(session_id, limit=self._message_poll_limit)
            )
        except WeFlowRequestError:
            return

    def _ensure_private_session(
        self,
        session_id: str,
        *,
        username: str = "",
        display_name: str = "",
    ) -> ChatSessionState:
        session = self._sessions.get(session_id)
        if session is not None:
            if username and not session.username:
                session.username = username
            if display_name and not session.display_name:
                session.display_name = display_name
            return session

        session = ChatSessionState(
            session_id=session_id,
            username=username,
            display_name=display_name or username or session_id,
            session_type="private",
        )
        self._sessions[session_id] = session
        self._missing_session_refresh_counts[session_id] = 0
        return session

    def _should_process_message(self, message: WeFlowMessage) -> bool:
        if not message.session_id or not message.rawid:
            return False
        if message.is_self:
            return False
        if message.message_type.strip().lower() != "text":
            return False
        session = self._sessions.get(message.session_id)
        if session is not None and session.session_type != "private":
            return False
        if message.talker.endswith("@chatroom"):
            return False
        return True

    def _is_recent_message(self, message: WeFlowMessage) -> bool:
        if message.timestamp <= 0:
            return False
        now_timestamp = int(self._now_provider())
        return message.timestamp >= now_timestamp - self._recent_message_window_seconds

    def _is_private_session(self, session: WeFlowSession) -> bool:
        if session.session_type and session.session_type != "private":
            return False
        if session.username.endswith("@chatroom"):
            return False
        return True

    def _remember_processed_message(self, message_key: tuple[str, str]) -> None:
        self._processed_message_keys[message_key] = None
        self._processed_message_keys.move_to_end(message_key)
        while len(self._processed_message_keys) > self._max_processed_message_keys:
            self._processed_message_keys.popitem(last=False)

    def _trim_draft_buffer(self, draft_buffer: str) -> str:
        if len(draft_buffer) <= self._max_draft_buffer_chars:
            return draft_buffer
        return draft_buffer[-self._max_draft_buffer_chars :].lstrip("\n")

    def _should_evict_missing_session(self, session_id: str, missing_count: int) -> bool:
        if missing_count < self._session_missing_eviction_threshold:
            return False
        session = self._sessions.get(session_id)
        if session is None:
            return False
        if session.is_current or self.current_session_id == session_id:
            return False
        if session.draft_buffer.strip():
            return False
        last_activity = max(session.last_message_timestamp, session.last_timestamp)
        if last_activity <= 0:
            return True
        now_timestamp = int(self._now_provider())
        return last_activity < now_timestamp - self._recent_message_window_seconds

    def _sort_key(self, session: ChatSessionState) -> tuple[int, int, str]:
        return (
            0 if session.is_current else 1,
            -max(session.last_message_timestamp, session.last_timestamp),
            session.session_id,
        )
