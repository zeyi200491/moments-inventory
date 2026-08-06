# CCD Inventory Showcase Site Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build an Excel-managed static CCD inventory showcase site with one command to merge daily inventory into a manual workbook and one command to generate publishable site files.

**Architecture:** Add a focused Python module `moments_inventory.showcase` that owns workbook merging, model key normalization, sample-image discovery, static catalog generation, and static asset copying. Extend the existing CLI with `showcase-merge` and `showcase-build` commands, then add Windows `.bat` wrappers for daily use. The generated site is a static HTML/CSS/JS bundle reading `products.json`, so it can be hosted anywhere without a live backend.

**Tech Stack:** Python 3.11+, existing XLSX writer/reader helpers, pytest, vanilla HTML/CSS/JavaScript static site, Windows batch scripts.

---

## File Structure

- Create `src/moments_inventory/showcase.py`: data classes, workbook merge, catalog build, static site generation.
- Modify `src/moments_inventory/cli.py`: add `showcase-merge` and `showcase-build` subcommands.
- Create `tests/test_showcase.py`: focused tests for merge preservation, hidden filtering, image matching, and catalog output.
- Create `publish_showcase_site.bat`: double-click wrapper for building the static site from the manual workbook.
- Modify `run_full_mode.bat`: append a merge step after the full inventory run, keeping existing behavior intact.
- Create `showcase_assets/.gitkeep`: default location for user-maintained sample output folders.
- Generated at runtime, not committed: `manual/客户展示库存.xlsx`, `site_dist/`, `output/showcase_missing_assets.csv`.

---

### Task 1: Showcase Model Normalization

**Files:**
- Create: `src/moments_inventory/showcase.py`
- Test: `tests/test_showcase.py`

- [ ] **Step 1: Write failing tests for model key normalization**

Add to `tests/test_showcase.py`:

```python
from moments_inventory.showcase import normalize_showcase_model_key


def test_normalize_showcase_model_key_collapses_spacing_and_brand_aliases() -> None:
    assert normalize_showcase_model_key("三星 A40") == "三星a40"
    assert normalize_showcase_model_key("samsung-a40") == "三星a40"
    assert normalize_showcase_model_key("佳能 IXUS 95") == "佳能ixus95"
    assert normalize_showcase_model_key("Canon_ixus95") == "佳能ixus95"
```

- [ ] **Step 2: Run the test to verify it fails**

Run:

```bash
pytest tests/test_showcase.py::test_normalize_showcase_model_key_collapses_spacing_and_brand_aliases -v
```

Expected: FAIL with `ModuleNotFoundError` or missing function.

- [ ] **Step 3: Implement minimal normalization**

Create `src/moments_inventory/showcase.py` with:

```python
from __future__ import annotations

import re


_BRAND_ALIASES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("佳能", ("佳能", "canon")),
    ("索尼", ("索尼", "sony")),
    ("富士", ("富士", "fujifilm", "fuji")),
    ("奥林巴斯", ("奥林巴斯", "olympus")),
    ("柯达", ("柯达", "kodak")),
    ("尼康", ("尼康", "nikon")),
    ("卡西欧", ("卡西欧", "casio")),
    ("三星", ("三星", "samsung")),
    ("松下", ("松下", "panasonic")),
)


def normalize_showcase_model_key(value: str) -> str:
    compact = re.sub(r"[\s\-_]+", "", value.strip()).lower()
    for brand, aliases in _BRAND_ALIASES:
        for alias in aliases:
            alias_key = re.sub(r"[\s\-_]+", "", alias).lower()
            if compact.startswith(alias_key):
                return f"{brand}{compact[len(alias_key):]}"
    return compact
```

- [ ] **Step 4: Run the test to verify it passes**

Run:

```bash
pytest tests/test_showcase.py::test_normalize_showcase_model_key_collapses_spacing_and_brand_aliases -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/moments_inventory/showcase.py tests/test_showcase.py
git commit -m "feat: add showcase model normalization"
```

---

### Task 2: Manual Workbook Merge

**Files:**
- Modify: `src/moments_inventory/showcase.py`
- Modify: `tests/test_showcase.py`

- [ ] **Step 1: Write failing merge tests**

Add to `tests/test_showcase.py`:

