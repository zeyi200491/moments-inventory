from dataclasses import dataclass

import pytest

import moments_inventory.wechat_ui_adapter as wechat_ui_adapter_module
from moments_inventory.warmup_state import (
    WarmupPageState,
    WarmupStepStatus,
)
from moments_inventory.wechat_ui_adapter import (
    PywinautoWechatController,
    WeChatWarmupAdapter,
)


@dataclass(slots=True)
class FakeWarmupUiSettings:
    search_delay_ms: int = 800
    open_profile_delay_ms: int = 1000
    open_timeline_delay_ms: int = 1200
    timeline_sync_wait_ms: int = 1500
    scroll_count: int = 3
    scroll_delay_ms: int = 900
    back_delay_ms: int = 600
    verify_state_after_each_contact: bool = True


class FakeWarmupController:
    def __init__(
        self,
        has_window: bool = True,
        fail_calls: set[tuple[str, str | int | None]] | None = None,
        failure_exception: type[Exception] = RuntimeError,
        auto_timeline_popup: bool = True,
        reset_page_state_on_reset: WarmupPageState | None = WarmupPageState.SEARCH_READY,
    ) -> None:
        self.has_window = has_window
        self.fail_calls = fail_calls or set()
        self.failure_exception = failure_exception
        self.auto_timeline_popup = auto_timeline_popup
        self.reset_page_state_on_reset = reset_page_state_on_reset
        self.calls: list[tuple[str, str | int | None]] = []
        self.page_state = WarmupPageState.SEARCH_READY

    def _record_call(self, method: str, value: str | int | None = None) -> None:
        call = (method, value)
        self.calls.append(call)
        if call in self.fail_calls:
            raise self.failure_exception("mock warmup failure")

    def ensure_wechat_window(self) -> None:
        self._record_call("ensure_wechat_window")
        if not self.has_window:
            raise RuntimeError("window missing")

    def open_search(self, start_page: str) -> None:
        self._record_call("open_search", start_page)

    def input_search_text(self, text: str) -> None:
        self._record_call("input_search_text", text)

    def select_contact(self, remark_name: str) -> None:
        self._record_call("select_contact", remark_name)

    def open_timeline(self) -> None:
        self._record_call("open_timeline")
        if self.auto_timeline_popup:
            self.page_state = WarmupPageState.TIMELINE_POPUP

    def page_down(self) -> None:
        self._record_call("page_down")

    def reset_to_searchable_page(self, back_delay_ms: int) -> None:
        self._record_call("reset_to_searchable_page", back_delay_ms)
        if self.reset_page_state_on_reset is not None:
            self.page_state = self.reset_page_state_on_reset

    def sleep_ms(self, milliseconds: int) -> None:
        self._record_call("sleep_ms", milliseconds)

    def detect_page_state(self) -> WarmupPageState:
        self._record_call("detect_page_state")
        return self.page_state

    def force_recover_to_searchable_page(self) -> bool:
        self._record_call("force_recover_to_searchable_page")
        self.page_state = WarmupPageState.SEARCH_READY
        return True


def test_prepare_and_warmup_contact_run_expected_controller_sequence() -> None:
    controller = FakeWarmupController()
    settings = FakeWarmupUiSettings()
    adapter = WeChatWarmupAdapter(settings=settings, controller=controller)

    adapter.prepare("contacts")

    diagnostics = adapter.warmup_contact("寮犱笁")

    assert diagnostics.search_ok is True
    assert diagnostics.select_contact_ok is True
    assert diagnostics.timeline_open_ok is True
    assert diagnostics.timeline_scroll_ok is True
    assert diagnostics.reset_ok is True
    assert diagnostics.final_page_state is WarmupPageState.SEARCH_READY
    assert [step.step for step in diagnostics.step_results] == [
        "ensure_wechat_window",
        "open_search",
        "input_search_text",
        "select_contact",
        "open_timeline",
        "page_down",
        "reset_to_searchable_page",
        "detect_page_state",
    ]
    assert controller.calls == [
        ("ensure_wechat_window", None),
        ("ensure_wechat_window", None),
        ("open_search", "contacts"),
        ("sleep_ms", 800),
        ("input_search_text", "寮犱笁"),
        ("select_contact", "寮犱笁"),
        ("sleep_ms", 1000),
        ("open_timeline", None),
        ("sleep_ms", 1200),
        ("detect_page_state", None),
        ("page_down", None),
        ("reset_to_searchable_page", 600),
        ("detect_page_state", None),
    ]


