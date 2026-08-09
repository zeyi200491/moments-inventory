from __future__ import annotations

import argparse
from dataclasses import dataclass, field
from pathlib import Path
import random
import re
import time
from typing import Any, Callable, Iterable, Protocol
from urllib.parse import unquote_plus, urljoin, urlparse, urlunparse

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
SUPPORTED_IMAGE_CONTENT_TYPES = {"", "application/octet-stream", "image/jpeg", "image/jpg", "image/png"}
IMAGE_NOISE_TOKENS = ("avatar", "icon", "logo", "emoji")
IGNORED_IMAGE_QUERY_KEYS = {
    "xsec_token",
    "xsec_source",
    "from",
    "share_from_user_hidden",
    "type",
    "appuid",
    "apptime",
}
PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PROFILE_DIR = PROJECT_ROOT / ".playwright-mcp" / "xhs-ccd-profile"


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


class RateController(Protocol):
    def after_search(self) -> None:
        ...

    def after_note_open(self) -> None:
        ...

    def after_image_save(self) -> None:
        ...

    def after_model(self, processed_count: int) -> None:
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
        sleep: Callable[[float], None] = time.sleep,
        random_uniform: Callable[[float, float], float] = random.uniform,
    ):
        self._sleep = sleep
        self._random_uniform = random_uniform

    def _sleep_between(self, minimum_seconds: float, maximum_seconds: float) -> None:
        self._sleep(self._random_uniform(minimum_seconds, maximum_seconds))

    def after_search(self) -> None:
        self._sleep_between(3.0, 6.0)

    def after_note_open(self) -> None:
        self._sleep_between(2.0, 5.0)

    def after_image_save(self) -> None:
        self._sleep_between(0.5, 1.5)

    def after_model(self, processed_count: int) -> None:
        if processed_count > 0 and processed_count % 10 == 0:
            self._sleep_between(60.0, 120.0)

    def wait(self) -> None:
        self.after_image_save()


def image_content_kind(content: bytes) -> str | None:
    if content.startswith(b"\xff\xd8\xff"):
        return "jpeg"
    if content.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    return None


def is_supported_image_content(content_type: str | None, content: bytes) -> bool:
    normalized_content_type = (content_type or "").split(";", 1)[0].strip().lower()
    if normalized_content_type not in SUPPORTED_IMAGE_CONTENT_TYPES:
        return False
    return image_content_kind(content) in {"jpeg", "png"}


def normalize_candidate_image_url(url: str) -> str | None:
    candidate = url.strip()
    if not candidate or candidate.startswith("data:"):
        return None
    if candidate.startswith("//"):
        candidate = f"https:{candidate}"
    elif candidate.startswith("/"):
        candidate = urljoin(XHS_HOME_URL, candidate)

    parsed = urlparse(candidate)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return None

    lowered = candidate.lower()
    if "data:image" in lowered or lowered.endswith(".svg") or ".svg?" in lowered:
        return None
    if any(token in lowered for token in IMAGE_NOISE_TOKENS):
        return None

    query_parts = []
    for part in parsed.query.split("&"):
        if not part:
            continue
        key = unquote_plus(part.split("=", 1)[0]).lower()
        if key in IGNORED_IMAGE_QUERY_KEYS:
            continue
        query_parts.append(part)
    query = "&".join(query_parts)
    return urlunparse((parsed.scheme, parsed.netloc, parsed.path, "", query, ""))


