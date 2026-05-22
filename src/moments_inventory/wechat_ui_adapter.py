from __future__ import annotations

import ctypes
import time
from dataclasses import dataclass, field
from typing import Protocol

import win32clipboard
from PIL import ImageGrab
from pywinauto import Application, Desktop

from moments_inventory.warmup_state import (
    WarmupContactDiagnostics,
    WarmupPageState,
    WarmupStepResult,
    WarmupStepStatus,
)


class WarmupUiSettings(Protocol):
    search_delay_ms: int
    open_profile_delay_ms: int
    open_timeline_delay_ms: int
    timeline_sync_wait_ms: int
    scroll_count: int
    scroll_delay_ms: int
    back_delay_ms: int
    force_recovery_on_reset_failure: bool


class WarmupController(Protocol):
    def ensure_wechat_window(self) -> None:
        ...

    def open_search(self, start_page: str) -> None:
        ...

    def input_search_text(self, text: str) -> None:
        ...

    def select_contact(self, remark_name: str) -> None:
        ...

    def open_timeline(self) -> None:
        ...

    def page_down(self) -> None:
        ...

    def reset_to_searchable_page(self, back_delay_ms: int) -> None:
        ...

    def detect_page_state(self) -> WarmupPageState:
        ...

    def force_recover_to_searchable_page(self) -> bool:
        ...

    def sleep_ms(self, milliseconds: int) -> None:
        ...


