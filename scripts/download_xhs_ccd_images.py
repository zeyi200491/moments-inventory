from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import re
import time
from typing import Any, Callable, Iterable, Protocol
from urllib.parse import urljoin, urlparse

import openpyxl


REQUIRED_HEADERS = {"品牌", "统一物理机型/规范名", "欧亚/中国常见名", "传感器"}
WINDOWS_RESERVED_DEVICE_NAMES = {
    "CON",
    "PRN",
    "AUX",
    "NUL",
    *{f"COM{number}" for number in range(1, 10)},
    *{f"LPT{number}" for number in range(1, 10)},
}
OUTPUT_ROOT = Path(r"E:\Ai jjfajgsw\AIkefu\output\ccdcpt")
TARGET_IMAGES_PER_MODEL = 7
IMAGE_SUFFIXES = {".jpg", ".jpeg"}
XHS_HOME_URL = "https://www.xiaohongshu.com"


class ExcelFormatError(ValueError):
    pass


@dataclass(frozen=True)
class ModelTask:
    brand: str
    brand_dir: str
    model_name: str
    canonical_name: str
    common_name: str
    search_query: str
    output_dir: Path


class ImageBrowser(Protocol):
    def image_urls_for_query(self, query: str, limit: int) -> list[str]:
        ...


class ImageDownloader(Protocol):
    def download(self, url: str) -> bytes | None:
        ...


class Waiter(Protocol):
    def wait(self) -> None:
        ...


@dataclass
class RunSummary:
    total: int = 0
    skipped_full: int = 0
    saved: int = 0
    incomplete: int = 0
    failed: int = 0
    searched: int = 0
    failed_downloads: list[tuple[str, str, str]] = field(default_factory=list)

    @property
    def total_tasks(self) -> int:
        return self.total

    @property
    def searched_tasks(self) -> int:
        return self.searched

    @property
    def saved_images(self) -> int:
        return self.saved


class RateLimiter:
    def __init__(
        self,
        min_interval_seconds: float = 1.0,
        sleep: Callable[[float], None] = time.sleep,
        monotonic: Callable[[], float] = time.monotonic,
    ):
        self.min_interval_seconds = min_interval_seconds
        self._sleep = sleep
        self._monotonic = monotonic
        self._last_request_at: float | None = None

    def wait(self) -> None:
        now = self._monotonic()
        if self._last_request_at is not None:
            elapsed = now - self._last_request_at
            remaining = self.min_interval_seconds - elapsed
            if remaining > 0:
                self._sleep(remaining)
                now = self._monotonic()
        self._last_request_at = now


class HttpImageDownloader:
    def __init__(self, timeout_seconds: float = 30.0):
        import httpx

        self._client = httpx.Client(
            follow_redirects=True,
            timeout=timeout_seconds,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/124.0.0.0 Safari/537.36"
                ),
                "Accept": "image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8",
                "Referer": XHS_HOME_URL,
            },
        )

    def download(self, url: str) -> bytes | None:
        response = self._client.get(url)
        response.raise_for_status()
        content_type = response.headers.get("content-type", "").lower()
        if "image" not in content_type:
            raise RuntimeError(f"unexpected content-type: {content_type or '<missing>'}")
        return response.content or None

    def close(self) -> None:
        self._client.close()


