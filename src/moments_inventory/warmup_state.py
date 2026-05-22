from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class WarmupPageState(str, Enum):
    UNKNOWN = "unknown"
    SEARCH_READY = "search_ready"
    CHAT_READY = "chat_ready"
    PROFILE_READY = "profile_ready"
    TIMELINE_POPUP = "timeline_popup"
    BROKEN = "broken"


class WarmupStepStatus(str, Enum):
    PASSED = "passed"
    FAILED = "failed"
    SKIPPED = "skipped"


@dataclass(slots=True)
class WarmupStepResult:
    step: str
    status: WarmupStepStatus
    reason: str = ""


@dataclass(slots=True)
class WarmupContactDiagnostics:
    remark_name: str | None
    search_ok: bool = False
    select_contact_ok: bool = False
    profile_ok: bool = False
    timeline_open_ok: bool = False
    timeline_scroll_ok: bool = False
    reset_ok: bool = False
    forced_recovery_used: bool = False
    final_page_state: WarmupPageState = WarmupPageState.UNKNOWN
    step_results: list[WarmupStepResult] = field(default_factory=list)