def test_prepare_stores_runtime_start_page_state_with_minimal_settings() -> None:
    adapter = WeChatWarmupAdapter(
        settings=FakeWarmupUiSettings(),
        controller=FakeWarmupController(),
    )

    adapter.prepare("chat_list")

    assert adapter._prepared_start_page == "chat_list"


def test_prepare_raises_when_wechat_window_is_missing() -> None:
    adapter = WeChatWarmupAdapter(
        settings=FakeWarmupUiSettings(),
        controller=FakeWarmupController(has_window=False),
    )

    with pytest.raises(RuntimeError):
        adapter.prepare("contacts")


def test_prepare_raises_when_start_page_is_invalid() -> None:
    adapter = WeChatWarmupAdapter(
        settings=FakeWarmupUiSettings(),
        controller=FakeWarmupController(),
    )

    with pytest.raises(RuntimeError):
        adapter.prepare("timeline")


def test_warmup_contact_raises_when_prepare_has_not_been_called() -> None:
    adapter = WeChatWarmupAdapter(
        settings=FakeWarmupUiSettings(),
        controller=FakeWarmupController(),
    )

    with pytest.raises(RuntimeError, match="prepare"):
        adapter.warmup_contact("寮犱笁")


def test_warmup_contact_returns_false_and_runs_best_effort_reset_on_runtime_error() -> None:
    controller = FakeWarmupController(fail_calls={("open_timeline", None)})
    adapter = WeChatWarmupAdapter(settings=FakeWarmupUiSettings(), controller=controller)
    adapter.prepare("contacts")

    diagnostics = adapter.warmup_contact("寮犱笁")

    assert diagnostics.timeline_open_ok is False
    assert diagnostics.reset_ok is True
    assert diagnostics.final_page_state is WarmupPageState.SEARCH_READY
    failed_steps = [step for step in diagnostics.step_results if step.status is WarmupStepStatus.FAILED]
    assert failed_steps[-1].step == "open_timeline"
    assert controller.calls[-2:] == [
        ("reset_to_searchable_page", 600),
        ("detect_page_state", None),
    ]


def test_warmup_contact_fails_before_page_down_when_timeline_popup_is_missing() -> None:
    controller = FakeWarmupController(auto_timeline_popup=False)
    adapter = WeChatWarmupAdapter(settings=FakeWarmupUiSettings(), controller=controller)
    adapter.prepare("contacts")

    diagnostics = adapter.warmup_contact("寮犱笁")

    assert diagnostics.timeline_open_ok is False
    assert diagnostics.timeline_scroll_ok is False
    failed_steps = [step for step in diagnostics.step_results if step.status is WarmupStepStatus.FAILED]
    assert failed_steps[-1].step == "open_timeline"
    assert failed_steps[-1].reason == "timeline popup missing"
    assert ("page_down", None) not in controller.calls


def test_warmup_contact_returns_false_and_runs_best_effort_reset_on_value_error() -> None:
    controller = FakeWarmupController(
        fail_calls={("select_contact", "寮犱笁")},
        failure_exception=ValueError,
    )
    adapter = WeChatWarmupAdapter(settings=FakeWarmupUiSettings(), controller=controller)
    adapter.prepare("contacts")

    diagnostics = adapter.warmup_contact("寮犱笁")

    assert diagnostics.select_contact_ok is False
    assert diagnostics.reset_ok is True
    failed_steps = [step for step in diagnostics.step_results if step.status is WarmupStepStatus.FAILED]
    assert failed_steps[-1].step == "select_contact"
    assert controller.calls[-2:] == [
        ("reset_to_searchable_page", 600),
        ("detect_page_state", None),
    ]