def image_url_dedupe_key(url: str) -> str:
    parsed = urlparse(url)
    return urlunparse((parsed.scheme, parsed.netloc, parsed.path, "", "", ""))


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
                "Accept": "image/jpeg,image/png,*/*;q=0.8",
                "Referer": XHS_HOME_URL,
            },
        )

    def download(self, url: str) -> bytes | None:
        response = self._client.get(url)
        response.raise_for_status()
        content = response.content
        content_type = response.headers.get("content-type")
        if not is_supported_image_content(content_type, content):
            kind = image_content_kind(content) or "unknown"
            raise RuntimeError(f"unsupported image content: {content_type or '<missing>'}, magic={kind}")
        return content or None

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
        rate_limiter: RateController | None = None,
    ):
        from playwright.sync_api import sync_playwright

        self.timeout_ms = timeout_ms
        self.manual_retries = manual_retries
        self._rate_limiter = rate_limiter or RateLimiter()
        self.user_data_dir = Path(user_data_dir) if user_data_dir else Path.home() / ".xhs_ccd_image_browser"
        self.user_data_dir.mkdir(parents=True, exist_ok=True)
        self._playwright = sync_playwright().start()
        self._context = None
        try:
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
        except Exception:
            if self._context is not None:
                self._context.close()
            self._playwright.stop()
            raise

    def close(self) -> None:
        try:
            if self._context is not None:
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
            try:
                note_image_urls = self._image_urls_from_note(link)
            except Exception as exc:
                print(f"跳过笔记：{link}，原因：{exc}")
                continue
            finally:
                self._rate_limiter.after_note_open()

            for image_url in note_image_urls:
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
        return self._image_urls_from_note(note_url)

    def _image_urls_from_note(self, note_url: str) -> list[str]:
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
                const mainSelectors = [
                    'main',
                    '[class*="note"]',
                    '[class*="media"]',
                    '[class*="swiper"]',
                    '[class*="carousel"]',
                    '[class*="content"]',
                    '[role="main"]'
                ];
                let root = document;
                for (const selector of mainSelectors) {
                    const candidate = document.querySelector(selector);
                    if (candidate && candidate.querySelectorAll('img').length > 0) {
                        root = candidate;
                        break;
                    }
                }
                const urls = [];
                for (const img of root.querySelectorAll('img')) {
                    const width = img.naturalWidth || img.width || 0;
                    const height = img.naturalHeight || img.height || 0;
                    if (width < 300 || height < 300 || width * height < 90000) {
                        continue;
                    }
                    urls.push(img.currentSrc, img.src, img.dataset.src, img.getAttribute('data-original'));
                    const srcset = img.getAttribute('srcset');
                    if (srcset) {
                        urls.push(...srcset.split(',').map(item => item.trim().split(/\\s+/)[0]));
                    }
                }
                return urls.filter(Boolean);
            }
            """
        )
        image_urls: list[str] = []
        seen: set[str] = set()
        for raw_url in raw_urls:
            normalized = normalize_candidate_image_url(str(raw_url))
            if not normalized:
                continue
            dedupe_key = image_url_dedupe_key(normalized)
            if dedupe_key in seen:
                continue
            seen.add(dedupe_key)
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
        return normalize_candidate_image_url(url)

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
    rate_limiter: RateController,
) -> RunSummary:
    task_list = list(tasks)
    summary = RunSummary(total=len(task_list))
    processed_count = 0

    for task in task_list:
        if next_image_number(task.output_dir) is None:
            summary.skipped_full += 1
            print(f"SKIP {task.model_name} already has {TARGET_IMAGES_PER_MODEL} images")
            continue

        processed_count += 1
        summary.searched += 1
        print(f"SEARCH {task.model_name} {task.search_query}")
        try:
            image_urls = browser.image_urls_for_query(task.search_query, TARGET_IMAGES_PER_MODEL)
        except Exception as exc:
            rate_limiter.after_search()
            summary.failed += 1
            summary.incomplete += 1
            print(f"FAIL {task.model_name} search {exc}")
            rate_limiter.after_model(processed_count)
            continue
        rate_limiter.after_search()

        for image_url in image_urls:
            if next_image_number(task.output_dir) is None:
                break

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
            rate_limiter.after_image_save()

        if next_image_number(task.output_dir) is not None:
            summary.incomplete += 1
            current_count = len(existing_image_numbers(task.output_dir))
            missing_count = TARGET_IMAGES_PER_MODEL - current_count
            print(f"不足 7 张 {task.model_name} 当前数量={current_count} 缺口={missing_count}")

        rate_limiter.after_model(processed_count)

    return summary


def _strip_matching_outer_quotes(value: str) -> str:
    stripped = value.strip()
    if len(stripped) >= 2 and stripped[0] == stripped[-1] and stripped[0] in {"'", '"'}:
        return stripped[1:-1]
    return stripped


def _existing_file_path(value: str) -> Path:
    path = Path(_strip_matching_outer_quotes(value)).expanduser()
    if path.suffix.lower() != ".xlsx":
        raise argparse.ArgumentTypeError(f"请选择 .xlsx 文件：{path}")
    if not path.is_file():
        raise argparse.ArgumentTypeError(f"Excel 文件不存在：{path}")
    return path


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="下载小红书 CCD 相机样张图片")
    parser.add_argument("excel_path", type=_existing_file_path, help="CCD 型号 Excel 文件路径")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=OUTPUT_ROOT,
        help=f"图片输出目录，默认：{OUTPUT_ROOT}",
    )
    parser.add_argument(
        "--profile-dir",
        type=Path,
        default=DEFAULT_PROFILE_DIR,
        help=f"浏览器独立用户数据目录，默认：{DEFAULT_PROFILE_DIR}",
    )
    return parser.parse_args(argv)


def exit_code_for_summary(summary: RunSummary) -> int:
    return 1 if summary.failed else 0


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    browser: XhsBrowser | None = None
    downloader: HttpImageDownloader | None = None

    try:
        tasks = load_model_tasks(args.excel_path, args.output_dir)
        browser = XhsBrowser(user_data_dir=args.profile_dir)
        downloader = HttpImageDownloader()
        summary = process_tasks(tasks, browser, downloader, RateLimiter())
        print(
            "SUMMARY "
            f"total={summary.total} "
            f"searched={summary.searched} "
            f"skipped_full={summary.skipped_full} "
            f"saved={summary.saved} "
            f"incomplete={summary.incomplete} "
            f"failed={summary.failed} "
            f"failed_downloads={len(summary.failed_downloads)}"
        )
        return exit_code_for_summary(summary)
    except Exception as exc:
        print(f"ERROR {exc}")
        return 1
    finally:
        if downloader is not None:
            downloader.close()
        if browser is not None:
            browser.close()


if __name__ == "__main__":
    raise SystemExit(main())
