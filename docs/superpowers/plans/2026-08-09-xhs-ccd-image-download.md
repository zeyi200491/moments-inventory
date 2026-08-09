# XHS CCD Image Download Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a double-clickable Windows tool that reads CCD camera models from one Excel file, searches Xiaohongshu for each model's output images, and saves up to 7 images per model under `E:\Ai jjfajgsw\AIkefu\output\ccdcpt`.

**Architecture:** Keep the feature isolated in one standalone script plus one `.bat` launcher. Put all testable logic in pure functions and inject browser/downloader/rate-limiter dependencies so Excel parsing, path handling, resume behavior, and orchestration are covered without logging into Xiaohongshu during automated tests. Keep Xiaohongshu browser selectors in one class so future page changes have one maintenance surface.

**Tech Stack:** Python 3.11, `openpyxl` for Excel reading, `playwright` for persistent browser automation, `httpx` for image downloads, `pytest` for tests, Windows `.bat` for double-click launch.

---

## File Structure

- Create: `scripts/download_xhs_ccd_images.py`
  - Standalone command-line script.
  - Contains task data models, Excel parsing, output path handling, browser automation, image downloading, orchestration, and CLI entry point.
  - Uses Chinese command-line messages because this is an end-user Windows script.
- Create: `run_xhs_ccd_download.bat`
  - Double-click/drag-and-drop entry.
  - Prompts for Excel path when no argument is passed.
  - Keeps the window open after completion.
- Create: `tests/test_xhs_ccd_image_download.py`
  - Unit tests for Excel parsing, brand extraction, safe folder naming, resume counting, and orchestration with fake browser/downloader.
- Modify: `pyproject.toml`
  - Add `openpyxl` and `playwright` dependencies.
  - `httpx` already exists and will be reused.

---

### Task 1: Add Dependencies

**Files:**
- Modify: `pyproject.toml`

- [ ] **Step 1: Add Excel and browser automation dependencies**

Modify the `[project].dependencies` list in `pyproject.toml` so it includes:

```toml
dependencies = [
  "fastapi>=0.115.0",
  "httpx>=0.27.0",
  "openpyxl>=3.1.0",
  "Pillow>=10.0.0",
  "playwright>=1.45.0",
  "pydantic>=2.9.0",
  "python-multipart>=0.0.9",
  "PyYAML>=6.0.1",
  "pywinauto>=0.6.8; sys_platform == 'win32'",
  "uvicorn>=0.30.0",
]
```

- [ ] **Step 2: Verify project metadata parses**

Run:

```powershell
python -m pip install -e .
```

Expected: command exits `0`.

- [ ] **Step 3: Commit dependency declaration**

```powershell
git add pyproject.toml
git commit -m "chore: add xhs downloader dependencies"
```

---

### Task 2: Implement Excel Parsing and Model Tasks

**Files:**
- Create: `scripts/download_xhs_ccd_images.py`
- Create: `tests/test_xhs_ccd_image_download.py`

- [ ] **Step 1: Write failing tests for Excel parsing**

Create `tests/test_xhs_ccd_image_download.py` with:

```python
from pathlib import Path
import importlib.util

import openpyxl
import pytest


SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "download_xhs_ccd_images.py"
spec = importlib.util.spec_from_file_location("download_xhs_ccd_images", SCRIPT_PATH)
xhs = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(xhs)


def make_workbook(path: Path, rows: list[list[str]]) -> Path:
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "CCD完整型号表"
    ws.append(["序号", "品牌", "统一物理机型/规范名", "产品类别", "系列", "欧亚/中国常见名", "传感器"])
    for row in rows:
        ws.append(row)
    wb.save(path)
    return path


def test_load_model_tasks_prefers_common_name_and_filters_ccd(tmp_path: Path):
    workbook = make_workbook(
        tmp_path / "canon.xlsx",
        [
            ["1", "Canon 佳能", "PowerShot A720 IS", "相机", "A", "佳能A720", "CCD"],
            ["2", "Canon 佳能", "PowerShot G7 X", "相机", "G", "佳能G7X", "CMOS"],
            ["3", "Canon 佳能", "PowerShot A570 IS", "相机", "A", "", "ccd"],
        ],
    )

    tasks = xhs.load_model_tasks(workbook)

    assert [task.model_name for task in tasks] == ["佳能A720", "PowerShot A570 IS"]
    assert [task.search_query for task in tasks] == ["佳能A720 出片图", "PowerShot A570 IS 出片图"]
    assert {task.brand_dir for task in tasks} == {"佳能"}


def test_load_model_tasks_deduplicates_by_brand_and_model(tmp_path: Path):
    workbook = make_workbook(
        tmp_path / "canon.xlsx",
        [
            ["1", "Canon 佳能", "PowerShot A720 IS", "相机", "A", "佳能A720", "CCD"],
            ["2", "Canon 佳能", "PowerShot A720 IS", "相机", "A", "佳能A720", "CCD"],
        ],
    )

    tasks = xhs.load_model_tasks(workbook)

    assert len(tasks) == 1
    assert tasks[0].model_name == "佳能A720"


def test_load_model_tasks_reports_missing_headers(tmp_path: Path):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["品牌", "传感器"])
    path = tmp_path / "bad.xlsx"
    wb.save(path)

    with pytest.raises(xhs.ExcelFormatError) as exc:
        xhs.load_model_tasks(path)

    assert "统一物理机型/规范名" in str(exc.value)
    assert "欧亚/中国常见名" in str(exc.value)
```

- [ ] **Step 2: Run tests and verify they fail because the script does not exist**

Run:

```powershell
pytest tests/test_xhs_ccd_image_download.py -q
```

Expected: FAIL with `FileNotFoundError` or import error for `scripts/download_xhs_ccd_images.py`.

- [ ] **Step 3: Implement Excel parsing**

Create `scripts/download_xhs_ccd_images.py` with:

```python
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
from typing import Iterable

import openpyxl


REQUIRED_HEADERS = {"品牌", "统一物理机型/规范名", "欧亚/中国常见名", "传感器"}
OUTPUT_ROOT = Path(r"E:\Ai jjfajgsw\AIkefu\output\ccdcpt")
TARGET_IMAGES_PER_MODEL = 7
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
    return cleaned or "未命名"


def header_map(headers: Iterable[object]) -> dict[str, int]:
    mapping = {clean_cell(value): index for index, value in enumerate(headers)}
    missing = sorted(REQUIRED_HEADERS - set(mapping))
    if missing:
        raise ExcelFormatError(f"Excel 缺少必要字段：{', '.join(missing)}")
    return mapping


def load_model_tasks(excel_path: str | Path, output_root: Path = OUTPUT_ROOT) -> list[ModelTask]:
    path = Path(excel_path)
    workbook = openpyxl.load_workbook(path, read_only=True, data_only=True)
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
```

- [ ] **Step 4: Run Excel parsing tests**

Run:

```powershell
pytest tests/test_xhs_ccd_image_download.py -q
```

Expected: PASS for the three tests.

- [ ] **Step 5: Commit Excel parsing**

```powershell
git add scripts/download_xhs_ccd_images.py tests/test_xhs_ccd_image_download.py
git commit -m "feat: parse xhs ccd model workbook"
```

---

### Task 3: Implement Output Resume and Image Download Helpers

**Files:**
- Modify: `scripts/download_xhs_ccd_images.py`
- Modify: `tests/test_xhs_ccd_image_download.py`

- [ ] **Step 1: Add failing tests for resume counting and file naming**

Append to `tests/test_xhs_ccd_image_download.py`:

```python
def test_existing_image_numbers_count_only_target_jpgs(tmp_path: Path):
    folder = tmp_path / "佳能" / "佳能A720"
    folder.mkdir(parents=True)
    (folder / "01.jpg").write_bytes(b"a")
    (folder / "02.jpeg").write_bytes(b"b")
    (folder / "note.txt").write_text("ignore", encoding="utf-8")
    (folder / "08.jpg").write_bytes(b"outside target range")

    assert xhs.existing_image_numbers(folder) == {1, 2}
    assert xhs.next_image_number(folder) == 3


def test_next_image_number_returns_none_when_full(tmp_path: Path):
    folder = tmp_path / "full"
    folder.mkdir()
    for number in range(1, 8):
        (folder / f"{number:02d}.jpg").write_bytes(b"x")

    assert xhs.next_image_number(folder) is None


def test_save_image_bytes_uses_next_available_number(tmp_path: Path):
    folder = tmp_path / "model"
    folder.mkdir()
    (folder / "01.jpg").write_bytes(b"old")

    saved = xhs.save_image_bytes(folder, b"new image bytes")

    assert saved == folder / "02.jpg"
    assert saved.read_bytes() == b"new image bytes"
```