def test_best_effort_reset_does_not_raise_when_cleanup_fails() -> None:
    controller = FakeWarmupController(
        fail_calls={
            ("open_timeline", None),
            ("reset_to_searchable_page", 600),
        },
        failure_exception=ValueError,
    )
    adapter = WeChatWarmupAdapter(settings=FakeWarmupUiSettings(), controller=controller)
    adapter.prepare("contacts")

    diagnostics = adapter.warmup_contact("寮犱笁")

    assert diagnostics.reset_ok is False
    assert ("reset_to_searchable_page", 600) in controller.calls


def test_warmup_contact_force_recovers_when_final_page_state_is_unknown() -> None:
    controller = FakeWarmupController(reset_page_state_on_reset=WarmupPageState.UNKNOWN)
    adapter = WeChatWarmupAdapter(settings=FakeWarmupUiSettings(), controller=controller)
    adapter.prepare("contacts")

    diagnostics = adapter.warmup_contact("寮犱笁")

    assert diagnostics.reset_ok is True
    assert diagnostics.forced_recovery_used is True
    assert diagnostics.final_page_state is WarmupPageState.SEARCH_READY
    assert controller.calls[-3:] == [
        ("detect_page_state", None),
        ("force_recover_to_searchable_page", None),
        ("detect_page_state", None),
    ]
    assert [step.step for step in diagnostics.step_results][-3:] == [
        "detect_page_state",
        "force_recover_to_searchable_page",
        "detect_page_state_after_recovery",
    ]


class _FakeWrapper:
    def __init__(self, *, fail_on_type_keys: bool = False, fail_on_click: bool = False) -> None:
        self.fail_on_type_keys = fail_on_type_keys
        self.fail_on_click = fail_on_click
        self.calls: list[tuple[str, object]] = []

    def type_keys(self, keys: str, set_foreground: bool = False, **kwargs: object) -> None:
        self.calls.append(("type_keys", keys))
        if self.fail_on_type_keys:
            raise ValueError("backend failure")

    def click_input(self, double: bool = False) -> None:
        self.calls.append(("click_input", double))
        if self.fail_on_click:
            raise ValueError("backend failure")


class _FakeRect:
    def __init__(self, *, left: int, top: int, width: int = 32, height: int = 32) -> None:
        self.left = left
        self.top = top
        self._width = width
        self._height = height
        self.right = left + width
        self.bottom = top + height

    def width(self) -> int:
        return self._width

    def height(self) -> int:
        return self._height


class _FakeWindow:
    def __init__(self, *, width: int = 1294, height: int = 703, left: int = 0, top: int = 0) -> None:
        self.wrapper = _FakeWrapper()
        self._rect = _FakeRect(left=left, top=top, width=width, height=height)

    def rectangle(self) -> _FakeRect:
        return self._rect

    def set_focus(self) -> None:
        self.wrapper.calls.append(("set_focus", None))

    def type_keys(self, keys: str, set_foreground: bool = False, **kwargs: object) -> None:
        self.wrapper.calls.append(("type_keys", keys))

    def click_input(self, coords=None, double: bool = False) -> None:
        self.wrapper.calls.append(("window_click", (coords, double)))


class _FakeElement:
    def __init__(
        self,
        *,
        control_type: str,
        text: str,
        left: int,
        top: int,
        width: int = 32,
        height: int = 32,
        automation_id: str = "",
        class_name: str = "",
    ) -> None:
        self.wrapper = _FakeWrapper()
        self._text = text
        self._rect = _FakeRect(left=left, top=top, width=width, height=height)
        self.element_info = type(
            "ElementInfo",
            (),
            {
                "control_type": control_type,
                "automation_id": automation_id,
                "class_name": class_name,
                "name": text,
            },
        )()

    def window_text(self) -> str:
        return self._text

    def rectangle(self) -> _FakeRect:
        return self._rect

    def type_keys(self, keys: str, set_foreground: bool = False, **kwargs: object) -> None:
        self.wrapper.type_keys(keys, set_foreground=set_foreground, **kwargs)

    def click_input(self, double: bool = False) -> None:
        self.wrapper.click_input(double=double)