class XhsBrowser:
    SEARCH_INPUT_SELECTORS = [
        "input.search-input",
        "input[placeholder*='搜索']",
        "input[placeholder*='搜']",
        "input[type='search']",
        "input",
    ]
    NOTE_LINK_SELECTOR = "a[href*='/explore/'], a[href*='/discovery/item/']"
    LOGIN_SELECTORS = [
        "button:has-text('登录')",
        "text=登录后查看",
        "text=扫码登录",
        "text=验证码登录",
        "text=手机登录",
    ]
    CAPTCHA_KEYWORDS = ["验证码", "安全验证", "滑块", "访问异常", "操作频繁", "请通过验证"]
    VIDEO_SELECTORS = ["video", ".video-player", "[class*='video']", "text=视频"]

    def __init__(
        self,
        user_data_dir: str | Path | None = None,
        timeout_ms: int = 30_000,
        slow_mo_ms: int = 0,
        manual_retries: int = 3,
    ):
        from playwright.sync_api import sync_playwright

        self.timeout_ms = timeout_ms
        self.manual_retries = manual_retries
        self.user_data_dir = Path(user_data_dir) if user_data_dir else Path.home() / ".xhs_ccd_image_browser"
        self.user_data_dir.mkdir(parents=True, exist_ok=True)
        self._playwright = sync_playwright().start()
        self._context = self._playwright.chromium.launch_persistent_context(
            str(self.user_data_dir),
            headless=False,
            slow_mo=slow_mo_ms,
            viewport={"width": 1400, "height": 900},
            locale="zh-CN",
            args=["--disable-blink-features=AutomationControlled"],
        )
        self._context.set_default_timeout(timeout_ms)
        self._page = self._context.pages[0] if self._context.pages else self._context.new_page()

    def close(self) -> None:
        try:
            self._context.close()
        finally:
            self._playwright.stop()

    def ensure_login(self) -> None:
        self._page.goto(XHS_HOME_URL, wait_until="domcontentloaded", timeout=self.timeout_ms)
        self._page.wait_for_timeout(1_000)
        self._handle_manual_intervention(self._page)

    def image_urls_for_query(self, query: str, limit: int) -> list[str]:
        self.ensure_login()
        self._submit_search(query)
        links = self._collect_note_links(limit=max(limit * 4, 20))
        image_urls: list[str] = []
        seen: set[str] = set()

        for link in links:
            if len(image_urls) >= limit:
                break
            for image_url in self._image_urls_for_note(link):
                if image_url in seen:
                    continue
                seen.add(image_url)
                image_urls.append(image_url)
                if len(image_urls) >= limit:
                    break

        return image_urls

    def search_image_urls(self, query: str, limit: int) -> list[str]:
        return self.image_urls_for_query(query, limit)

    def image_urls(self, query: str, limit: int) -> list[str]:
        return self.image_urls_for_query(query, limit)

    def _submit_search(self, query: str) -> None:
        search_input = self._first_visible_locator(self._page, self.SEARCH_INPUT_SELECTORS)
        if search_input is None:
            self._handle_manual_intervention(self._page, "未找到搜索框，请确认页面可搜索")
            search_input = self._first_visible_locator(self._page, self.SEARCH_INPUT_SELECTORS)
        if search_input is None:
            raise RuntimeError("未找到小红书搜索框")

        search_input.click()
        search_input.fill(query)
        search_input.press("Enter")
        self._page.wait_for_load_state("domcontentloaded")
        self._page.wait_for_timeout(2_000)
        self._handle_manual_intervention(self._page)

    def _collect_note_links(self, limit: int) -> list[str]:
        links: list[str] = []
        seen: set[str] = set()
        for _ in range(8):
            for href in self._hrefs_from_page(self._page):
                normalized = self._normalize_note_url(href)
                if not normalized or normalized in seen:
                    continue
                seen.add(normalized)
                links.append(normalized)
                if len(links) >= limit:
                    return links
            self._page.mouse.wheel(0, 1_200)
            self._page.wait_for_timeout(1_000)
        return links

    def _image_urls_for_note(self, note_url: str) -> list[str]:
        page = self._context.new_page()
        try:
            page.goto(note_url, wait_until="domcontentloaded", timeout=self.timeout_ms)
            page.wait_for_timeout(1_500)
            self._handle_manual_intervention(page)
            if self._is_video_note(page):
                print(f"SKIP video note {note_url}")
                return []
            return self._extract_image_urls(page)
        finally:
            page.close()

    def _extract_image_urls(self, page: Any) -> list[str]:
        raw_urls = page.evaluate(
            """
            () => {
                const urls = [];
                for (const img of document.querySelectorAll('img')) {
                    urls.push(img.currentSrc, img.src, img.dataset.src, img.getAttribute('data-original'));
                }
                for (const source of document.querySelectorAll('source[srcset]')) {
                    urls.push(...source.srcset.split(',').map(item => item.trim().split(/\\s+/)[0]));
                }
                return urls.filter(Boolean);
            }
            """
        )
        image_urls: list[str] = []
        seen: set[str] = set()
        for raw_url in raw_urls:
            normalized = self._normalize_image_url(str(raw_url))
            if not normalized or normalized in seen:
                continue
            seen.add(normalized)
            image_urls.append(normalized)
        return image_urls

    def _hrefs_from_page(self, page: Any) -> list[str]:
        locator = page.locator(self.NOTE_LINK_SELECTOR)
        hrefs: list[str] = []
        for index in range(locator.count()):
            href = locator.nth(index).get_attribute("href")
            if href:
                hrefs.append(href)
        return hrefs

    def _normalize_note_url(self, href: str) -> str | None:
        url = urljoin(XHS_HOME_URL, href)
        parsed = urlparse(url)
        if parsed.netloc and "xiaohongshu.com" not in parsed.netloc:
            return None
        if "/explore/" not in parsed.path and "/discovery/item/" not in parsed.path:
            return None
        return url

    def _normalize_image_url(self, url: str) -> str | None:
        if url.startswith("//"):
            url = f"https:{url}"
        elif url.startswith("/"):
            url = urljoin(XHS_HOME_URL, url)

        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"}:
            return None
        lowered = url.lower()
        if lowered.endswith(".svg") or "data:image/svg" in lowered:
            return None
        if any(token in lowered for token in ("avatar", "icon", "logo")):
            return None
        return url

    def _is_video_note(self, page: Any) -> bool:
        return any(self._locator_is_visible(page, selector) for selector in self.VIDEO_SELECTORS)

    def _handle_manual_intervention(self, page: Any, fallback_reason: str | None = None) -> None:
        reason = self._manual_intervention_reason(page) or fallback_reason
        if reason is None:
            return

        for attempt in range(1, self.manual_retries + 1):
            print(f"NEED_MANUAL {reason}，请在浏览器处理后按 Enter 继续（{attempt}/{self.manual_retries}）")
            try:
                input()
            except EOFError as exc:
                raise RuntimeError(f"需要人工处理：{reason}") from exc
            page.wait_for_timeout(1_000)
            reason = self._manual_intervention_reason(page)
            if reason is None:
                return
        raise RuntimeError(f"人工处理后仍无法继续：{reason}")

    def _manual_intervention_reason(self, page: Any) -> str | None:
        body_text = self._body_text(page)
        for keyword in self.CAPTCHA_KEYWORDS:
            if keyword in body_text:
                return keyword
        for selector in self.LOGIN_SELECTORS:
            if self._locator_is_visible(page, selector):
                return "登录"
        return None

    def _first_visible_locator(self, page: Any, selectors: Iterable[str]) -> Any | None:
        for selector in selectors:
            locator = page.locator(selector).first
            try:
                if locator.is_visible(timeout=1_000):
                    return locator
            except Exception:
                continue
        return None

    def _locator_is_visible(self, page: Any, selector: str) -> bool:
        try:
            return page.locator(selector).first.is_visible(timeout=1_000)
        except Exception:
            return False

    def _body_text(self, page: Any) -> str:
        try:
            return page.locator("body").inner_text(timeout=2_000)
        except Exception:
            return ""