```python
from pathlib import Path

from moments_inventory.exporter import _write_workbook
from moments_inventory.showcase import SHOWCASE_HEADERS, merge_showcase_workbook
from moments_inventory.ai_kefu.products import read_xlsx_rows_from_bytes


def _rows(path: Path) -> list[list[object]]:
    return read_xlsx_rows_from_bytes(path.read_bytes())


def test_merge_showcase_workbook_creates_manual_sheet(tmp_path: Path) -> None:
    source = tmp_path / "全量当前库.xlsx"
    manual = tmp_path / "客户展示库存.xlsx"
    _write_workbook(
        source,
        [
            ["型号", "价格", "状态", "备注名", "备注名wxid", "发布时间", "序列号", "图片路径", "视频路径", "原文文案", "备注", "是否需要人工复核"],
            ["三星a40", 99, "未售卖", "晨曦", "wxid_1", "2026-07-15T20:25:55+08:00", "8820", "media/r1/image-1.jpg", "", "99💰三星A40 特价", "", "否"],
        ],
    )

    result = merge_showcase_workbook(source, manual)

    rows = _rows(result)
    assert rows[0] == SHOWCASE_HEADERS
    assert rows[1][1] == "三星a40"
    assert rows[1][3] == 99
    assert rows[1][4] == 99
    assert rows[1][5] == "是"
    assert rows[1][10] == "99💰三星A40 特价"
    assert rows[1][11] == "media/r1/image-1.jpg"
    assert rows[1][12] == "三星a40"


def test_merge_showcase_workbook_preserves_manual_overrides(tmp_path: Path) -> None:
    source = tmp_path / "全量当前库.xlsx"
    manual = tmp_path / "客户展示库存.xlsx"
    _write_workbook(
        source,
        [
            ["型号", "价格", "状态", "备注名", "备注名wxid", "发布时间", "序列号", "图片路径", "视频路径", "原文文案", "备注", "是否需要人工复核"],
            ["三星a40", 99, "未售卖", "晨曦", "wxid_1", "2026-07-15T20:25:55+08:00", "8820", "media/r1/image-1.jpg", "", "原文新版", "", "否"],
        ],
    )
    _write_workbook(
        manual,
        [
            SHOWCASE_HEADERS,
            ["wxid_1|2026-07-15T20:25:55+08:00|8820", "三星a40", "三星", 99, 168, "否", "2026-07-15T20:25:55+08:00", "晨曦", "旧原文", "客户展示文案", "media/old/image.jpg", "media/old/video.mp4", "三星a40", "内部备注"],
        ],
    )

    merge_showcase_workbook(source, manual)

    rows = _rows(manual)
    assert rows[1][3] == 99
    assert rows[1][4] == 168
    assert rows[1][5] == "否"
    assert rows[1][8] == "原文新版"
    assert rows[1][9] == "客户展示文案"
    assert rows[1][10] == "media/r1/image-1.jpg"
    assert rows[1][12] == "三星a40"
    assert rows[1][13] == "内部备注"
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
pytest tests/test_showcase.py::test_merge_showcase_workbook_creates_manual_sheet tests/test_showcase.py::test_merge_showcase_workbook_preserves_manual_overrides -v
```

Expected: FAIL with missing names.

- [ ] **Step 3: Implement workbook merge**

Add to `src/moments_inventory/showcase.py`:

```python
from dataclasses import dataclass
from pathlib import Path

from moments_inventory.ai_kefu.products import read_xlsx_rows_from_bytes
from moments_inventory.exporter import _write_workbook


SHOWCASE_HEADERS = [
    "商品ID",
    "型号",
    "品牌",
    "成本价",
    "展示价",
    "是否展示",
    "发布时间",
    "来源",
    "原文文案",
    "展示文案",
    "机身图路径",
    "视频路径",
    "出片图型号",
    "备注",
]


def merge_showcase_workbook(source_xlsx: str | Path, manual_xlsx: str | Path) -> Path:
    source_path = Path(source_xlsx)
    manual_path = Path(manual_xlsx)
    manual_path.parent.mkdir(parents=True, exist_ok=True)
    source_rows = _read_rows(source_path)
    manual_rows = _read_rows(manual_path) if manual_path.exists() else []
    existing_by_id = _manual_rows_by_product_id(manual_rows)

    output_rows: list[list[str | int | None]] = [SHOWCASE_HEADERS]
    for source_row in _source_records(source_rows):
        product_id = _build_product_id(source_row)
        old = existing_by_id.get(product_id, {})
        display_copy = old.get("展示文案") or source_row["原文文案"]
        sample_key = old.get("出片图型号") or normalize_showcase_model_key(source_row["型号"])
        output_rows.append(
            [
                product_id,
                source_row["型号"],
                old.get("品牌") or _derive_brand(source_row["型号"]),
                _parse_int(source_row["价格"]),
                _parse_int(old.get("展示价")) or _parse_int(source_row["价格"]),
                old.get("是否展示") or "是",
                source_row["发布时间"],
                source_row["备注名"],
                source_row["原文文案"],
                display_copy,
                source_row["图片路径"],
                source_row["视频路径"],
                sample_key,
                old.get("备注") or "",
            ]
        )
    _write_workbook(manual_path, output_rows)
    return manual_path
```