class _TestablePywinautoWechatController(PywinautoWechatController):
    def __init__(
        self,
        *,
        descendants: list[_FakeElement],
        search_box: object | None,
        search_box_states: list[object | None] | None = None,
        window: _FakeWindow | None = None,
        search_results_popup_window: _FakeWindow | None = None,
        search_results_popup_states: list[_FakeWindow | None] | None = None,
        timeline_popup_window: _FakeWindow | None = None,
        detected_timeline_preview_bbox: tuple[int, int, int, int] | None = None,
        detected_timeline_preview_bbox_near_entry: tuple[int, int, int, int] | None = None,
        media_row_bbox: tuple[int, int, int, int] | None = None,
        panel_scan_bbox: tuple[int, int, int, int] | None = None,
        chat_title_text: str | None = None,
        require_timeline_popup: bool = False,
        chat_menu_open: bool = True,
        chat_menu_open_states: list[bool] | None = None,
        popup_after_screen_click_indices: set[int] | None = None,
    ) -> None:
        super().__init__()
        self._descendants = descendants
        self._search_box = search_box
        self._search_box_states = list(search_box_states or [])
        self._window = window or _FakeWindow()
        self._search_results_popup_window = search_results_popup_window
        self._search_results_popup_states = list(search_results_popup_states or [])
        self._timeline_popup_window = timeline_popup_window
        self.detected_timeline_preview_bbox = detected_timeline_preview_bbox
        self.detected_timeline_preview_bbox_near_entry = detected_timeline_preview_bbox_near_entry
        self.media_row_bbox = media_row_bbox
        self.panel_scan_bbox = panel_scan_bbox
        self.chat_title_text = chat_title_text
        self.require_timeline_popup = require_timeline_popup
        self.chat_menu_open = chat_menu_open
        self.chat_menu_open_states = list(chat_menu_open_states or [])
        self.popup_after_screen_click_indices = set(popup_after_screen_click_indices or [])
        self.sleep_calls: list[int] = []
        self.screen_click_calls: list[tuple[int, int]] = []
        self.screen_click_targets: list[str] = []
        self.screen_wheel_calls: list[tuple[int, int, int]] = []
        self.screen_drag_calls: list[tuple[int, int, int, int]] = []
        self.hold_down_calls: list[tuple[str, int]] = []
        self.escape_calls: list[str] = []
        self.clipboard_text_calls: list[str] = []
        self.clipboard_buffer_text: str = ""
        self.clipboard_copy_result: str | None = None

    def _iter_descendants(self):
        return iter(self._descendants)

    def _find_search_box(self):
        if self._search_box_states:
            return self._search_box_states.pop(0)
        if self._search_box is not None:
            return self._search_box
        return PywinautoWechatController._find_search_box(self)

    def sleep_ms(self, milliseconds: int) -> None:
        self.sleep_calls.append(milliseconds)

    def _screen_click_relative(self, window, x: int, y: int) -> None:
        assert window is self._window or window is self._timeline_popup_window
        self.screen_click_targets.append("popup" if window is self._timeline_popup_window else "main")
        self.screen_click_calls.append((x, y))
        if len(self.screen_click_calls) in self.popup_after_screen_click_indices:
            self._timeline_popup_window = _FakeWindow(width=576, height=558, left=1739, top=40)

    def _screen_wheel_relative(self, window, x: int, y: int, wheel_delta: int) -> None:
        assert window is self._window
        self.screen_wheel_calls.append((x, y, wheel_delta))

    def _screen_drag_relative(self, window, start_x: int, start_y: int, end_x: int, end_y: int) -> None:
        assert window is self._window
        self.screen_drag_calls.append((start_x, start_y, end_x, end_y))

    def _set_clipboard_text(self, text: str) -> None:
        self.clipboard_text_calls.append(text)
        self.clipboard_buffer_text = text

    def _type_keys(self, wrapper, keys: str, **kwargs: object) -> None:
        PywinautoWechatController._type_keys(wrapper, keys, **kwargs)
        if keys == "^a^c" and self.clipboard_copy_result is not None:
            self.clipboard_buffer_text = self.clipboard_copy_result

    def _detect_timeline_preview_bbox(self):
        return self.detected_timeline_preview_bbox

    def _detect_timeline_preview_bbox_from_media_rows(self):
        return self.media_row_bbox

    def _detect_timeline_preview_bbox_by_panel_scan(self):
        return self.panel_scan_bbox

    def _get_clipboard_text(self):
        return self.clipboard_buffer_text

    def _find_timeline_popup_window(self):
        return self._timeline_popup_window

    def _find_search_results_popup_window(self):
        if self._search_results_popup_states:
            return self._search_results_popup_states.pop(0)
        return self._search_results_popup_window

    def _hold_down_arrow(self, window, duration_ms: int) -> None:
        target = "popup" if window is self._timeline_popup_window else "main"
        self.hold_down_calls.append((target, duration_ms))

    def _send_escape(self, window) -> None:
        target = "popup" if window is self._timeline_popup_window else "main"
        self.escape_calls.append(target)