- [ ] **Step 2: Run tests and verify missing helper failures**

Run:

```powershell
pytest tests/test_xhs_ccd_image_download.py -q
```

Expected: FAIL with `AttributeError` for `existing_image_numbers`.

- [ ] **Step 3: Add resume and save helpers**

Append to `scripts/download_xhs_ccd_images.py`:

```python
IMAGE_SUFFIXES = {".jpg", ".jpeg"}


def existing_image_numbers(folder: Path) -> set[int]:
    if not folder.exists():
        return set()
    numbers: set[int] = set()
    for path in folder.iterdir():
        if path.suffix.lower() not in IMAGE_SUFFIXES:
            continue
        if not re.fullmatch(r"\d{2}", path.stem):
            continue
        number = int(path.stem)
        if 1 <= number <= TARGET_IMAGES_PER_MODEL:
            numbers.add(number)
    return numbers


def next_image_number(folder: Path) -> int | None:
    existing = existing_image_numbers(folder)
    for number in range(1, TARGET_IMAGES_PER_MODEL + 1):
        if number not in existing:
            return number
    return None


def save_image_bytes(folder: Path, content: bytes) -> Path | None:
    folder.mkdir(parents=True, exist_ok=True)
    number = next_image_number(folder)
    if number is None:
        return None
    output = folder / f"{number:02d}.jpg"
    output.write_bytes(content)
    return output
```

- [ ] **Step 4: Run helper tests**

Run:

```powershell
pytest tests/test_xhs_ccd_image_download.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit output helper changes**

```powershell
git add scripts/download_xhs_ccd_images.py tests/test_xhs_ccd_image_download.py
git commit -m "feat: add xhs image resume helpers"
```

---

### Task 4: Implement Orchestration with Test Doubles

**Files:**
- Modify: `scripts/download_xhs_ccd_images.py`
- Modify: `tests/test_xhs_ccd_image_download.py`

- [ ] **Step 1: Add failing orchestration test**

Append to `tests/test_xhs_ccd_image_download.py`:

```python
class FakeBrowser:
    def __init__(self):
        self.queries: list[str] = []

    def image_urls_for_query(self, query: str, limit: int):
        self.queries.append(query)
        return [f"https://example.test/{query}/{index}.jpg" for index in range(limit + 2)]


class FakeDownloader:
    def __init__(self):
        self.urls: list[str] = []

    def download(self, url: str) -> bytes:
        self.urls.append(url)
        return f"bytes:{url}".encode("utf-8")


class NoSleepRateLimiter:
    def after_search(self):
        pass

    def after_note_open(self):
        pass

    def after_image_save(self):
        pass

    def after_model(self, processed_count: int):
        pass


def test_process_tasks_skips_full_folder_and_saves_until_seven(tmp_path: Path, capsys):
    full = tmp_path / "佳能" / "已满"
    full.mkdir(parents=True)
    for number in range(1, 8):
        (full / f"{number:02d}.jpg").write_bytes(b"x")

    partial = tmp_path / "佳能" / "未满"
    partial.mkdir(parents=True)
    (partial / "01.jpg").write_bytes(b"old")

    tasks = [
        xhs.ModelTask("Canon 佳能", "佳能", "已满", "已满", "已满", "已满 出片图", full),
        xhs.ModelTask("Canon 佳能", "佳能", "未满", "未满", "未满", "未满 出片图", partial),
    ]
    browser = FakeBrowser()
    downloader = FakeDownloader()

    summary = xhs.process_tasks(tasks, browser, downloader, NoSleepRateLimiter())

    assert summary.total == 2
    assert summary.skipped_full == 1
    assert summary.saved == 6
    assert browser.queries == ["未满 出片图"]
    assert len(list(partial.glob("*.jpg"))) == 7
    assert "已满" in capsys.readouterr().out
