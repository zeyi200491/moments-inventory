from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Protocol

from pywinauto import Application, Desktop
from pywinauto.keyboard import send_keys


class WarmupUiSettings(Protocol):
    search_delay_ms: int
    open_profile_delay_ms: int
    open_timeline_delay_ms: int
    scroll_count: int
    scroll_delay_ms: int
    back_delay_ms: int


class KeyboardController(Protocol):
    def ensure_wechat_window(self) -> None:
        ...

    def send_hotkey(self, keys: str) -> None:
        ...

    def type_text(self, text: str) -> None:
        ...

    def press_key(self, key: str) -> None:
        ...

    def sleep_ms(self, milliseconds: int) -> None:
        ...


class PywinautoKeyboardController:
    def ensure_wechat_window(self) -> None:
        window = self._find_wechat_window()
        if window is None:
            raise RuntimeError("未找到微信窗口")
        window.set_focus()

    def send_hotkey(self, keys: str) -> None:
        self._send_keys(keys)

    def type_text(self, text: str) -> None:
        self._send_keys(text, with_spaces=True, pause=0.02)

    def press_key(self, key: str) -> None:
        self._send_keys(f"{{{key}}}")

    def sleep_ms(self, milliseconds: int) -> None:
        time.sleep(milliseconds / 1000)

    def _find_wechat_window(self):
        try:
            windows = Application(backend="uia").connect(title_re=".*(微信|WeChat).*").windows()
        except Exception:
            windows = []

        if windows:
            return windows[0]

        try:
            for window in Desktop(backend="uia").windows():
                title = window.window_text()
                if title in {"微信", "WeChat"}:
                    return window
        except Exception as exc:
            raise RuntimeError("查找微信窗口失败") from exc

        return None

    def _send_keys(self, *args: object, **kwargs: object) -> None:
        try:
            send_keys(*args, **kwargs)
        except Exception as exc:
            raise RuntimeError("微信按键操作失败") from exc


@dataclass(slots=True)
class WeChatWarmupAdapter:
    settings: WarmupUiSettings
    controller: KeyboardController
    _prepared_start_page: str | None = field(init=False, default=None)

    def prepare(self, start_page: str) -> None:
        if start_page not in {"contacts", "chat_list"}:
            raise RuntimeError(f"不支持的起始页: {start_page}")
        self.controller.ensure_wechat_window()
        self._prepared_start_page = start_page

    def warmup_contact(self, remark_name: str) -> bool:
        if self._prepared_start_page is None:
            raise RuntimeError("尚未调用 prepare")

        try:
            self._open_contact_search()
            self.controller.sleep_ms(self.settings.search_delay_ms)
            self.controller.type_text(remark_name)
            self.controller.press_key("ENTER")
            self.controller.sleep_ms(self.settings.open_profile_delay_ms)
            self.controller.send_hotkey("%~")
            self.controller.sleep_ms(self.settings.open_profile_delay_ms)
            self.controller.press_key("ENTER")
            self.controller.sleep_ms(self.settings.open_timeline_delay_ms)

            for _ in range(self.settings.scroll_count):
                self.controller.press_key("PGDN")
                self.controller.sleep_ms(self.settings.scroll_delay_ms)

            self._best_effort_go_back()
            return True
        except Exception:
            self._best_effort_go_back()
            return False

    def _open_contact_search(self) -> None:
        if self._prepared_start_page in {"contacts", "chat_list"}:
            self.controller.send_hotkey("^f")
            return
        raise RuntimeError("尚未准备有效的起始页")

    def _best_effort_go_back(self) -> None:
        for _ in range(2):
            try:
                self.controller.press_key("ESC")
            except Exception:
                continue

            try:
                self.controller.sleep_ms(self.settings.back_delay_ms)
            except Exception:
                continue