def test_reset_to_searchable_page_closes_timeline_overlay_and_keeps_main_window() -> None:
    popup = _FakeWindow(width=576, height=558, left=1739, top=40)
    controller = _TestablePywinautoWechatController(
        descendants=[],
        search_box=None,
        timeline_popup_window=popup,
    )

    controller.reset_to_searchable_page(600)

    assert controller._window.wrapper.calls == []
    assert controller.escape_calls == ["popup"]
    assert controller.screen_click_calls == []
    assert controller.sleep_calls == [600]


def test_reset_to_searchable_page_does_not_send_escape_to_main_window_when_popup_missing() -> None:
    controller = _TestablePywinautoWechatController(
        descendants=[],
        search_box=None,
        timeline_popup_window=None,
    )

    controller.reset_to_searchable_page(600)

    assert controller.escape_calls == []
    assert controller.sleep_calls == [600]


def test_page_down_clicks_scrollbar_track_bottom_right_area() -> None:
    popup = _FakeWindow(width=576, height=558, left=1739, top=40)
    controller = _TestablePywinautoWechatController(
        descendants=[],
        search_box=None,
        timeline_popup_window=popup,
    )

    controller.page_down()

    assert controller._window.wrapper.calls == []
    assert controller.hold_down_calls == [("popup", 20000)]
    assert controller.screen_click_calls == []
    assert controller.screen_wheel_calls == []
    assert controller.screen_drag_calls == []


def test_page_down_track_click_uses_same_safe_point_without_focus_side_effects() -> None:
    popup = _FakeWindow(width=576, height=558, left=1739, top=40)
    controller = _TestablePywinautoWechatController(
        descendants=[],
        search_box=None,
        timeline_popup_window=popup,
    )

    controller.page_down()

    assert controller._window.wrapper.calls == []
    assert controller.hold_down_calls == [("popup", 20000)]
    assert controller.screen_click_calls == []
    assert controller.screen_wheel_calls == []
    assert controller.screen_drag_calls == []


def test_page_down_raises_when_timeline_popup_missing() -> None:
    controller = _TestablePywinautoWechatController(
        descendants=[],
        search_box=None,
        timeline_popup_window=None,
    )

    with pytest.raises(RuntimeError, match="timeline popup missing"):
        controller.page_down()


def test_detect_page_state_prefers_timeline_popup() -> None:
    popup = _FakeWindow(width=576, height=558, left=1739, top=40)
    controller = _TestablePywinautoWechatController(
        descendants=[],
        search_box=None,
        timeline_popup_window=popup,
    )

    assert controller.detect_page_state() is WarmupPageState.TIMELINE_POPUP


def test_detect_page_state_accepts_recovery_search_ready_override() -> None:
    controller = _TestablePywinautoWechatController(
        descendants=[],
        search_box=None,
    )
    controller._recovery_search_ready = True

    assert controller.detect_page_state() is WarmupPageState.SEARCH_READY