class PywinautoWechatController:
    _TIMELINE_HOLD_DOWN_MS = 20_000

    def __init__(self) -> None:
        self._window = None
        self._search_input_mode: str | None = None
        self._last_timeline_launch_point: tuple[int, int] | None = None
        self._timeline_popup_window = None
        self._recovery_search_ready = False

    def ensure_wechat_window(self) -> None:
        window = self._find_wechat_window()
        if window is None:
            raise RuntimeError("window missing")
        try:
            if window.is_minimized():
                window.restore()
        except Exception:
            pass
        window.set_focus()
        self._window = window
        self._search_input_mode = None
        self._last_timeline_launch_point = None
        self._timeline_popup_window = None
        self._recovery_search_ready = False

    def open_search(self, start_page: str) -> None:
        if start_page not in {"contacts", "chat_list"}:
            raise RuntimeError(f"unsupported start page: {start_page}")
        self._recovery_search_ready = False

        search_box = self._find_search_box()
        if search_box is not None:
            self._safe_click(search_box)
            self._search_input_mode = "control"
            return

        self._click_search_hot_area()
        time.sleep(0.25)
        search_box = self._find_search_box()
        if search_box is None:
            self._type_keys(self._require_window(), "^f")
            time.sleep(0.15)
            self._search_input_mode = "window"
            return
        self._safe_click(search_box)
        self._search_input_mode = "control"
    def input_search_text(self, text: str) -> None:
        self._recovery_search_ready = False
        target = None
        if self._search_input_mode == "control":
            target = self._find_search_box()
        elif self._search_input_mode == "window":
            target = self._require_window()

        if target is None:
            raise RuntimeError("search box not confirmed")
        self._type_keys(target, "^a{BACKSPACE}")
        self._set_clipboard_text(text)
        self._type_keys(target, "^v")
        self._assert_search_text_matches(target, text)

    def select_contact(self, remark_name: str) -> None:
        self._recovery_search_ready = False
        contact_item = self._find_contact_item(remark_name)
        if contact_item is not None:
            self._safe_click(contact_item)
            return

        if self._find_search_results_popup_window() is not None:
            self._type_keys(self._require_window(), "{ENTER}")
            time.sleep(0.25)
            return

        self._click_first_search_result()

    def open_timeline(self) -> None:
        self._recovery_search_ready = False
        tried_points: set[tuple[int, int]] = set()
        for _attempt in range(3):
            self._open_profile_details_page()
            timeline_entry = self._find_timeline_entry()
            if timeline_entry is not None and self._click_timeline_preview_hot_area(
                timeline_entry, tried_points, limit=2
            ):
                return
            if self._click_timeline_preview_visual_fallback(tried_points):
                return
        raise RuntimeError("timeline popup missing")

    def page_down(self) -> None:
        timeline_window = self._find_timeline_popup_window()
        if timeline_window is not None:
            self._hold_down_arrow(timeline_window, self._TIMELINE_HOLD_DOWN_MS)
            return
        raise RuntimeError("timeline popup missing")

    def reset_to_searchable_page(self, back_delay_ms: int) -> None:
        timeline_window = self._find_timeline_popup_window()
        if timeline_window is not None:
            self._send_escape(timeline_window)
            self._timeline_popup_window = None
        self.sleep_ms(back_delay_ms)

    def detect_page_state(self) -> WarmupPageState:
        if self._find_timeline_popup_window() is not None:
            return WarmupPageState.TIMELINE_POPUP
        if self._find_search_box() is not None:
            return WarmupPageState.SEARCH_READY
        if self._find_timeline_entry() is not None:
            return WarmupPageState.PROFILE_READY
        if self._recovery_search_ready:
            return WarmupPageState.SEARCH_READY
        return WarmupPageState.UNKNOWN

    def force_recover_to_searchable_page(self) -> bool:
        self.ensure_wechat_window()
        self._close_timeline_popup_if_present()
        self._prime_search_input()
        self._recovery_search_ready = self._search_input_mode in {"control", "window"}
        return self.detect_page_state() is WarmupPageState.SEARCH_READY

    def sleep_ms(self, milliseconds: int) -> None:
        time.sleep(milliseconds / 1000)

    def _require_window(self):
        if self._window is None:
            raise RuntimeError("window not ready")
        return self._window

    def _find_wechat_window(self):
        candidates: list[tuple[int, object]] = []
        for handle, title in self._iter_visible_windows():
            if "微信" not in title and "WeChat" not in title and "Weixin" not in title:
                continue
            try:
                app = Application(backend="uia").connect(handle=handle)
                window = app.window(handle=handle)
                rect = window.rectangle()
                width = int(rect.width())
                height = int(rect.height())
                class_name = str(getattr(window.element_info, "class_name", "") or "")
                if "ToolSaveBits" in class_name:
                    continue
                score = width * height
                if "Qt51514QWindowIcon" in class_name:
                    score += 10**9
                elif "Chrome_WidgetWin_0" in class_name:
                    score -= 10**8
                candidates.append((score, window))
            except Exception:
                continue

        if candidates:
            candidates.sort(key=lambda item: item[0], reverse=True)
            return candidates[0][1]

        try:
            desktop_candidates: list[tuple[int, object]] = []
            for window in Desktop(backend="uia").windows():
                title = window.window_text()
                if title not in {"微信", "WeChat", "Weixin"}:
                    continue
                rect = window.rectangle()
                width = int(rect.width())
                height = int(rect.height())
                class_name = str(getattr(window.element_info, "class_name", "") or "")
                if "ToolSaveBits" in class_name:
                    continue
                score = width * height
                if "Qt51514QWindowIcon" in class_name:
                    score += 10**9
                elif "Chrome_WidgetWin_0" in class_name:
                    score -= 10**8
                desktop_candidates.append((score, window))
            if desktop_candidates:
                desktop_candidates.sort(key=lambda item: item[0], reverse=True)
                return desktop_candidates[0][1]
        except Exception as exc:
            raise RuntimeError("find wechat window failed") from exc

        return None

    @staticmethod
    def _iter_visible_windows() -> list[tuple[int, str]]:
        user32 = ctypes.windll.user32
        windows: list[tuple[int, str]] = []

        enum_windows_proc = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)

        def collect(hwnd, _lparam):
            if not user32.IsWindowVisible(hwnd):
                return True
            length = user32.GetWindowTextLengthW(hwnd)
            if length <= 0:
                return True
            buffer = ctypes.create_unicode_buffer(length + 1)
            user32.GetWindowTextW(hwnd, buffer, length + 1)
            title = buffer.value.strip()
            if title:
                windows.append((int(hwnd), title))
            return True

        user32.EnumWindows(enum_windows_proc(collect), 0)
        return windows

    def _iter_descendants(self):
        window = self._require_window()
        roots = [window]
        try:
            roots.extend(window.children())
        except Exception:
            pass

        seen = set()
        for root in roots:
            try:
                descendants = root.descendants(depth=8)
            except Exception:
                descendants = []
            for descendant in descendants:
                handle = getattr(descendant.element_info, "handle", None)
                key = (handle, descendant.element_info.control_type, descendant.element_info.automation_id)
                if key in seen:
                    continue
                seen.add(key)
                yield descendant

    def _find_search_box(self):
        keyword_candidates: list[tuple[int, int, object]] = []
        region_candidates: list[tuple[int, int, object]] = []

        for descendant in self._iter_descendants():
            info = descendant.element_info
            if info.control_type != "Edit":
                continue

            try:
                rect = descendant.rectangle()
                left = int(rect.left)
                top = int(rect.top)
                width = int(rect.width())
                height = int(rect.height())
            except Exception:
                continue

            if width <= 0 or height <= 0:
                continue

            if left > 320 or top > 220:
                continue

            metadata = " ".join(
                part
                for part in (
                    self._window_text(descendant),
                    str(getattr(info, "name", "") or ""),
                    str(getattr(info, "automation_id", "") or ""),
                    str(getattr(info, "class_name", "") or ""),
                )
                if part
            ).lower()

            if any(keyword in metadata for keyword in ("鎼滅储", "search", "find")):
                keyword_candidates.append((top, left, descendant))
                continue

            if width >= 120 and height <= 80:
                region_candidates.append((top, left, descendant))

        if keyword_candidates:
            keyword_candidates.sort(key=lambda item: (item[0], item[1]))
            return keyword_candidates[0][2]

        if region_candidates:
            region_candidates.sort(key=lambda item: (item[0], item[1]))
            return region_candidates[0][2]

        return None

    def _click_search_hot_area(self) -> None:
        window = self._require_window()
        x, y = self._search_hot_area_coords()
        self._window_click(window, x, y)

    def _click_first_search_result(self) -> None:
        window = self._find_search_results_popup_window() or self._require_window()
        x, y = self._first_search_result_coords()
        self._window_click(window, x, y)

    def _search_hot_area_coords(self) -> tuple[int, int]:
        window = self._require_window()
        rect = window.rectangle()
        width = int(rect.width())
        height = int(rect.height())
        if width <= 320 or height <= 180:
            raise RuntimeError("search box area unavailable")
        return max(80, int(width * 0.12)), max(48, int(height * 0.08))

    def _first_search_result_coords(self) -> tuple[int, int]:
        window = self._find_search_results_popup_window() or self._require_window()
        rect = window.rectangle()
        width = int(rect.width())
        height = int(rect.height())
        if width <= 320 or height <= 240:
            raise RuntimeError("first result area unavailable")
        if window is self._find_search_results_popup_window():
            return max(115, int(width * 0.25)), max(90, int(height * 0.16))
        return max(120, int(width * 0.13)), max(108, int(height * 0.16))

    def _chat_menu_hot_area_coords(self) -> tuple[int, int]:
        window = self._require_window()
        rect = window.rectangle()
        width = int(rect.width())
        height = int(rect.height())
        if width <= 480 or height <= 220:
            raise RuntimeError("chat menu area unavailable")
        return int(width * 0.965), max(40, int(height * 0.07))

    def _chat_menu_hot_area_candidates(self) -> list[tuple[int, int]]:
        window = self._require_window()
        rect = window.rectangle()
        width = int(rect.width())
        height = int(rect.height())
        if width <= 480 or height <= 220:
            raise RuntimeError("chat menu area unavailable")
        candidates = [
            (0.97, 0.09),
            (0.95, 0.09),
            (0.93, 0.07),
            (0.965, 0.07),
            (0.97, 0.07),
        ]
        resolved: list[tuple[int, int]] = []
        seen: set[tuple[int, int]] = set()
        for x_ratio, y_ratio in candidates:
            point = (
                min(max(0, int(width * x_ratio)), max(0, width - 1)),
                min(max(40, int(height * y_ratio)), max(0, height - 1)),
            )
            if point in seen:
                continue
            seen.add(point)
            resolved.append(point)
        return resolved

    def _profile_avatar_hot_area_coords(self) -> tuple[int, int]:
        window = self._require_window()
        rect = window.rectangle()
        width = int(rect.width())
        height = int(rect.height())
        if width <= 640 or height <= 260:
            raise RuntimeError("profile avatar area unavailable")
        return int(width * 0.83), max(108, int(height * 0.16))

    def _moments_hot_area_coords(self) -> tuple[int, int]:
        window = self._require_window()
        rect = window.rectangle()
        width = int(rect.width())
        height = int(rect.height())
        if width <= 760 or height <= 420:
            raise RuntimeError("moments entry area unavailable")
        return int(width * 0.691), int(height * 0.467)

    def _timeline_view_hot_area_coords(self) -> tuple[int, int]:
        window = self._require_window()
        rect = window.rectangle()
        width = int(rect.width())
        height = int(rect.height())
        if width <= 760 or height <= 420:
            raise RuntimeError("timeline view area unavailable")
        return int(width * 0.54), int(height * 0.40)

    def _timeline_scrollbar_drag_coords(self) -> tuple[int, int, int, int]:
        window = self._require_window()
        rect = window.rectangle()
        width = int(rect.width())
        height = int(rect.height())
        if width <= 760 or height <= 420:
            raise RuntimeError("timeline scrollbar area unavailable")
        x = int(width * 0.79)
        start_y = int(height * 0.21)
        end_y = int(height * 0.34)
        return x, start_y, x, end_y

    def _detect_timeline_preview_bbox(self) -> tuple[int, int, int, int] | None:
        window = self._require_window()
        rect = window.rectangle()
        width = int(rect.width())
        height = int(rect.height())
        if width <= 760 or height <= 420:
            return None

        bbox = (int(rect.left), int(rect.top), int(rect.right), int(rect.bottom))
        image = ImageGrab.grab(bbox=bbox, all_screens=True).convert("RGB")
        pixels = image.load()

        x0 = int(width * 0.63)
        x1 = int(width * 0.93)
        y0 = int(height * 0.44)
        y1 = int(height * 0.66)

        candidate_rows: list[tuple[int, int]] = []
        row_threshold = max(18, int((x1 - x0) * 0.08))
        for y in range(y0, y1):
            count = 0
            for x in range(x0, x1):
                if self._is_preview_candidate_pixel(*pixels[x, y]):
                    count += 1
            if count >= row_threshold:
                candidate_rows.append((y, count))

        if not candidate_rows:
            return None

        best_band = self._first_dense_band(candidate_rows, min_length=12)
        if best_band is None:
            return None
        band_y0, band_y1 = best_band

        candidate_cols: list[tuple[int, int]] = []
        col_threshold = max(8, int((band_y1 - band_y0 + 1) * 0.20))
        for x in range(x0, x1):
            count = 0
            for y in range(band_y0, band_y1 + 1):
                if self._is_preview_candidate_pixel(*pixels[x, y]):
                    count += 1
            if count >= col_threshold:
                candidate_cols.append((x, count))

        if not candidate_cols:
            return None

        best_col_band = self._largest_dense_band(candidate_cols, min_length=24)
        if best_col_band is None:
            return None
        band_x0, band_x1 = best_col_band
        return band_x0, band_y0, band_x1, band_y1

    def _detect_timeline_preview_bbox_by_panel_scan(self) -> tuple[int, int, int, int] | None:
        window = self._require_window()
        rect = window.rectangle()
        width = int(rect.width())
        height = int(rect.height())
        if width <= 760 or height <= 420:
            return None

        bbox = (
            int(rect.left),
            int(rect.top),
            int(rect.right),
            int(rect.bottom),
        )
        image = ImageGrab.grab(bbox=bbox, all_screens=True).convert("RGB")
        pixels = image.load()

        # 只扫描资料页中“朋友圈”缩略图区应出现的下半横带，避开上方“标签”区域。
        scan_x0 = int(width * 0.50)
        scan_x1 = int(width * 0.77)
        scan_y0 = int(height * 0.54)
        scan_y1 = int(height * 0.68)
        win_w = max(128, int(width * 0.14))
        win_h = max(36, int(height * 0.065))

        scored_windows: list[tuple[float, int, int]] = []
        for y in range(scan_y0, max(scan_y0, scan_y1 - win_h + 1), 4):
            for x in range(scan_x0, max(scan_x0, scan_x1 - win_w + 1), 4):
                score = self._score_preview_window(pixels, x, y, win_w, win_h)
                scored_windows.append((score, x, y))

        if not scored_windows:
            return None
        scored_windows.sort(reverse=True)
        best_score = scored_windows[0][0]
        if best_score < 2500:
            return None

        near_best = [
            item
            for item in scored_windows
            if item[0] >= best_score * 0.92
        ]
        _, best_x, best_y = min(near_best, key=lambda item: (item[2], -item[0], item[1]))

        return best_x, best_y, best_x + win_w, best_y + win_h

    def _detect_timeline_preview_bbox_from_media_rows(self) -> tuple[int, int, int, int] | None:
        window = self._require_window()
        rect = window.rectangle()
        width = int(rect.width())
        height = int(rect.height())
        if width <= 760 or height <= 420:
            return None

        bbox = (
            int(rect.left),
            int(rect.top),
            int(rect.right),
            int(rect.bottom),
        )
        image = ImageGrab.grab(bbox=bbox, all_screens=True).convert("RGB")
        pixels = image.load()

        # 只看资料页中媒体缩略图应出现的右半区域，并在多条媒体行中优先选择最靠上的一条。
        x0 = int(width * 0.60)
        x1 = int(width * 0.84)
        y0 = int(height * 0.40)
        y1 = int(height * 0.62)

        candidate_rows: list[tuple[int, int]] = []
        row_threshold = max(20, int((x1 - x0) * 0.10))
        for y in range(y0, y1):
            count = 0
            for x in range(x0, x1):
                if self._is_preview_candidate_pixel(*pixels[x, y]):
                    count += 1
            if count >= row_threshold:
                candidate_rows.append((y, count))

        if not candidate_rows:
            return None

        row_bands = self._dense_bands(candidate_rows, min_length=12)
        if not row_bands:
            return None

        candidates: list[tuple[int, int, int, int, int]] = []
        for band_y0, band_y1 in row_bands:
            candidate_cols: list[tuple[int, int]] = []
            col_threshold = max(8, int((band_y1 - band_y0 + 1) * 0.20))
            for x in range(x0, x1):
                count = 0
                for y in range(band_y0, band_y1 + 1):
                    if self._is_preview_candidate_pixel(*pixels[x, y]):
                        count += 1
                if count >= col_threshold:
                    candidate_cols.append((x, count))

            col_band = self._largest_dense_band(candidate_cols, min_length=42)
            if col_band is None:
                continue
            band_x0, band_x1 = col_band
            candidates.append((band_y0, band_y1, band_x0, band_x1, band_x1 - band_x0))

        if not candidates:
            return None

        best_y0, best_y1, best_x0, best_x1, _ = min(
            candidates,
            key=lambda item: (item[0], -item[4]),
        )
        return best_x0, best_y0, best_x1, best_y1

    @staticmethod
    def _score_preview_window(pixels, x0: int, y0: int, win_w: int, win_h: int) -> float:
        sample_count = 0
        sum_value = 0.0
        sum_value_sq = 0.0
        edges = 0
        nondark = 0

        for y in range(y0, y0 + win_h, 2):
            prev_value = None
            for x in range(x0, x0 + win_w, 2):
                r, g, b = pixels[x, y]
                value = (r + g + b) / 3
                sample_count += 1
                sum_value += value
                sum_value_sq += value * value
                if value > 55:
                    nondark += 1
                if prev_value is not None and abs(value - prev_value) > 18:
                    edges += 1
                prev_value = value

        if sample_count == 0:
            return 0.0

        mean_value = sum_value / sample_count
        variance = max(0.0, sum_value_sq / sample_count - mean_value * mean_value)
        return variance + edges * 6 + nondark * 0.4

    def _find_timeline_popup_window(self):
        if self._timeline_popup_window is not None:
            try:
                rect = self._timeline_popup_window.rectangle()
                if int(rect.width()) > 0 and int(rect.height()) > 0:
                    return self._timeline_popup_window
            except Exception:
                self._timeline_popup_window = None

        main_window = self._window
        main_rect = main_window.rectangle() if main_window is not None else None
        candidates: list[tuple[int, object]] = []
        for window in Desktop(backend="uia").windows():
            try:
                title = window.window_text()
                rect = window.rectangle()
                width = int(rect.width())
                height = int(rect.height())
                if width <= 0 or height <= 0:
                    continue
                if title != "朋友圈":
                    continue
                if main_rect is not None:
                    if int(rect.left) < int(main_rect.left) or int(rect.top) < int(main_rect.top):
                        continue
                    if int(rect.right) > int(main_rect.right) or int(rect.bottom) > int(main_rect.bottom):
                        continue
                candidates.append((width * height, window))
            except Exception:
                continue

        if not candidates:
            return None
        candidates.sort(key=lambda item: item[0], reverse=True)
        self._timeline_popup_window = candidates[0][1]
        return self._timeline_popup_window

    def _find_search_results_popup_window(self):
        main_window = self._window
        main_rect = main_window.rectangle() if main_window is not None else None
        candidates: list[tuple[int, object]] = []
        for descendant in self._iter_descendants():
            try:
                title = self._window_text(descendant)
                rect = descendant.rectangle()
                width = int(rect.width())
                height = int(rect.height())
                if width <= 0 or height <= 0:
                    continue
                class_name = str(getattr(descendant.element_info, "class_name", "") or "")
                if "ToolSaveBits" not in class_name:
                    continue
                if title not in {"Weixin", "微信"}:
                    continue
                if main_rect is not None:
                    if int(rect.left) < int(main_rect.left) or int(rect.top) < int(main_rect.top):
                        continue
                    if int(rect.right) > int(main_rect.right) or int(rect.bottom) > int(main_rect.bottom):
                        continue
                candidates.append((width * height, descendant))
            except Exception:
                continue

        if candidates:
            candidates.sort(key=lambda item: item[0], reverse=True)
            return candidates[0][1]

        candidates = []
        for window in Desktop(backend="uia").windows():
            try:
                title = window.window_text()
                rect = window.rectangle()
                width = int(rect.width())
                height = int(rect.height())
                if width <= 0 or height <= 0:
                    continue
                class_name = str(getattr(window.element_info, "class_name", "") or "")
                if "ToolSaveBits" not in class_name:
                    continue
                if title not in {"Weixin", "微信"}:
                    continue
                if main_rect is not None:
                    if int(rect.left) < int(main_rect.left) or int(rect.top) < int(main_rect.top):
                        continue
                    if int(rect.right) > int(main_rect.right) or int(rect.bottom) > int(main_rect.bottom):
                        continue
                candidates.append((width * height, window))
            except Exception:
                continue

        if not candidates:
            return None
        candidates.sort(key=lambda item: item[0], reverse=True)
        return candidates[0][1]

    def _timeline_scrollbar_track_bottom_right_coords(self, window=None) -> tuple[int, int]:
        window = window or self._require_window()
        rect = window.rectangle()
        width = int(rect.width())
        height = int(rect.height())
        if width <= 760 or height <= 420:
            if width <= 240 or height <= 240:
                raise RuntimeError("timeline track area unavailable")
        if self._find_timeline_popup_window() is window:
            return max(0, width - 15), max(0, height - 9)
        return int(width * 0.814), int(height * 0.947)

    def _timeline_close_hot_area_coords(self, window=None) -> tuple[int, int]:
        window = window or self._require_window()
        rect = window.rectangle()
        width = int(rect.width())
        height = int(rect.height())
        if width <= 760 or height <= 420:
            if width <= 240 or height <= 240:
                raise RuntimeError("timeline close area unavailable")
        if self._find_timeline_popup_window() is window:
            return max(0, width - 22), 20
        return int(width * 0.77), max(23, int(height * 0.034))

    def _hold_down_arrow(self, window, duration_ms: int) -> None:
        user32 = ctypes.windll.user32
        vk_down = 0x28
        try:
            window.set_focus()
        except Exception:
            pass
        try:
            # 直接“按下 20 秒再松开”对 Qt 窗口不一定会触发稳定的自动连发，
            # 这里改成在给定时长内持续发送向下键，模拟真实长按后的连续下滑。
            end_time = time.monotonic() + (duration_ms / 1000)
            initial_delay = 0.35
            repeat_interval = 0.03
            keyeventf_keyup = 0x0002

            user32.keybd_event(vk_down, 0, 0, 0)
            user32.keybd_event(vk_down, 0, keyeventf_keyup, 0)
            time.sleep(initial_delay)

            while time.monotonic() < end_time:
                user32.keybd_event(vk_down, 0, 0, 0)
                user32.keybd_event(vk_down, 0, keyeventf_keyup, 0)
                time.sleep(repeat_interval)
        except Exception as exc:
            raise RuntimeError("hold down arrow failed") from exc

    def _send_escape(self, window) -> None:
        try:
            window.set_focus()
        except Exception:
            pass
        self._type_keys(window, "{ESC}")

    def _close_timeline_popup_if_present(self) -> None:
        timeline_window = self._find_timeline_popup_window()
        if timeline_window is None:
            return
        self._send_escape(timeline_window)
        self._timeline_popup_window = None

    def _return_to_chat_home(self) -> None:
        window = self._require_window()
        self._send_escape(window)
        self.sleep_ms(300)

    def _prime_search_input(self) -> None:
        self.open_search("contacts")
        self.sleep_ms(200)

    def _click_chat_menu_hot_area(self) -> None:
        window = self._require_window()
        x, y = self._chat_menu_hot_area_coords()
        self._window_click(window, x, y)

    def _click_profile_avatar_hot_area(self) -> None:
        window = self._require_window()
        x, y = self._profile_avatar_hot_area_coords()
        self._window_click(window, x, y)

    def _open_profile_details_page(self) -> None:
        self._click_chat_menu_hot_area()
        self._sleep_transition()
        self._click_profile_avatar_hot_area()
        self._sleep_transition()

    def _click_timeline_preview_hot_area(
        self,
        timeline_entry,
        tried_points: set[tuple[int, int]] | None = None,
        limit: int | None = None,
    ) -> bool:
        window = self._require_window()
        window_rect = window.rectangle()
        entry_rect = timeline_entry.rectangle()
        window_width = int(window_rect.width())
        window_height = int(window_rect.height())
        entry_left = int(entry_rect.left)
        entry_top = int(entry_rect.top)
        entry_width = int(entry_rect.width())
        entry_height = int(entry_rect.height())
        window_left = int(window_rect.left)
        window_top = int(window_rect.top)
        entry_x = entry_left - window_left
        entry_y = entry_top - window_top + max(16, int(entry_height * 0.6))
        right_edge = max(0, window_width - 36)
        candidate_points = [
            (
                min(max(0, entry_x + max(180, entry_width + 70)), right_edge),
                min(max(0, entry_y), max(0, window_height - 1)),
            ),
            (
                min(max(0, entry_x + max(260, entry_width + 150)), right_edge),
                min(max(0, entry_y + 2), max(0, window_height - 1)),
            ),
            (
                min(max(0, entry_x + max(320, entry_width + 210)), right_edge),
                min(max(0, entry_y), max(0, window_height - 1)),
            ),
            (
                min(max(0, entry_x + max(380, entry_width + 270)), right_edge),
                min(max(0, entry_y + 2), max(0, window_height - 1)),
            ),
            (
                min(max(0, entry_x + max(440, entry_width + 330)), right_edge),
                min(max(0, entry_y), max(0, window_height - 1)),
            ),
            (
                min(max(0, entry_x + max(500, entry_width + 390)), right_edge),
                min(max(0, entry_y + 2), max(0, window_height - 1)),
            ),
        ]
        seen = tried_points if tried_points is not None else set()
        attempts = 0
        for point in candidate_points:
            if point in seen:
                continue
            seen.add(point)
            attempts += 1
            if self._click_timeline_candidate_point(window, point[0], point[1]):
                return True
            if limit is not None and attempts >= limit:
                break
        return False

    def _click_timeline_preview_visual_fallback(
        self,
        tried_points: set[tuple[int, int]] | None = None,
    ) -> bool:
        for detector in (
            self._detect_timeline_preview_bbox_from_media_rows,
            self._detect_timeline_preview_bbox_by_panel_scan,
            self._detect_timeline_preview_bbox,
        ):
            bbox = detector()
            if bbox is None:
                continue
            x0, y0, x1, y1 = bbox
            point = (int((x0 + x1) / 2), int((y0 + y1) / 2))
            if tried_points is not None and point in tried_points:
                continue
            if tried_points is not None:
                tried_points.add(point)
            if self._click_timeline_candidate_point(self._require_window(), point[0], point[1]):
                return True
        return False

    def _click_timeline_candidate_point(self, window, x: int, y: int) -> bool:
        self._last_timeline_launch_point = (x, y)
        self._screen_click_relative(window, x, y)
        self._sleep_transition()
        return self._find_timeline_popup_window() is not None

    @staticmethod
    def _is_preview_candidate_pixel(r: int, g: int, b: int) -> bool:
        mx = max(r, g, b)
        mn = min(r, g, b)
        return (mx >= 78 and (mx - mn) >= 16) or (r + g + b) >= 300

    @staticmethod
    def _first_dense_band(items: list[tuple[int, int]], min_length: int) -> tuple[int, int] | None:
        if not items:
            return None
        start = items[0][0]
        prev = items[0][0]
        for value, _count in items[1:]:
            if value == prev + 1:
                prev = value
                continue
            if prev - start + 1 >= min_length:
                return start, prev
            start = value
            prev = value
        if prev - start + 1 >= min_length:
            return start, prev
        return None

    @staticmethod
    def _largest_dense_band(items: list[tuple[int, int]], min_length: int) -> tuple[int, int] | None:
        if not items:
            return None
        best: tuple[int, int] | None = None
        start = items[0][0]
        prev = items[0][0]
        for value, _count in items[1:]:
            if value == prev + 1:
                prev = value
                continue
            if prev - start + 1 >= min_length and (
                best is None or (prev - start) > (best[1] - best[0])
            ):
                best = (start, prev)
            start = value
            prev = value
        if prev - start + 1 >= min_length and (
            best is None or (prev - start) > (best[1] - best[0])
        ):
            best = (start, prev)
        return best

    @staticmethod
    def _dense_bands(items: list[tuple[int, int]], min_length: int) -> list[tuple[int, int]]:
        if not items:
            return []
        bands: list[tuple[int, int]] = []
        start = items[0][0]
        prev = items[0][0]
        for value, _count in items[1:]:
            if value == prev + 1:
                prev = value
                continue
            if prev - start + 1 >= min_length:
                bands.append((start, prev))
            start = value
            prev = value
        if prev - start + 1 >= min_length:
            bands.append((start, prev))
        return bands

    @staticmethod
    def _sleep_transition() -> None:
        time.sleep(0.5)

    def _find_contact_item(self, remark_name: str):
        normalized = remark_name.strip()
        for descendant in self._iter_descendants():
            info = descendant.element_info
            if info.control_type not in {"ListItem", "Text", "DataItem", "Pane"}:
                continue
            text = self._window_text(descendant)
            if text == normalized:
                return descendant
        for descendant in self._iter_descendants():
            text = self._window_text(descendant)
            if normalized and normalized in text:
                return descendant
        return None

    def _find_timeline_entry(self):
        timeline_label = "\u670b\u53cb\u5708"
        for descendant in self._iter_descendants():
            text = self._window_text(descendant)
            if timeline_label in text:
                return descendant
        return None

    def _assert_search_text_matches(self, target, expected_text: str) -> None:
        normalized_expected = expected_text.strip()
        if not normalized_expected:
            raise RuntimeError("empty expected search text")

        observed_text = self._window_text(target).strip()
        if observed_text == normalized_expected:
            return

        if self._search_input_mode == "window" and self._find_search_results_popup_window() is not None:
            return

        clipboard_probe = "__codex_search_probe__"
        self._set_clipboard_text(clipboard_probe)
        time.sleep(0.02)
        self._type_keys(target, "^a^c")
        time.sleep(0.08)
        clipboard_text = self._get_clipboard_text().strip()
        if clipboard_text != normalized_expected:
            raise RuntimeError("search text verification failed")

    @staticmethod
    def _window_text(wrapper) -> str:
        try:
            return str(wrapper.window_text() or "").strip()
        except Exception:
            return ""

    @staticmethod
    def _safe_click(wrapper, double: bool = False) -> None:
        try:
            if double:
                wrapper.click_input(double=True)
            else:
                wrapper.click_input()
        except Exception as exc:
            raise RuntimeError("寰俊鎺т欢鐐瑰嚮澶辫触") from exc

    @staticmethod
    def _window_click(window, x: int, y: int, double: bool = False) -> None:
        try:
            window.click_input(coords=(x, y), double=double)
        except Exception as exc:
            raise RuntimeError("寰俊绐楀彛鍧愭爣鐐瑰嚮澶辫触") from exc

    @staticmethod
    def _screen_click_relative(window, x: int, y: int) -> None:
        rect = window.rectangle()
        abs_x = int(rect.left) + int(x)
        abs_y = int(rect.top) + int(y)
        user32 = ctypes.windll.user32
        mouse_left_down = 0x0002
        mouse_left_up = 0x0004
        try:
            user32.SetCursorPos(abs_x, abs_y)
            time.sleep(0.05)
            user32.mouse_event(mouse_left_down, 0, 0, 0, 0)
            time.sleep(0.03)
            user32.mouse_event(mouse_left_up, 0, 0, 0, 0)
        except Exception as exc:
            raise RuntimeError("寰俊灞忓箷鐐瑰嚮澶辫触") from exc

    @staticmethod
    def _screen_wheel_relative(window, x: int, y: int, wheel_delta: int) -> None:
        rect = window.rectangle()
        abs_x = int(rect.left) + int(x)
        abs_y = int(rect.top) + int(y)
        user32 = ctypes.windll.user32
        mouseeventf_wheel = 0x0800
        try:
            user32.SetCursorPos(abs_x, abs_y)
            time.sleep(0.03)
            user32.mouse_event(mouseeventf_wheel, 0, 0, int(wheel_delta), 0)
        except Exception as exc:
            raise RuntimeError("寰俊灞忓箷婊氳疆澶辫触") from exc

    @staticmethod
    def _screen_drag_relative(window, start_x: int, start_y: int, end_x: int, end_y: int) -> None:
        rect = window.rectangle()
        abs_start_x = int(rect.left) + int(start_x)
        abs_start_y = int(rect.top) + int(start_y)
        abs_end_x = int(rect.left) + int(end_x)
        abs_end_y = int(rect.top) + int(end_y)
        user32 = ctypes.windll.user32
        mouse_left_down = 0x0002
        mouse_left_up = 0x0004
        try:
            user32.SetCursorPos(abs_start_x, abs_start_y)
            time.sleep(0.05)
            user32.mouse_event(mouse_left_down, 0, 0, 0, 0)
            steps = 8
            for step in range(1, steps + 1):
                move_x = int(abs_start_x + (abs_end_x - abs_start_x) * step / steps)
                move_y = int(abs_start_y + (abs_end_y - abs_start_y) * step / steps)
                user32.SetCursorPos(move_x, move_y)
                time.sleep(0.02)
            time.sleep(0.03)
            user32.mouse_event(mouse_left_up, 0, 0, 0, 0)
        except Exception as exc:
            raise RuntimeError("寰俊灞忓箷鎷栧姩澶辫触") from exc

    @staticmethod
    def _type_keys(wrapper, keys: str, **kwargs: object) -> None:
        try:
            wrapper.type_keys(keys, set_foreground=True, **kwargs)
        except Exception as exc:
            raise RuntimeError("type keys failed") from exc

    def _window_type_keys(self, keys: str) -> None:
        self._type_keys(self._require_window(), keys)

    @staticmethod
    def _set_clipboard_text(text: str) -> None:
        try:
            win32clipboard.OpenClipboard()
            win32clipboard.EmptyClipboard()
            win32clipboard.SetClipboardText(text, win32clipboard.CF_UNICODETEXT)
        except Exception as exc:
            raise RuntimeError("寰俊鎼滅储妗嗗啓鍏ュ壀璐存澘澶辫触") from exc
        finally:
            try:
                win32clipboard.CloseClipboard()
            except Exception:
                pass

    @staticmethod
    def _get_clipboard_text() -> str:
        try:
            win32clipboard.OpenClipboard()
            data = win32clipboard.GetClipboardData(win32clipboard.CF_UNICODETEXT)
            return str(data or "")
        except Exception as exc:
            raise RuntimeError("clipboard read failed") from exc
        finally:
            try:
                win32clipboard.CloseClipboard()
            except Exception:
                pass