```

- [ ] **Step 2: Run tests and verify orchestration failures**

Run:

```powershell
pytest tests/test_xhs_ccd_image_download.py -q
```

Expected: FAIL with `AttributeError` for `process_tasks`.

- [ ] **Step 3: Add orchestration classes and function**

Append to `scripts/download_xhs_ccd_images.py`:

```python
@dataclass
class RunSummary:
    total: int = 0
    skipped_full: int = 0
    saved: int = 0
    incomplete: int = 0
    failed: int = 0


class RateLimiter:
    def after_search(self) -> None:
        import random
        import time

        time.sleep(random.uniform(3, 6))

    def after_note_open(self) -> None:
        import random
        import time

        time.sleep(random.uniform(2, 5))

    def after_image_save(self) -> None:
        import random
        import time

        time.sleep(random.uniform(0.5, 1.5))

    def after_model(self, processed_count: int) -> None:
        if processed_count > 0 and processed_count % 10 == 0:
            import random
            import time

            rest = random.uniform(60, 120)
            print(f"已处理 {processed_count} 个型号，休息 {rest:.0f} 秒。")
            time.sleep(rest)


def process_tasks(tasks, browser, downloader, rate_limiter: RateLimiter) -> RunSummary:
    summary = RunSummary(total=len(tasks))
    for index, task in enumerate(tasks, start=1):
        existing_count = len(existing_image_numbers(task.output_dir))
        print(f"[{index}/{len(tasks)}] {task.brand_dir} / {task.model_name}，已有 {existing_count} 张。")
        if existing_count >= TARGET_IMAGES_PER_MODEL:
            print(f"跳过：{task.model_name} 已满 7 张。")
            summary.skipped_full += 1
            rate_limiter.after_model(index)
            continue

        needed = TARGET_IMAGES_PER_MODEL - existing_count
        saved_for_task = 0
        try:
            print(f"搜索：{task.search_query}")
            image_urls = browser.image_urls_for_query(task.search_query, needed)
            rate_limiter.after_search()
            for url in image_urls:
                if next_image_number(task.output_dir) is None:
                    break
                content = downloader.download(url)
                saved_path = save_image_bytes(task.output_dir, content)
                if saved_path is not None:
                    saved_for_task += 1
                    summary.saved += 1
                    print(f"保存：{saved_path}")
                    rate_limiter.after_image_save()
        except KeyboardInterrupt:
            raise
        except Exception as exc:
            summary.failed += 1
            print(f"失败：{task.model_name}，原因：{exc}")

        final_count = len(existing_image_numbers(task.output_dir))
        if final_count < TARGET_IMAGES_PER_MODEL:
            summary.incomplete += 1
            print(f"不足：{task.model_name} 当前 {final_count} 张，缺 {TARGET_IMAGES_PER_MODEL - final_count} 张。")
        else:
            print(f"完成：{task.model_name}，本次新增 {saved_for_task} 张。")
        rate_limiter.after_model(index)
    return summary
```

- [ ] **Step 4: Run orchestration tests**

Run:

```powershell
pytest tests/test_xhs_ccd_image_download.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit orchestration**

```powershell
git add scripts/download_xhs_ccd_images.py tests/test_xhs_ccd_image_download.py
git commit -m "feat: orchestrate xhs ccd image downloads"
```

---

### Task 5: Add Xiaohongshu Browser and Downloader Implementations

**Files:**
- Modify: `scripts/download_xhs_ccd_images.py`

- [ ] **Step 1: Add Playwright browser and HTTP downloader code**

Append to `scripts/download_xhs_ccd_images.py`:

```python
class HttpImageDownloader:
    def __init__(self, headers: dict[str, str] | None = None):
        import httpx

        self.client = httpx.Client(
            timeout=30,
            follow_redirects=True,
            headers=headers
            or {
                "User-Agent": "Mozilla/5.0",
                "Referer": XHS_HOME_URL,
            },
        )

    def download(self, url: str) -> bytes:
        response = self.client.get(url)
        response.raise_for_status()
        content_type = response.headers.get("content-type", "")
        if "image" not in content_type.lower():
            raise ValueError(f"URL 未返回图片内容：{url}")
        return response.content

    def close(self) -> None:
        self.client.close()


class XhsBrowser:
    def __init__(self, user_data_dir: Path):
        from playwright.sync_api import sync_playwright

        self.playwright = sync_playwright().start()
        self.context = self.playwright.chromium.launch_persistent_context(
            user_data_dir=str(user_data_dir),
            headless=False,
            viewport={"width": 1366, "height": 900},
            args=["--disable-blink-features=AutomationControlled"],
        )
        self.page = self.context.pages[0] if self.context.pages else self.context.new_page()

    def close(self) -> None:
        self.context.close()
        self.playwright.stop()

    def ensure_login(self) -> None:
        self.page.goto(XHS_HOME_URL, wait_until="domcontentloaded")
        self.page.wait_for_timeout(3000)
        if self._looks_logged_out_or_blocked():
            print("请在打开的浏览器中完成小红书登录或验证，完成后回到此窗口按回车继续。")
            input()
            self.page.goto(XHS_HOME_URL, wait_until="domcontentloaded")
            self.page.wait_for_timeout(3000)

    def image_urls_for_query(self, query: str, limit: int):
        self._search(query)
        collected: list[str] = []
        opened: set[str] = set()
        scroll_attempts = 0
        while len(collected) < limit and scroll_attempts < 8:
            note_links = self._note_links()
            for href in note_links:
                if href in opened:
                    continue
                opened.add(href)
                urls = self._image_urls_from_note(href)
                for url in urls:
                    if url not in collected:
                        collected.append(url)
                    if len(collected) >= limit:
                        return collected
            self.page.mouse.wheel(0, 1200)
            self.page.wait_for_timeout(2500)
            scroll_attempts += 1
        return collected

    def _search(self, query: str) -> None:
        self.page.goto(XHS_HOME_URL, wait_until="domcontentloaded")
        self.page.wait_for_timeout(2000)
        search_box = self.page.locator("input").first
        search_box.click()
        search_box.fill(query)
        search_box.press("Enter")
        self.page.wait_for_timeout(5000)
        if self._looks_logged_out_or_blocked():
            print("检测到登录失效、验证码或访问异常，请人工处理后按回车继续。")
            input()
            self.page.wait_for_timeout(3000)

    def _note_links(self) -> list[str]:
        links = self.page.locator("a[href*='/explore/'], a[href*='/discovery/item/']")
        hrefs: list[str] = []
        for index in range(min(links.count(), 40)):
            href = links.nth(index).get_attribute("href")
            if not href:
                continue
            if href.startswith("/"):
                href = XHS_HOME_URL + href
            if href not in hrefs:
                hrefs.append(href)
        return hrefs

    def _image_urls_from_note(self, href: str) -> list[str]:
        detail = self.context.new_page()
        try:
            detail.goto(href, wait_until="domcontentloaded")
            detail.wait_for_timeout(4000)
            page_text = detail.locator("body").inner_text(timeout=5000)
            if "视频" in page_text and detail.locator("video").count() > 0:
                return []
            image_urls = detail.evaluate(
                """() => Array.from(document.images)
                    .map((img) => img.currentSrc || img.src)
                    .filter((src) => src && /^https?:\\/\\//.test(src))
                    .filter((src) => !src.includes('avatar') && !src.includes('logo'))
                """
            )
            return list(dict.fromkeys(image_urls))
        finally:
            detail.close()

    def _looks_logged_out_or_blocked(self) -> bool:
        body_text = self.page.locator("body").inner_text(timeout=5000)
        markers = ["登录", "验证码", "安全验证", "请完成验证"]
        return any(marker in body_text for marker in markers)
```

- [ ] **Step 2: Run existing unit tests**

Run:

```powershell
pytest tests/test_xhs_ccd_image_download.py -q
```

Expected: PASS.

