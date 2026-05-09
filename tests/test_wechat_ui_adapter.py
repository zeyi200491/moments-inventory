from dataclasses import dataclass

import pytest

from moments_inventory import wechat_ui_adapter
from moments_inventory.wechat_ui_adapter import (
    PywinautoKeyboardController,
    WeChatWarmupAdapter,
)


@dataclass(slots=True)
class FakeWarmupUiSettings:
    search_delay_ms: int = 800
    open_profile_delay_ms: int = 1000
    open_timeline_delay_ms: int = 1200
    scroll_count: int = 3
    scroll_delay_ms: int = 900
    back_delay_ms: int = 600


class FakeKeyboardController:
    def __init__(
        self,
        has_window: bool = True,
        fail_calls: set[tuple[str, str | int | None]] | None = None,
        failure_exception: type[Exception] = RuntimeError,
    ) -> None:
        self.has_window = has_window
        self.fail_calls = fail_calls or set()
        self.failure_exception = failure_exception
        self.calls: list[tuple[str, str | int | None]] = []

    def _record_call(self, method: str, value: str | int | None) -> None:
        call = (method, value)
        self.calls.append(call)
        if call in self.fail_calls:
            raise self.failure_exception("模拟键盘流程失败")

    def ensure_wechat_window(self) -> None:
        self._record_call("ensure_wechat_window", None)
        if not self.has_window:
            raise RuntimeError("未找到微信窗口")

    def send_hotkey(self, keys: str) -> None:
        self._record_call("send_hotkey", keys)

    def type_text(self, text: str) -> None:
        self._record_call("type_text", text)

    def press_key(self, key: str) -> None:
        self._record_call("press_key", key)

    def sleep_ms(self, milliseconds: int) -> None:
        self._record_call("sleep_ms", milliseconds)


def test_prepare_and_warmup_contact_run_expected_keyboard_sequence() -> None:
    controller = FakeKeyboardController()
    settings = FakeWarmupUiSettings()
    adapter = WeChatWarmupAdapter(settings=settings, controller=controller)

    adapter.prepare("contacts")

    assert adapter.warmup_contact("张三") is True
    assert controller.calls == [
        ("ensure_wechat_window", None),
        ("send_hotkey", "^f"),
        ("sleep_ms", 800),
        ("type_text", "张三"),
        ("press_key", "ENTER"),
        ("sleep_ms", 1000),
        ("send_hotkey", "%~"),
        ("sleep_ms", 1000),
        ("press_key", "ENTER"),
        ("sleep_ms", 1200),
        ("press_key", "PGDN"),
        ("sleep_ms", 900),
        ("press_key", "PGDN"),
        ("sleep_ms", 900),
        ("press_key", "PGDN"),
        ("sleep_ms", 900),
        ("press_key", "ESC"),
        ("sleep_ms", 600),
        ("press_key", "ESC"),
        ("sleep_ms", 600),
    ]


def test_prepare_stores_runtime_start_page_state_with_minimal_settings() -> None:
    adapter = WeChatWarmupAdapter(
        settings=FakeWarmupUiSettings(),
        controller=FakeKeyboardController(),
    )

    adapter.prepare("chat_list")

    assert adapter._prepared_start_page == "chat_list"


def test_prepare_raises_when_wechat_window_is_missing() -> None:
    controller = FakeKeyboardController(has_window=False)
    adapter = WeChatWarmupAdapter(
        settings=FakeWarmupUiSettings(),
        controller=controller,
    )

    with pytest.raises(RuntimeError, match="未找到微信窗口"):
        adapter.prepare("contacts")


def test_prepare_raises_when_start_page_is_invalid() -> None:
    adapter = WeChatWarmupAdapter(
        settings=FakeWarmupUiSettings(),
        controller=FakeKeyboardController(),
    )

    with pytest.raises(RuntimeError, match="不支持的起始页"):
        adapter.prepare("timeline")


def test_warmup_contact_raises_when_prepare_has_not_been_called() -> None:
    adapter = WeChatWarmupAdapter(
        settings=FakeWarmupUiSettings(),
        controller=FakeKeyboardController(),
    )

    with pytest.raises(RuntimeError, match="尚未调用 prepare"):
        adapter.warmup_contact("张三")


def test_warmup_contact_returns_false_and_runs_best_effort_escape_on_runtime_error() -> None:
    controller = FakeKeyboardController(fail_calls={("press_key", "ENTER")})
    adapter = WeChatWarmupAdapter(
        settings=FakeWarmupUiSettings(),
        controller=controller,
    )
    adapter.prepare("contacts")

    assert adapter.warmup_contact("张三") is False
    assert controller.calls[-4:] == [
        ("press_key", "ESC"),
        ("sleep_ms", 600),
        ("press_key", "ESC"),
        ("sleep_ms", 600),
    ]


def test_warmup_contact_returns_false_and_runs_best_effort_escape_on_value_error() -> None:
    controller = FakeKeyboardController(
        fail_calls={("press_key", "ENTER")},
        failure_exception=ValueError,
    )
    adapter = WeChatWarmupAdapter(
        settings=FakeWarmupUiSettings(),
        controller=controller,
    )
    adapter.prepare("contacts")

    assert adapter.warmup_contact("张三") is False
    assert controller.calls[-4:] == [
        ("press_key", "ESC"),
        ("sleep_ms", 600),
        ("press_key", "ESC"),
        ("sleep_ms", 600),
    ]


def test_best_effort_go_back_does_not_raise_when_cleanup_sleep_hits_value_error() -> None:
    controller = FakeKeyboardController(
        fail_calls={
            ("send_hotkey", "%~"),
            ("sleep_ms", 600),
        },
        failure_exception=ValueError,
    )
    adapter = WeChatWarmupAdapter(
        settings=FakeWarmupUiSettings(),
        controller=controller,
    )
    adapter.prepare("contacts")

    assert adapter.warmup_contact("张三") is False
    assert ("sleep_ms", 600) in controller.calls
    assert controller.calls.count(("press_key", "ESC")) == 2


@pytest.mark.parametrize(
    ("method_name", "args"),
    [
        ("send_hotkey", ("^f",)),
        ("type_text", ("张三",)),
        ("press_key", ("ENTER",)),
    ],
)
def test_pywinauto_controller_wraps_send_keys_errors_as_runtime_error(
    monkeypatch: pytest.MonkeyPatch,
    method_name: str,
    args: tuple[str, ...],
) -> None:
    controller = PywinautoKeyboardController()

    def fake_send_keys(*_args: object, **_kwargs: object) -> None:
        raise ValueError("底层异常")

    monkeypatch.setattr(wechat_ui_adapter, "send_keys", fake_send_keys)

    with pytest.raises(RuntimeError, match="微信按键操作失败"):
        getattr(controller, method_name)(*args)