def clean_cell(value: object) -> str:
    if value is None:
        return ""
    return str(value).strip()


def extract_chinese_brand(raw_brand: str) -> str:
    chinese = "".join(re.findall(r"[\u4e00-\u9fff]+", raw_brand))
    return chinese or safe_path_part(raw_brand) or "未知品牌"


def safe_path_part(value: str) -> str:
    cleaned = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", value.strip())
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" .")
    cleaned = cleaned or "未命名"
    device_name = cleaned.split(".", 1)[0].upper()
    if device_name in WINDOWS_RESERVED_DEVICE_NAMES:
        return f"_{cleaned}"
    return cleaned


def header_map(headers: Iterable[object]) -> dict[str, int]:
    mapping: dict[str, int] = {}
    duplicates: list[str] = []
    for index, value in enumerate(headers):
        header = clean_cell(value)
        if not header:
            continue
        if header in mapping and header not in duplicates:
            duplicates.append(header)
            continue
        mapping[header] = index
    if duplicates:
        raise ExcelFormatError(f"Excel 存在重复字段：{', '.join(sorted(duplicates))}")

    missing = sorted(REQUIRED_HEADERS - set(mapping))
    if missing:
        raise ExcelFormatError(f"Excel 缺少必要字段：{', '.join(missing)}")
    return mapping


