from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import re
import time
from typing import Callable, Iterable, Protocol

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