@dataclass(slots=True)
class WeChatWarmupAdapter:
    settings: WarmupUiSettings
    controller: WarmupController
    _prepared_start_page: str | None = field(init=False, default=None)

    def prepare(self, start_page: str) -> None:
        if start_page not in {"contacts", "chat_list"}:
            raise RuntimeError(f"unsupported start page: {start_page}")
        self.controller.ensure_wechat_window()
        self._prepared_start_page = start_page

    def warmup_contact(self, remark_name: str) -> WarmupContactDiagnostics:
        if self._prepared_start_page is None:
            raise RuntimeError("prepare required")

        diagnostics = WarmupContactDiagnostics(remark_name=remark_name)
        current_step = "warmup_contact"
        try:
            current_step = "ensure_wechat_window"
            self.controller.ensure_wechat_window()
            self._record_step(diagnostics, current_step)
            current_step = "open_search"
            self.controller.open_search(self._prepared_start_page)
            diagnostics.search_ok = True
            self._record_step(diagnostics, current_step)
            self.controller.sleep_ms(self.settings.search_delay_ms)
            current_step = "input_search_text"
            self.controller.input_search_text(remark_name)
            self._record_step(diagnostics, current_step)
            current_step = "select_contact"
            self.controller.select_contact(remark_name)
            diagnostics.select_contact_ok = True
            self._record_step(diagnostics, current_step)
            self.controller.sleep_ms(self.settings.open_profile_delay_ms)
            diagnostics.profile_ok = True
            current_step = "open_timeline"
            self.controller.open_timeline()
            self.controller.sleep_ms(self.settings.open_timeline_delay_ms)
            if self.controller.detect_page_state() is not WarmupPageState.TIMELINE_POPUP:
                raise RuntimeError("timeline popup missing")
            diagnostics.timeline_open_ok = True
            self._record_step(diagnostics, current_step)
            current_step = "page_down"
            self.controller.page_down()
            diagnostics.timeline_scroll_ok = True
            self._record_step(diagnostics, current_step)
        except Exception as exc:
            self._record_step(
                diagnostics,
                current_step,
                WarmupStepStatus.FAILED,
                str(exc),
            )

        diagnostics.reset_ok = self._best_effort_reset_page()
        if (
            getattr(self.settings, "force_recovery_on_reset_failure", False)
            and not diagnostics.reset_ok
        ):
            diagnostics.forced_recovery_used = True
            diagnostics.reset_ok = (
                self.controller.force_recover_to_searchable_page()
            )
        self._record_step(
            diagnostics,
            "reset_to_searchable_page",
            WarmupStepStatus.PASSED if diagnostics.reset_ok else WarmupStepStatus.FAILED,
        )
        diagnostics.final_page_state = self._detect_final_page_state(diagnostics)
        return diagnostics

    def _best_effort_reset_page(self) -> bool:
        try:
            self.controller.reset_to_searchable_page(self.settings.back_delay_ms)
            return True
        except Exception:
            return False

    def _detect_final_page_state(
        self,
        diagnostics: WarmupContactDiagnostics,
    ) -> WarmupPageState:
        try:
            page_state = self.controller.detect_page_state()
            diagnostics.step_results.append(
                WarmupStepResult("detect_page_state", WarmupStepStatus.PASSED)
            )
            if page_state is WarmupPageState.SEARCH_READY:
                return page_state
            if not getattr(self.settings, "verify_state_after_each_contact", False):
                return page_state

            try:
                recovered = self.controller.force_recover_to_searchable_page()
                diagnostics.step_results.append(
                    WarmupStepResult(
                        "force_recover_to_searchable_page",
                        WarmupStepStatus.PASSED if recovered else WarmupStepStatus.FAILED,
                    )
                )
            except Exception as exc:
                diagnostics.step_results.append(
                    WarmupStepResult(
                        "force_recover_to_searchable_page",
                        WarmupStepStatus.FAILED,
                        str(exc),
                    )
                )
                return page_state

            if not recovered:
                return page_state

            diagnostics.forced_recovery_used = True
            recovered_state = self.controller.detect_page_state()
            diagnostics.step_results.append(
                WarmupStepResult("detect_page_state_after_recovery", WarmupStepStatus.PASSED)
            )
            return recovered_state
        except Exception as exc:
            diagnostics.step_results.append(
                WarmupStepResult("detect_page_state", WarmupStepStatus.FAILED, str(exc))
            )
            return WarmupPageState.UNKNOWN

    @staticmethod
    def _record_step(
        diagnostics: WarmupContactDiagnostics,
        step: str,
        status: WarmupStepStatus = WarmupStepStatus.PASSED,
        reason: str = "",
    ) -> None:
        diagnostics.step_results.append(WarmupStepResult(step, status, reason))