def load_model_tasks(excel_path: str | Path, output_root: Path = OUTPUT_ROOT) -> list[ModelTask]:
    path = Path(excel_path)
    workbook = openpyxl.load_workbook(path, read_only=True, data_only=True)
    try:
        sheet = workbook.worksheets[0]
        rows = sheet.iter_rows(values_only=True)
        try:
            headers = next(rows)
        except StopIteration as exc:
            raise ExcelFormatError("Excel 第一个工作表为空") from exc

        columns = header_map(headers)
        tasks: list[ModelTask] = []
        seen: set[tuple[str, str]] = set()

        for row in rows:
            sensor = clean_cell(row[columns["传感器"]]).upper()
            if sensor != "CCD":
                continue

            brand = clean_cell(row[columns["品牌"]])
            canonical_name = clean_cell(row[columns["统一物理机型/规范名"]])
            common_name = clean_cell(row[columns["欧亚/中国常见名"]])
            model_name = common_name or canonical_name
            if not model_name:
                continue

            brand_dir = extract_chinese_brand(brand)
            safe_brand = safe_path_part(brand_dir)
            safe_model = safe_path_part(model_name)
            dedupe_key = (safe_brand.casefold(), safe_model.casefold())
            if dedupe_key in seen:
                continue
            seen.add(dedupe_key)

            tasks.append(
                ModelTask(
                    brand=brand,
                    brand_dir=safe_brand,
                    model_name=model_name,
                    canonical_name=canonical_name,
                    common_name=common_name,
                    search_query=f"{model_name} 出片图",
                    output_dir=output_root / safe_brand / safe_model,
                )
            )

        return tasks
    finally:
        workbook.close()


def existing_image_numbers(folder: Path) -> set[int]:
    numbers: set[int] = set()
    if not folder.exists():
        return numbers

    for path in folder.iterdir():
        if not path.is_file():
            continue
        if path.suffix.lower() not in IMAGE_SUFFIXES:
            continue
        if not re.fullmatch(r"\d{2}", path.stem):
            continue

        number = int(path.stem)
        if 1 <= number <= TARGET_IMAGES_PER_MODEL:
            numbers.add(number)

    return numbers


def next_image_number(folder: Path) -> int | None:
    existing_numbers = existing_image_numbers(folder)
    for number in range(1, TARGET_IMAGES_PER_MODEL + 1):
        if number not in existing_numbers:
            return number
    return None


def save_image_bytes(folder: Path, content: bytes) -> Path | None:
    number = next_image_number(folder)
    if number is None:
        return None

    folder.mkdir(parents=True, exist_ok=True)
    output_path = folder / f"{number:02d}.jpg"
    output_path.write_bytes(content)
    return output_path


def process_tasks(
    tasks: Iterable[ModelTask],
    browser: ImageBrowser,
    downloader: ImageDownloader,
    rate_limiter: Waiter,
) -> RunSummary:
    task_list = list(tasks)
    summary = RunSummary(total=len(task_list))

    for task in task_list:
        if next_image_number(task.output_dir) is None:
            summary.skipped_full += 1
            print(f"SKIP {task.model_name} already has {TARGET_IMAGES_PER_MODEL} images")
            continue

        summary.searched += 1
        print(f"SEARCH {task.model_name} {task.search_query}")
        try:
            image_urls = browser.image_urls_for_query(task.search_query, TARGET_IMAGES_PER_MODEL)
        except Exception as exc:
            summary.failed += 1
            summary.incomplete += 1
            print(f"FAIL {task.model_name} search {exc}")
            continue

        for image_url in image_urls:
            if next_image_number(task.output_dir) is None:
                break

            rate_limiter.wait()
            try:
                content = downloader.download(image_url)
            except Exception as exc:
                summary.failed_downloads.append((task.model_name, image_url, str(exc)))
                print(f"FAIL {task.model_name} {image_url} {exc}")
                continue

            if not content:
                reason = "empty image content"
                summary.failed_downloads.append((task.model_name, image_url, reason))
                print(f"FAIL {task.model_name} {image_url} {reason}")
                continue

            saved_path = save_image_bytes(task.output_dir, content)
            if saved_path is None:
                break

            summary.saved += 1
            print(f"SAVE {task.model_name} {saved_path.name}")

        if next_image_number(task.output_dir) is not None:
            summary.incomplete += 1

    return summary