- [ ] **Step 3: Run syntax check**

Run:

```powershell
python -m py_compile scripts/download_xhs_ccd_images.py
```

Expected: command exits `0`.

- [ ] **Step 4: Commit browser implementation**

```powershell
git add scripts/download_xhs_ccd_images.py
git commit -m "feat: add xhs browser downloader"
```

---

### Task 6: Add CLI Entry Point and Double-Click BAT

**Files:**
- Modify: `scripts/download_xhs_ccd_images.py`
- Create: `run_xhs_ccd_download.bat`
- Modify: `tests/test_xhs_ccd_image_download.py`

- [ ] **Step 1: Add failing tests for CLI argument parsing**

Append to `tests/test_xhs_ccd_image_download.py`:

```python
def test_parse_args_accepts_excel_path(tmp_path: Path):
    workbook = tmp_path / "models.xlsx"
    workbook.write_bytes(b"not used")

    args = xhs.parse_args([str(workbook)])

    assert args.excel_path == workbook
    assert args.output_root == xhs.OUTPUT_ROOT


def test_parse_args_rejects_missing_file(tmp_path: Path):
    with pytest.raises(SystemExit):
        xhs.parse_args([str(tmp_path / "missing.xlsx")])
```

- [ ] **Step 2: Run tests and verify CLI functions are missing**

Run:

```powershell
pytest tests/test_xhs_ccd_image_download.py -q
```

Expected: FAIL with `AttributeError` for `parse_args`.

- [ ] **Step 3: Implement CLI entry point**

Append to `scripts/download_xhs_ccd_images.py`:

```python
def parse_args(argv: list[str] | None = None):
    import argparse

    parser = argparse.ArgumentParser(description="小红书 CCD 出片图下载工具")
    parser.add_argument("excel_path", type=Path, help="CCD 型号 Excel 文件路径")
    parser.add_argument("--output-root", type=Path, default=OUTPUT_ROOT, help="图片输出根目录")
    parser.add_argument(
        "--profile-dir",
        type=Path,
        default=Path(".playwright-mcp") / "xhs-ccd-profile",
        help="独立浏览器配置目录",
    )
    args = parser.parse_args(argv)
    if not args.excel_path.exists():
        parser.error(f"Excel 文件不存在：{args.excel_path}")
    if args.excel_path.suffix.lower() != ".xlsx":
        parser.error(f"只支持 .xlsx 文件：{args.excel_path}")
    return args


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    print(f"读取 Excel：{args.excel_path}")
    tasks = load_model_tasks(args.excel_path, args.output_root)
    print(f"读取到 {len(tasks)} 个 CCD 型号任务。")
    if not tasks:
        print("没有可处理的 CCD 型号。")
        return 0

    browser = XhsBrowser(args.profile_dir)
    downloader = HttpImageDownloader()
    try:
        browser.ensure_login()
        summary = process_tasks(tasks, browser, downloader, RateLimiter())
        print("运行结束。")
        print(f"总型号：{summary.total}")
        print(f"已满跳过：{summary.skipped_full}")
        print(f"本次新增图片：{summary.saved}")
        print(f"不足 7 张型号：{summary.incomplete}")
        print(f"失败型号：{summary.failed}")
        return 0 if summary.failed == 0 else 1
    finally:
        downloader.close()
        browser.close()


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Create BAT launcher**

Create `run_xhs_ccd_download.bat` with:

```bat
@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"

set "EXCEL_PATH=%~1"
if "%EXCEL_PATH%"=="" (
  echo 请把 CCD 型号 Excel 文件拖到这个窗口，然后按回车：
  set /p EXCEL_PATH=
)

if "%EXCEL_PATH%"=="" (
  echo 未提供 Excel 文件路径。
  pause
  exit /b 1
)