Also add helper functions `_read_rows`, `_headers`, `_source_records`, `_manual_rows_by_product_id`, `_build_product_id`, `_derive_brand`, and `_parse_int` in the same file using direct header lookups and the known source headers from `exporter.HEADERS`.

- [ ] **Step 4: Run tests to verify they pass**

Run:

```bash
pytest tests/test_showcase.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/moments_inventory/showcase.py tests/test_showcase.py
git commit -m "feat: merge inventory into showcase workbook"
```

---

### Task 3: Static Catalog Generation

**Files:**
- Modify: `src/moments_inventory/showcase.py`
- Modify: `tests/test_showcase.py`

- [ ] **Step 1: Write failing catalog tests**

Add to `tests/test_showcase.py`:

```python
import json

from moments_inventory.showcase import build_showcase_site


def test_build_showcase_site_filters_hidden_products_and_copies_assets(tmp_path: Path) -> None:
    manual = tmp_path / "manual.xlsx"
    image = tmp_path / "output" / "media" / "r1" / "image-1.jpg"
    image.parent.mkdir(parents=True)
    image.write_bytes(b"body")
    sample = tmp_path / "sample_assets" / "三星a40" / "sample-1.jpg"
    sample.parent.mkdir(parents=True)
    sample.write_bytes(b"sample")
    _write_workbook(
        manual,
        [
            SHOWCASE_HEADERS,
            ["p1", "三星a40", "三星", 99, 168, "是", "2026-07-15T20:25:55+08:00", "晨曦", "原文", "展示文案", "output/media/r1/image-1.jpg", "", "三星a40", ""],
            ["p2", "索尼t70", "索尼", 99, 188, "否", "2026-07-16T20:25:55+08:00", "十一", "原文", "隐藏文案", "", "", "索尼t70", ""],
        ],
    )

    result = build_showcase_site(
        manual,
        tmp_path / "sample_assets",
        tmp_path / "site_dist",
        workspace_root=tmp_path,
    )

    products = json.loads((result.output_dir / "products.json").read_text(encoding="utf-8"))
    assert [item["productId"] for item in products["products"]] == ["p1"]
    assert products["products"][0]["bodyImages"] == ["assets/body/p1/image-1.jpg"]
    assert products["products"][0]["sampleImages"] == ["assets/samples/三星a40/sample-1.jpg"]
    assert (result.output_dir / "assets" / "body" / "p1" / "image-1.jpg").read_bytes() == b"body"
    assert (result.output_dir / "assets" / "samples" / "三星a40" / "sample-1.jpg").read_bytes() == b"sample"
    assert result.missing_assets_path.exists()
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
pytest tests/test_showcase.py::test_build_showcase_site_filters_hidden_products_and_copies_assets -v
```

Expected: FAIL with missing `build_showcase_site`.

- [ ] **Step 3: Implement static catalog generation**

Add to `src/moments_inventory/showcase.py`:

```python
import csv
import json
import shutil


@dataclass(slots=True)
class ShowcaseBuildResult:
    output_dir: Path
    product_count: int
    missing_assets_path: Path


def build_showcase_site(
    manual_xlsx: str | Path,
    sample_assets_dir: str | Path,
    output_dir: str | Path,
    *,
    workspace_root: str | Path | None = None,
) -> ShowcaseBuildResult:
    root = Path(workspace_root or ".").resolve()
    target_dir = Path(output_dir)
    target_dir.mkdir(parents=True, exist_ok=True)
    rows = _read_rows(Path(manual_xlsx))
    products: list[dict[str, object]] = []
    missing_rows: list[dict[str, str]] = []
    for row in _manual_records(rows):
        if row["是否展示"].strip() != "是":
            continue
        body_images = _copy_body_images(row, root, target_dir, missing_rows)
        sample_images = _copy_sample_images(row, Path(sample_assets_dir), target_dir, missing_rows)
        products.append(_catalog_product(row, body_images, sample_images))
    _write_static_files(target_dir)
    (target_dir / "products.json").write_text(
        json.dumps({"products": products}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    missing_path = target_dir / "showcase_missing_assets.csv"
    _write_missing_assets(missing_path, missing_rows)
    return ShowcaseBuildResult(target_dir, len(products), missing_path)
```

Also add `_manual_records`, `_split_path_lines`, `_copy_body_images`, `_copy_sample_images`, `_catalog_product`, `_write_missing_assets`, and `_write_static_files`.

- [ ] **Step 4: Run tests to verify they pass**

Run:

```bash
pytest tests/test_showcase.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/moments_inventory/showcase.py tests/test_showcase.py
git commit -m "feat: build showcase static catalog"
```

---

### Task 4: CLI Commands and Windows Scripts

**Files:**
- Modify: `src/moments_inventory/cli.py`
- Modify: `tests/test_cli_batch_run.py`
- Modify: `run_full_mode.bat`
- Create: `publish_showcase_site.bat`

- [ ] **Step 1: Write failing CLI parser test**

Add to `tests/test_cli_batch_run.py`:

```python
def test_cli_accepts_showcase_commands() -> None:
    parser = build_parser()

    merge_args = parser.parse_args([
        "showcase-merge",
        "--source-xlsx",
        "output/全量当前库.xlsx",
        "--manual-xlsx",
        "manual/客户展示库存.xlsx",
    ])
    build_args = parser.parse_args([
        "showcase-build",
        "--manual-xlsx",
        "manual/客户展示库存.xlsx",
        "--sample-assets-dir",
        "showcase_assets",
        "--output-dir",
        "site_dist",
    ])

    assert merge_args.command == "showcase-merge"
    assert build_args.command == "showcase-build"
```

- [ ] **Step 2: Run parser test to verify it fails**

Run:

```bash
pytest tests/test_cli_batch_run.py::test_cli_accepts_showcase_commands -v
```

Expected: FAIL because commands do not exist.

- [ ] **Step 3: Add CLI commands**

Modify `src/moments_inventory/cli.py`:

```python
from moments_inventory.showcase import build_showcase_site, merge_showcase_workbook
```

In `build_parser()` add:

```python
    showcase_merge_parser = subparsers.add_parser(
        "showcase-merge",
        help="merge raw inventory Excel into manual showcase Excel",
    )
    showcase_merge_parser.add_argument("--source-xlsx", default="output/全量当前库.xlsx")
    showcase_merge_parser.add_argument("--manual-xlsx", default="manual/客户展示库存.xlsx")

    showcase_build_parser = subparsers.add_parser(
        "showcase-build",
        help="build static CCD showcase site from manual showcase Excel",
    )
    showcase_build_parser.add_argument("--manual-xlsx", default="manual/客户展示库存.xlsx")
    showcase_build_parser.add_argument("--sample-assets-dir", default="showcase_assets")
    showcase_build_parser.add_argument("--output-dir", default="site_dist")
```

In `main()` before loading inventory settings:

```python
    if args.command == "showcase-merge":
        merge_showcase_workbook(args.source_xlsx, args.manual_xlsx)
        return 0

    if args.command == "showcase-build":
        build_showcase_site(args.manual_xlsx, args.sample_assets_dir, args.output_dir)
        return 0
```

- [ ] **Step 4: Add Windows wrappers**

Create `publish_showcase_site.bat`:

```bat
@echo off
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
  echo [ERROR] Missing .venv. Please run setup_windows.bat first.
  pause
  exit /b 1
)

".venv\Scripts\python.exe" -m moments_inventory.cli showcase-build --manual-xlsx "manual\客户展示库存.xlsx" --sample-assets-dir "showcase_assets" --output-dir "site_dist"
if errorlevel 1 (
  echo [ERROR] Showcase site build failed.
  pause
  exit /b 1
)

echo [OK] Showcase site built at site_dist
pause
```