def test_force_recover_to_searchable_page_calls_recovery_steps(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    controller = _TestablePywinautoWechatController(descendants=[], search_box=None)
    calls: list[str] = []
    monkeypatch.setattr(
        controller,
        "ensure_wechat_window",
        lambda: calls.append("ensure_window"),
    )

    monkeypatch.setattr(
        controller,
        "_close_timeline_popup_if_present",
        lambda: calls.append("close_popup"),
    )
    monkeypatch.setattr(
        controller,
        "_prime_search_input",
        lambda: calls.append("prime_search"),
    )
    monkeypatch.setattr(
        controller,
        "detect_page_state",
        lambda: WarmupPageState.SEARCH_READY,
    )

    assert controller.force_recover_to_searchable_page() is True
    assert calls == ["ensure_window", "close_popup", "prime_search"]


def test_pywinauto_controller_wraps_type_keys_errors_as_runtime_error() -> None:
    wrapper = _FakeWrapper(fail_on_type_keys=True)

    with pytest.raises(RuntimeError):
        PywinautoWechatController._type_keys(wrapper, "^f")


def test_pywinauto_controller_wraps_click_errors_as_runtime_error() -> None:
    wrapper = _FakeWrapper(fail_on_click=True)

    with pytest.raises(RuntimeError):
        PywinautoWechatController._safe_click(wrapper)

def test_open_search_uses_safe_window_hot_area_when_search_box_not_exposed() -> None:
    controller = _TestablePywinautoWechatController(
        descendants=[],
        search_box=None,
        search_box_states=[None, None],
    )

    controller.open_search("contacts")

    assert controller._search_input_mode == "window"
    assert controller._window.wrapper.calls == [
        ("window_click", ((155, 56), False)),
        ("type_keys", "^f"),
    ]


def test_open_search_confirms_search_box_after_hot_area_click() -> None:
    controller = _TestablePywinautoWechatController(
        descendants=[],
        search_box=None,
        search_box_states=[None],
    )
    controller._search_box_states.append(controller._window)

    controller.open_search("contacts")

    assert controller._search_input_mode == "control"
    assert controller._window.wrapper.calls == [
        ("window_click", ((155, 56), False)),
        ("window_click", (None, False)),
    ]


def test_input_search_text_raises_when_search_mode_not_confirmed() -> None:
    controller = _TestablePywinautoWechatController(descendants=[], search_box=None)

    with pytest.raises(RuntimeError):
        controller.input_search_text("target")


def test_input_search_text_uses_paste_not_direct_typing() -> None:
    search_box = _FakeElement(control_type="Edit", text="target", left=80, top=40, width=160, height=36)
    controller = _TestablePywinautoWechatController(descendants=[], search_box=None)
    controller._search_input_mode = "control"
    controller._search_box_states = [search_box]
    controller.clipboard_copy_result = "target"

    controller.input_search_text("target")

    assert controller.clipboard_text_calls == ["target"]
    assert search_box.wrapper.calls == [
        ("type_keys", "^a{BACKSPACE}"),
        ("type_keys", "^v"),
    ]


def test_input_search_text_raises_when_verified_text_does_not_match_expected() -> None:
    controller = _TestablePywinautoWechatController(descendants=[], search_box=None)
    controller._search_input_mode = "control"
    controller._search_box_states = [controller._window]
    controller.clipboard_copy_result = "????"

    with pytest.raises(RuntimeError):
        controller.input_search_text("target")


def test_input_search_text_raises_when_clipboard_still_contains_expected_but_control_text_is_empty() -> None:
    search_box = _FakeElement(control_type="Edit", text="", left=80, top=40, width=160, height=36)
    controller = _TestablePywinautoWechatController(descendants=[], search_box=None)
    controller._search_input_mode = "control"
    controller._search_box_states = [search_box]
    controller.clipboard_copy_result = None

    with pytest.raises(RuntimeError, match="search text verification failed"):
        controller.input_search_text("target")


def test_input_search_text_accepts_window_mode_when_results_popup_appears() -> None:
    popup = _FakeWindow(width=460, height=565, left=69, top=79)
    controller = _TestablePywinautoWechatController(
        descendants=[],
        search_box=None,
        search_results_popup_window=popup,
    )
    controller._search_input_mode = "window"

    controller.input_search_text("target")
def test_select_contact_uses_first_search_result_safe_area_when_exact_item_missing() -> None:
    controller = _TestablePywinautoWechatController(descendants=[], search_box=object())

    controller.select_contact("寮犱笁")

    assert controller._window.wrapper.calls == [("window_click", ((168, 112), False))]


def test_select_contact_uses_enter_when_search_results_popup_is_available() -> None:
    popup = _FakeWindow(width=460, height=565, left=69, top=79)
    controller = _TestablePywinautoWechatController(
        descendants=[],
        search_box=object(),
        search_results_popup_states=[popup, None],
    )

    controller.select_contact("寮犱笁")

    assert popup.wrapper.calls == []
    assert controller._window.wrapper.calls == [("type_keys", "{ENTER}")]


def test_select_contact_allows_enter_fallback_without_selection_verification() -> None:
    popup = _FakeWindow(width=460, height=565, left=69, top=79)
    controller = _TestablePywinautoWechatController(
        descendants=[],
        search_box=object(),
        search_results_popup_states=[popup, popup],
    )

    controller.select_contact("寮犱笁")

    assert controller._window.wrapper.calls == [("type_keys", "{ENTER}")]


def test_find_search_results_popup_window_detects_toolsavebits_descendant() -> None:
    popup = _FakeElement(
        control_type="Pane",
        text="Weixin",
        left=69,
        top=79,
        width=460,
        height=565,
        class_name="Qt51514QWindowToolSaveBits",
    )
    controller = _TestablePywinautoWechatController(
        descendants=[popup],
        search_box=object(),
    )

    found = PywinautoWechatController._find_search_results_popup_window(controller)

    assert found is popup


def test_open_timeline_uses_chat_menu_then_avatar_then_moments_area() -> None:
    timeline_entry = _FakeElement(
        control_type="Text",
        text="朋友圈",
        left=760,
        top=300,
        width=72,
        height=30,
    )
    controller = _TestablePywinautoWechatController(
        descendants=[timeline_entry],
        search_box=object(),
        popup_after_screen_click_indices={1},
    )

    controller.open_timeline()

    assert controller._window.wrapper.calls == [
        ("window_click", ((1248, 49), False)),
        ("window_click", ((1074, 112), False)),
    ]
    assert len(controller.screen_click_calls) == 1


def test_open_timeline_retries_candidate_points_from_timeline_entry_until_popup_opens() -> None:
    timeline_entry = _FakeElement(
        control_type="Text",
        text="朋友圈",
        left=760,
        top=300,
        width=72,
        height=30,
    )
    controller = _TestablePywinautoWechatController(
        descendants=[timeline_entry],
        search_box=object(),
        popup_after_screen_click_indices={3},
    )

    controller.open_timeline()

    assert controller._window.wrapper.calls == [
        ("window_click", ((1248, 49), False)),
        ("window_click", ((1074, 112), False)),
        ("window_click", ((1248, 49), False)),
        ("window_click", ((1074, 112), False)),
    ]
    assert len(controller.screen_click_calls) == 3
    assert len(set(controller.screen_click_calls)) == 3
    assert controller._find_timeline_popup_window() is not None


def test_open_timeline_raises_when_all_timeline_entry_candidates_fail_to_open_popup() -> None:
    timeline_entry = _FakeElement(
        control_type="Text",
        text="朋友圈",
        left=760,
        top=300,
        width=72,
        height=30,
    )
    controller = _TestablePywinautoWechatController(
        descendants=[timeline_entry],
        search_box=object(),
    )

    with pytest.raises(RuntimeError, match="timeline popup missing"):
        controller.open_timeline()

    assert len(controller.screen_click_calls) == 6
    assert controller._window.wrapper.calls == [
        ("window_click", ((1248, 49), False)),
        ("window_click", ((1074, 112), False)),
        ("window_click", ((1248, 49), False)),
        ("window_click", ((1074, 112), False)),
        ("window_click", ((1248, 49), False)),
        ("window_click", ((1074, 112), False)),
    ]
    assert controller._find_timeline_popup_window() is None


def test_open_timeline_falls_back_to_visual_preview_bbox_when_timeline_text_not_found() -> None:
    controller = _TestablePywinautoWechatController(
        descendants=[],
        search_box=object(),
        media_row_bbox=(910, 320, 1040, 360),
        popup_after_screen_click_indices={1},
    )

    controller.open_timeline()

    assert controller._window.wrapper.calls == [
        ("window_click", ((1248, 49), False)),
        ("window_click", ((1074, 112), False)),
    ]
    assert controller.screen_click_calls == [(975, 340)]
    assert controller._find_timeline_popup_window() is not None


def test_find_wechat_window_prefers_main_window_over_tool_save_bits(monkeypatch: pytest.MonkeyPatch) -> None:
    class _FakeWechatWindow:
        def __init__(self, *, width: int, height: int, class_name: str) -> None:
            self._rect = _FakeRect(left=0, top=0, width=width, height=height)
            self.element_info = type("ElementInfo", (), {"class_name": class_name})()

        def rectangle(self) -> _FakeRect:
            return self._rect

    window_map = {
        1: _FakeWechatWindow(width=328, height=619, class_name="Qt51514QWindowToolSaveBits"),
        2: _FakeWechatWindow(width=1294, height=703, class_name="Qt51514QWindowIcon"),
    }

    class _FakeApp:
        def __init__(self, backend: str) -> None:
            assert backend == "uia"
            self._handle: int | None = None

        def connect(self, *, handle: int):
            self._handle = handle
            return self

        def window(self, *, handle: int):
            assert handle == self._handle
            return window_map[handle]

    monkeypatch.setattr(
        PywinautoWechatController,
        "_iter_visible_windows",
        staticmethod(lambda: [(1, "Weixin"), (2, "微信")]),
    )
    monkeypatch.setattr(wechat_ui_adapter_module, "Application", _FakeApp)

    controller = PywinautoWechatController()

    assert controller._find_wechat_window() is window_map[2]


def test_find_wechat_window_prefers_qt_main_window_over_larger_chrome_shell(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _FakeWechatWindow:
        def __init__(self, *, width: int, height: int, class_name: str) -> None:
            self._rect = _FakeRect(left=0, top=0, width=width, height=height)
            self.element_info = type("ElementInfo", (), {"class_name": class_name})()

        def rectangle(self) -> _FakeRect:
            return self._rect

    window_map = {
        1: _FakeWechatWindow(width=1151, height=1020, class_name="Chrome_WidgetWin_0"),
        2: _FakeWechatWindow(width=976, height=1028, class_name="Qt51514QWindowIcon"),
    }

    class _FakeApp:
        def __init__(self, backend: str) -> None:
            assert backend == "uia"
            self._handle: int | None = None

        def connect(self, *, handle: int):
            self._handle = handle
            return self

        def window(self, *, handle: int):
            assert handle == self._handle
            return window_map[handle]

    monkeypatch.setattr(
        PywinautoWechatController,
        "_iter_visible_windows",
        staticmethod(lambda: [(1, "微信"), (2, "微信")]),
    )
    monkeypatch.setattr(wechat_ui_adapter_module, "Application", _FakeApp)

    controller = PywinautoWechatController()

    assert controller._find_wechat_window() is window_map[2]


def test_find_search_box_rejects_lower_chat_input_edit_control() -> None:
    chat_input = _FakeElement(
        control_type="Edit",
        text="",
        left=420,
        top=760,
        width=520,
        height=120,
        automation_id="chat_input",
        class_name="Edit",
    )
    controller = _TestablePywinautoWechatController(descendants=[chat_input], search_box=None)

    assert controller._find_search_box() is None


def test_find_search_box_prefers_top_left_search_candidate() -> None:
    search_box = _FakeElement(
        control_type="Edit",
        text="鎼滅储",
        left=36,
        top=72,
        width=220,
        height=36,
        automation_id="search",
        class_name="SearchBox",
    )
    chat_input = _FakeElement(
        control_type="Edit",
        text="",
        left=420,
        top=760,
        width=520,
        height=120,
        automation_id="chat_input",
        class_name="Edit",
    )
    controller = _TestablePywinautoWechatController(
        descendants=[chat_input, search_box],
        search_box=None,
    )

    assert controller._find_search_box() is search_box