python scripts\download_xhs_ccd_images.py "%EXCEL_PATH%"
set "EXIT_CODE=%ERRORLEVEL%"
echo.
echo 任务结束，退出码：%EXIT_CODE%
pause
exit /b %EXIT_CODE%
```

- [ ] **Step 5: Run unit tests and syntax check**

Run:

```powershell
pytest tests/test_xhs_ccd_image_download.py -q
python -m py_compile scripts/download_xhs_ccd_images.py
```

Expected: both commands exit `0`.

- [ ] **Step 6: Commit CLI and BAT**

```powershell
git add scripts/download_xhs_ccd_images.py tests/test_xhs_ccd_image_download.py run_xhs_ccd_download.bat
git commit -m "feat: add xhs ccd downloader launcher"
```

---

### Task 7: Manual Verification with the Sample Excel

**Files:**
- No code changes unless verification exposes a defect.

- [ ] **Step 1: Install Playwright browser if needed**

Run:

```powershell
python -m playwright install chromium
```

Expected: command exits `0`.

- [ ] **Step 2: Verify Excel parsing against the provided sample**

Run:

```powershell
python -c "from pathlib import Path; import importlib.util; p=Path('scripts/download_xhs_ccd_images.py'); s=importlib.util.spec_from_file_location('xhs', p); m=importlib.util.module_from_spec(s); s.loader.exec_module(m); tasks=m.load_model_tasks(r'C:\Users\19577\Desktop\ccd型号\佳能CCD完整型号表_联网核查补全.xlsx'); print(len(tasks)); print(tasks[0])"
```

Expected: prints a positive task count and the first task has `brand_dir='佳能'`.

- [ ] **Step 3: Create a one-row smoke-test workbook**

Run:

```powershell
python -c "from pathlib import Path; import openpyxl; src=Path(r'C:\Users\19577\Desktop\ccd型号\佳能CCD完整型号表_联网核查补全.xlsx'); dst=Path(r'.test-tmp\xhs-smoke\canon-one-row.xlsx'); dst.parent.mkdir(parents=True, exist_ok=True); wb=openpyxl.load_workbook(src); ws=wb.worksheets[0]; rows=list(ws.iter_rows(values_only=True)); out=openpyxl.Workbook(); ows=out.active; ows.title=ws.title; ows.append(rows[0]); ccd_row=next(row for row in rows[1:] if str(row[9]).strip().upper() == 'CCD'); ows.append(ccd_row); out.save(dst); print(dst)"
```

Expected:

- `.test-tmp\xhs-smoke\canon-one-row.xlsx` is created.
- The workbook contains the original header and one CCD data row.

- [ ] **Step 4: Run a real browser smoke test on the one-row workbook**

Run:

```powershell
python scripts\download_xhs_ccd_images.py ".test-tmp\xhs-smoke\canon-one-row.xlsx"
```

Expected:

- Browser opens visibly.
- If not logged in, the script pauses and waits for manual login.
- Script searches Xiaohongshu for the first model's `型号名 出片图`.
- Images are saved under `E:\Ai jjfajgsw\AIkefu\output\ccdcpt\佳能\<型号>\`.
- If selectors fail because Xiaohongshu changed markup, update only `XhsBrowser._search`, `XhsBrowser._note_links`, or `XhsBrowser._image_urls_from_note`.

- [ ] **Step 5: Run final verification**

Run:

```powershell
pytest tests/test_xhs_ccd_image_download.py -q
python -m py_compile scripts/download_xhs_ccd_images.py
```

Expected: both commands exit `0`.

- [ ] **Step 6: Commit any verification fixes**

If Step 3 required selector or parsing fixes:

```powershell
git add scripts/download_xhs_ccd_images.py tests/test_xhs_ccd_image_download.py
git commit -m "fix: stabilize xhs downloader smoke test"
```

If no fixes were required, do not create an empty commit.

---

## Self-Review

- Spec coverage: Excel reading, CCD filtering, search query generation, brand/model output folders, 7-image cap, resume behavior, independent browser profile, note-detail image extraction, video skipping, rate limiting, command-line output, and double-click `.bat` launch are covered by Tasks 1 through 7.
- Completion-marker scan: This plan contains no unresolved markers or vague implementation-only steps.
- Type consistency: `ModelTask`, `RunSummary`, `RateLimiter`, `XhsBrowser`, `HttpImageDownloader`, `load_model_tasks`, `process_tasks`, `parse_args`, and `main` are introduced before use and use consistent names across tests and implementation.