Append to `run_full_mode.bat` after the full mode command succeeds:

```bat
".venv\Scripts\python.exe" -m moments_inventory.cli showcase-merge --source-xlsx "output\全量当前库.xlsx" --manual-xlsx "manual\客户展示库存.xlsx"
if errorlevel 1 (
  echo [ERROR] Showcase workbook merge failed.
  pause
  exit /b 1
)
```

- [ ] **Step 5: Run tests and inspect scripts**

Run:

```bash
pytest tests/test_cli_batch_run.py::test_cli_accepts_showcase_commands tests/test_showcase.py -v
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/moments_inventory/cli.py tests/test_cli_batch_run.py run_full_mode.bat publish_showcase_site.bat
git commit -m "feat: add showcase cli and scripts"
```

---

### Task 5: Static Site Usability and Full Verification

**Files:**
- Modify: `src/moments_inventory/showcase.py`
- Create: `showcase_assets/.gitkeep`
- Modify: `README.md`

- [ ] **Step 1: Add generated static site UI assets**

Implement `_write_static_files()` so it writes:

- `index.html`
- `styles.css`
- `app.js`

The UI must include:

- Search input.
- Brand select.
- Price select.
- Image select.
- Sort select.
- Product count.
- Product cards with display copy, body images, and sample images.

- [ ] **Step 2: Add static UI smoke test**

Extend `test_build_showcase_site_filters_hidden_products_and_copies_assets`:

```python
    html = (result.output_dir / "index.html").read_text(encoding="utf-8")
    css = (result.output_dir / "styles.css").read_text(encoding="utf-8")
    js = (result.output_dir / "app.js").read_text(encoding="utf-8")
    assert "CCD 当前库存" in html
    assert "brandFilter" in html
    assert "价格区间" in html
    assert ".product-card" in css
    assert "products.json" in js
```

- [ ] **Step 3: Add README usage section**

Add a concise Chinese section explaining:

```markdown
## CCD 客户展示站

日常流程：

1. 双击 `run_full_mode.bat` 刷库并更新 `manual/客户展示库存.xlsx`
2. 打开 `manual/客户展示库存.xlsx`，调整展示价、是否展示和展示文案
3. 把型号出片图放到 `showcase_assets/<出片图型号>/`
4. 双击 `publish_showcase_site.bat` 生成 `site_dist/`
5. 将 `site_dist/` 发布到线上静态托管
```

- [ ] **Step 4: Run full verification**

Run:

```bash
pytest tests/test_showcase.py tests/test_cli_batch_run.py::test_cli_accepts_showcase_commands -v
```

Expected: PASS.

Run:

```bash
.venv\Scripts\python.exe -m moments_inventory.cli showcase-merge --source-xlsx output\全量当前库.xlsx --manual-xlsx manual\客户展示库存.xlsx
.venv\Scripts\python.exe -m moments_inventory.cli showcase-build --manual-xlsx manual\客户展示库存.xlsx --sample-assets-dir showcase_assets --output-dir site_dist
```

Expected: `manual/客户展示库存.xlsx`, `site_dist/index.html`, `site_dist/products.json`, `site_dist/styles.css`, and `site_dist/app.js` exist. If current `output/media` is empty, generated products can still build with missing image rows recorded in `site_dist/showcase_missing_assets.csv`.

- [ ] **Step 5: Commit**

```bash
git add src/moments_inventory/showcase.py tests/test_showcase.py README.md showcase_assets/.gitkeep
git commit -m "feat: generate ccd showcase site"
```

---

## Self-Review

- Spec coverage: tasks cover manual workbook creation, manual override preservation, product hiding, body image copy, sample image matching, static products JSON, static UI, CLI, scripts, and usage docs.
- Scope: plan keeps the first version static and Excel-managed; no backend, database, login, order flow, or real-time management is included.
- Type consistency: CLI command names are `showcase-merge` and `showcase-build`; workbook headers are centralized in `SHOWCASE_HEADERS`; generated product JSON uses camelCase keys for frontend consumption.
