from __future__ import annotations

import csv
import base64
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import re
import shutil

from moments_inventory.xlsx_reader import read_xlsx_rows_from_bytes
from moments_inventory.exporter import _write_workbook
from moments_inventory.showcase_brands import (
    BRAND_MODEL_ALIASES as _BRAND_ALIASES,
    derive_showcase_brand,
    normalize_showcase_brand,
    normalize_showcase_model_key,
)
from cryptography.hazmat.primitives.ciphers.aead import AESGCM


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
PUBLIC_SOURCE_LABEL = "星星ccd货源"

_SOURCE_ALIASES: dict[str, tuple[str, ...]] = {
    "型号": ("型号",),
    "价格": ("价格",),
    "状态": ("状态",),
    "备注名": ("备注名", "来源", "来源备注名"),
    "备注名wxid": ("备注名wxid", "来源 wxid", "来源wxid"),
    "发布时间": ("发布时间", "朋友圈发布时间"),
    "序列号": ("序列号", "编号"),
    "图片路径": ("图片路径", "图片本地路径", "机身图路径"),
    "视频路径": ("视频路径", "视频本地路径"),
    "原文文案": ("原文文案", "文案原文"),
    "备注": ("备注",),
    "是否需要人工复核": ("是否需要人工复核", "是否待人工补充"),
}

_IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".gif"}


@dataclass(slots=True)
class ShowcaseBuildResult:
    output_dir: Path
    product_count: int
    missing_assets_path: Path


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
        cost_price = _parse_int(source_row["价格"])
        display_copy = old.get("展示文案") or source_row["原文文案"]
        sample_key = old.get("出片图型号") or normalize_showcase_model_key(source_row["型号"])
        output_rows.append(
            [
                product_id,
                source_row["型号"],
                normalize_showcase_brand(
                    old.get("品牌") or "",
                    source_row["型号"],
                    source_row["原文文案"],
                ),
                cost_price,
                _parse_int(old.get("展示价")) or cost_price,
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


def build_showcase_site(
    manual_xlsx: str | Path,
    sample_assets_dir: str | Path,
    output_dir: str | Path,
    *,
    workspace_root: str | Path | None = None,
    access_password: str | None = None,
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

    _write_static_files(target_dir, encrypted=bool(access_password))
    products_payload = json.dumps({"products": products}, ensure_ascii=False, indent=2).encode("utf-8")
    products_path = target_dir / "products.json"
    encrypted_path = target_dir / "products.encrypted.json"
    if access_password:
        if products_path.exists():
            products_path.unlink()
        encrypted_path.write_text(
            json.dumps(encrypt_showcase_payload(products_payload, access_password), ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    else:
        if encrypted_path.exists():
            encrypted_path.unlink()
        products_path.write_text(products_payload.decode("utf-8") + "\n", encoding="utf-8")
    missing_path = target_dir / "showcase_missing_assets.csv"
    _write_missing_assets(missing_path, missing_rows)
    return ShowcaseBuildResult(target_dir, len(products), missing_path)


def encrypt_showcase_payload(plaintext: bytes, password: str) -> dict[str, object]:
    if not password:
        raise ValueError("access password must not be empty")
    salt = os.urandom(16)
    nonce = os.urandom(12)
    iterations = 200_000
    key = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations, dklen=32)
    ciphertext = AESGCM(key).encrypt(nonce, plaintext, salt)
    return {
        "version": 1,
        "kdf": "PBKDF2-HMAC-SHA256",
        "iterations": iterations,
        "cipher": "AES-256-GCM",
        "salt": _b64(salt),
        "nonce": _b64(nonce),
        "ciphertext": _b64(ciphertext),
    }


def decrypt_showcase_payload(payload: dict[str, object], password: str) -> bytes | None:
    try:
        salt = _unb64(str(payload["salt"]))
        nonce = _unb64(str(payload["nonce"]))
        ciphertext = _unb64(str(payload["ciphertext"]))
        iterations = int(payload["iterations"])
    except (KeyError, TypeError, ValueError):
        return None

    key = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations, dklen=32)
    try:
        return AESGCM(key).decrypt(nonce, ciphertext, salt)
    except Exception:
        return None


def _b64(value: bytes) -> str:
    return base64.b64encode(value).decode("ascii")


def _unb64(value: str) -> bytes:
    return base64.b64decode(value.encode("ascii"), validate=True)


def _read_rows(path: Path) -> list[list[object]]:
    return read_xlsx_rows_from_bytes(path.read_bytes())


def _header_map(header: list[object]) -> dict[str, int]:
    return {str(value or "").strip(): index for index, value in enumerate(header)}


def _canonical_source_map(header: list[object]) -> dict[str, int]:
    raw_map = _header_map(header)
    canonical: dict[str, int] = {}
    for field_name, aliases in _SOURCE_ALIASES.items():
        for alias in aliases:
            if alias in raw_map:
                canonical[field_name] = raw_map[alias]
                break
    return canonical


def _source_records(rows: list[list[object]]) -> list[dict[str, str]]:
    if not rows:
        return []
    canonical = _canonical_source_map(rows[0])
    records: list[dict[str, str]] = []
    for row in rows[1:]:
        model = _get_by_index(row, canonical.get("型号"))
        price = _get_by_index(row, canonical.get("价格"))
        if not model or not price:
            continue
        records.append(
            {
                field_name: _get_by_index(row, canonical.get(field_name))
                for field_name in _SOURCE_ALIASES
            }
        )
    return records


def _manual_rows_by_product_id(rows: list[list[object]]) -> dict[str, dict[str, str]]:
    if not rows:
        return {}
    header = [str(value or "").strip() for value in rows[0]]
    indexes = {name: index for index, name in enumerate(header)}
    product_id_index = indexes.get("商品ID")
    if product_id_index is None:
        return {}

    mapped: dict[str, dict[str, str]] = {}
    for row in rows[1:]:
        product_id = _get_by_index(row, product_id_index)
        if not product_id:
            continue
        mapped[product_id] = {
            header_name: _get_by_index(row, index)
            for header_name, index in indexes.items()
        }
    return mapped


def _manual_records(rows: list[list[object]]) -> list[dict[str, str]]:
    if not rows:
        return []
    header = [str(value or "").strip() for value in rows[0]]
    indexes = {name: index for index, name in enumerate(header)}
    return [
        {
            header_name: _get_by_index(row, indexes.get(header_name))
            for header_name in SHOWCASE_HEADERS
        }
        for row in rows[1:]
        if _get_by_index(row, indexes.get("商品ID"))
    ]


def _build_product_id(source_row: dict[str, str]) -> str:
    parts = [
        source_row["备注名wxid"] or source_row["备注名"],
        source_row["发布时间"],
        source_row["序列号"] or source_row["型号"],
    ]
    return "|".join(part for part in parts if part)


def _derive_brand(model: str) -> str:
    return derive_showcase_brand(model)


def _parse_int(value: object) -> int | None:
    digits = re.sub(r"[^\d]", "", str(value or ""))
    if not digits:
        return None
    return int(digits)


def _get_by_index(row: list[object], index: int | None) -> str:
    if index is None or index >= len(row):
        return ""
    value = row[index]
    if value is None:
        return ""
    return str(value).strip()


def _split_path_lines(value: str) -> list[str]:
    return [line.strip() for line in value.splitlines() if line.strip()]


def _copy_body_images(
    row: dict[str, str],
    workspace_root: Path,
    target_dir: Path,
    missing_rows: list[dict[str, str]],
) -> list[str]:
    copied: list[str] = []
    product_id = _safe_asset_segment(row["商品ID"])
    for raw_path in _split_path_lines(row["机身图路径"]):
        source = Path(raw_path)
        if not source.is_absolute():
            source = workspace_root / source
        if not source.exists():
            missing_rows.append(
                {
                    "商品ID": row["商品ID"],
                    "型号": row["型号"],
                    "类型": "机身图",
                    "路径": raw_path,
                }
            )
            continue
        destination = target_dir / "assets" / "body" / product_id / source.name
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
        copied.append(destination.relative_to(target_dir).as_posix())
    return copied


def _copy_sample_images(
    row: dict[str, str],
    sample_assets_dir: Path,
    target_dir: Path,
    missing_rows: list[dict[str, str]],
) -> list[str]:
    sample_key = row["出片图型号"] or normalize_showcase_model_key(row["型号"])
    source_dir = sample_assets_dir / sample_key
    if not source_dir.exists():
        missing_rows.append(
            {
                "商品ID": row["商品ID"],
                "型号": row["型号"],
                "类型": "出片图",
                "路径": source_dir.as_posix(),
            }
        )
        return []

    copied: list[str] = []
    for source in sorted(source_dir.iterdir()):
        if not source.is_file() or source.suffix.lower() not in _IMAGE_EXTENSIONS:
            continue
        destination = target_dir / "assets" / "samples" / sample_key / source.name
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
        copied.append(destination.relative_to(target_dir).as_posix())
    if not copied:
        missing_rows.append(
            {
                "商品ID": row["商品ID"],
                "型号": row["型号"],
                "类型": "出片图",
                "路径": source_dir.as_posix(),
            }
        )
    return copied


def _catalog_product(
    row: dict[str, str],
    body_images: list[str],
    sample_images: list[str],
) -> dict[str, object]:
    return {
        "productId": row["商品ID"],
        "model": row["型号"],
        "brand": row["品牌"],
        "costPrice": _parse_int(row["成本价"]),
        "displayPrice": _parse_int(row["展示价"]),
        "publishedAt": row["发布时间"],
        "source": PUBLIC_SOURCE_LABEL,
        "rawCopy": row["原文文案"],
        "displayCopy": row["展示文案"] or row["原文文案"],
        "sampleModelKey": row["出片图型号"],
        "bodyImages": body_images,
        "sampleImages": sample_images,
    }


def _write_missing_assets(path: Path, missing_rows: list[dict[str, str]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["商品ID", "型号", "类型", "路径"])
        writer.writeheader()
        writer.writerows(missing_rows)


def _write_static_files(target_dir: Path, *, encrypted: bool = False) -> None:
    (target_dir / "index.html").write_text(
        f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>星星CCD 当前库存</title>
  <link rel="icon" href="data:,">
  <link rel="stylesheet" href="styles.css">
</head>
<body>
  <div class="site-watermark" aria-hidden="true"></div>
  <main class="page-shell">
    <section id="accessGate" class="access-gate" {"hidden" if not encrypted else ""}>
      <div class="gate-panel">
        <p class="eyebrow">Xingxing CCD</p>
        <h1>星星CCD库存展示</h1>
        <p class="gate-copy">请输入本周口令查看当前库存。口令错误或过期时，请私信星星CCD获取最新口令。</p>
        <form id="accessForm" class="access-form">
          <input type="hidden" name="username" autocomplete="username" value="xingxing-ccd-customer">
          <label class="field">
            <span>本周口令</span>
            <input id="accessPasswordInput" name="password" type="password" autocomplete="current-password" placeholder="输入本周口令">
          </label>
          <label class="remember-row">
            <input id="rememberAccessInput" type="checkbox" checked>
            <span>记住本设备 7 天</span>
          </label>
          <button class="access-button" type="submit">进入库存</button>
          <p id="accessError" class="access-error" hidden></p>
        </form>
      </div>
    </section>

    <section id="inventoryApp" {"hidden" if encrypted else ""}>
    <header class="inventory-header">
      <div>
        <p class="eyebrow">Xingxing CCD Stock</p>
        <h1>星星CCD 当前库存</h1>
      </div>
      <p id="resultCount" class="result-count">0 台</p>
    </header>

    <section class="ownership-notice" aria-label="库存归属声明">
      <div>
        <h2>星星CCD库存声明</h2>
        <p>本库存展示页归星星CCD所有，仅供星星CCD客户查看。未经许可，任何代理、货源、同行不得复制、转发或用于二次销售。</p>
        <p>非授权渠道转发的库存信息可能存在价格错误、库存过期、无法发货、售后无法保障等问题。授权合作方名单以本页面公示为准。</p>
      </div>
      <div class="authorized-list">
        <span>当前授权合作方：星星CCD直营</span>
      </div>
    </section>

    <section class="toolbar" aria-label="库存筛选">
      <label class="field field-search">
        <span>搜索</span>
        <input id="searchInput" type="search" placeholder="型号、品牌、文案关键词">
      </label>
      <label class="field">
        <span>品牌</span>
        <select id="brandFilter">
          <option value="">全部品牌</option>
        </select>
      </label>
      <label class="field">
        <span>价格区间</span>
        <select id="priceFilter">
          <option value="">全部价格</option>
          <option value="0-99">100 以下</option>
          <option value="100-199">100-199</option>
          <option value="200-299">200-299</option>
          <option value="300-499">300-499</option>
          <option value="500-799">500-799</option>
          <option value="800-999999">800 以上</option>
        </select>
      </label>
      <label class="field">
        <span>图片</span>
        <select id="imageFilter">
          <option value="">全部商品</option>
          <option value="body">有机身图</option>
          <option value="sample">有出片图</option>
          <option value="both">机身图和出片图都有</option>
        </select>
      </label>
      <label class="field">
        <span>排序</span>
        <select id="sortFilter">
          <option value="latest">最新发布</option>
          <option value="priceAsc">价格低到高</option>
          <option value="priceDesc">价格高到低</option>
        </select>
      </label>
    </section>

    <section id="productGrid" class="product-grid" aria-live="polite"></section>
    <section id="emptyState" class="empty-state" hidden>没有匹配的库存</section>
    <button id="loadMoreButton" class="load-more-button" type="button" hidden>加载更多</button>
    </section>
  </main>
  <script src="app.js"></script>
</body>
</html>
""",
        encoding="utf-8",
    )
    (target_dir / "styles.css").write_text(
        """:root {
  --ink: #192022;
  --muted: #65706f;
  --paper: #fbfbf8;
  --surface: #ffffff;
  --line: #d9ddd7;
  --line-strong: #b8c0b9;
  --pine: #21453f;
  --mint: #d7e7dd;
  --coral: #d96f55;
  --amber: #c79a43;
  --shadow: 0 18px 38px rgba(25, 32, 34, 0.11);
}

* {
  box-sizing: border-box;
}

[hidden] {
  display: none !important;
}

body {
  margin: 0;
  background:
    linear-gradient(90deg, rgba(33, 69, 63, 0.06) 1px, transparent 1px),
    linear-gradient(180deg, #f8faf7 0%, #eef3ee 100%);
  background-size: 28px 28px, 100% 100%;
  color: var(--ink);
  font-family: "Microsoft YaHei", "PingFang SC", "Noto Sans CJK SC", sans-serif;
}

.site-watermark {
  position: fixed;
  inset: -80px;
  z-index: 20;
  pointer-events: none;
  opacity: 0.13;
  transform: rotate(-24deg);
  transform-origin: center;
  background-image: repeating-linear-gradient(
    0deg,
    transparent 0,
    transparent 74px,
    rgba(25, 32, 34, 0.34) 75px,
    rgba(25, 32, 34, 0.34) 76px,
    transparent 77px,
    transparent 150px
  );
}

.site-watermark::before {
  content: "星星CCD  星星CCD  星星CCD  星星CCD";
  position: absolute;
  inset: 0;
  color: rgba(25, 32, 34, 0.54);
  font-size: 28px;
  font-weight: 900;
  line-height: 150px;
  letter-spacing: 0.18em;
  word-spacing: 46px;
  white-space: pre-wrap;
}

.page-shell {
  position: relative;
  z-index: 1;
  width: min(1440px, 100%);
  margin: 0 auto;
  padding: 22px;
}

.access-gate {
  min-height: 100vh;
  display: grid;
  place-items: center;
  padding: 28px 0;
}

.gate-panel {
  width: min(520px, 100%);
  padding: 30px;
  border: 2px solid var(--ink);
  background: rgba(255, 255, 255, 0.94);
  box-shadow: var(--shadow);
}

.gate-copy {
  margin: 16px 0 22px;
  color: var(--muted);
  line-height: 1.75;
}

.access-form {
  display: grid;
  gap: 14px;
}

.remember-row {
  display: flex;
  align-items: center;
  gap: 8px;
  color: var(--muted);
  font-size: 14px;
}

.access-button,
.load-more-button {
  min-height: 44px;
  border: 0;
  background: var(--pine);
  color: #fff;
  font-weight: 900;
  cursor: pointer;
}

.access-button:hover,
.load-more-button:hover {
  background: #17322e;
}

.access-error {
  margin: 0;
  padding: 10px 12px;
  border: 1px solid rgba(217, 111, 85, 0.45);
  background: rgba(217, 111, 85, 0.1);
  color: #9d3e2e;
  font-weight: 700;
}

.inventory-header {
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  gap: 16px;
  padding: 18px 0 16px;
  border-bottom: 2px solid var(--ink);
}

.eyebrow {
  margin: 0 0 8px;
  color: var(--coral);
  font-size: 12px;
  font-weight: 800;
  letter-spacing: 0.12em;
  text-transform: uppercase;
}

h1 {
  margin: 0;
  font-family: "SimSun", "Songti SC", serif;
  font-size: clamp(34px, 5vw, 72px);
  line-height: 0.96;
  letter-spacing: 0;
}

.result-count {
  margin: 0;
  min-width: 86px;
  padding: 10px 12px;
  border: 1px solid var(--line-strong);
  background: var(--mint);
  color: var(--pine);
  font-weight: 800;
  text-align: center;
}

.ownership-notice {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 220px;
  gap: 18px;
  margin: 18px 0;
  padding: 18px;
  border: 1px solid var(--line-strong);
  background: rgba(255, 255, 255, 0.78);
}

.ownership-notice h2 {
  margin: 0 0 8px;
  font-size: 18px;
}

.ownership-notice p {
  margin: 6px 0;
  color: var(--muted);
  line-height: 1.7;
}

.authorized-list {
  align-self: stretch;
  display: grid;
  align-content: center;
  gap: 8px;
  padding: 14px;
  border: 1px solid var(--line);
  background: var(--mint);
}

.authorized-list span {
  color: var(--muted);
  font-size: 12px;
  font-weight: 800;
}

.authorized-list strong {
  color: var(--pine);
  font-size: 18px;
}

.toolbar {
  position: sticky;
  top: 0;
  z-index: 10;
  display: grid;
  grid-template-columns: minmax(220px, 1.4fr) repeat(4, minmax(132px, 0.7fr));
  gap: 10px;
  padding: 14px 0;
  background: rgba(248, 250, 247, 0.94);
  backdrop-filter: blur(12px);
  border-bottom: 1px solid var(--line);
}

.field {
  display: grid;
  gap: 6px;
}

.field span {
  color: var(--muted);
  font-size: 12px;
  font-weight: 800;
}

input,
select {
  width: 100%;
  height: 42px;
  border: 1px solid var(--line-strong);
  border-radius: 6px;
  background: var(--surface);
  color: var(--ink);
  font: inherit;
  font-size: 14px;
  padding: 0 11px;
}

input:focus,
select:focus {
  outline: 3px solid rgba(33, 69, 63, 0.18);
  border-color: var(--pine);
}

.product-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(286px, 1fr));
  gap: 14px;
  padding-top: 16px;
}

.product-card {
  border: 1px solid var(--line);
  border-radius: 8px;
  background: var(--surface);
  box-shadow: var(--shadow);
  overflow: hidden;
}

.product-main-image {
  width: 100%;
  aspect-ratio: 4 / 3;
  background: #e7ebe6;
  object-fit: cover;
  display: block;
}

.product-content {
  display: grid;
  gap: 11px;
  padding: 14px;
}

.product-title-row {
  display: flex;
  justify-content: space-between;
  gap: 10px;
  align-items: flex-start;
}

.product-title-row h2 {
  margin: 0;
  font-size: 18px;
  line-height: 1.25;
  letter-spacing: 0;
}

.price {
  flex: 0 0 auto;
  color: var(--coral);
  font-size: 20px;
  font-weight: 900;
}

.meta-row,
.sample-title {
  color: var(--muted);
  font-size: 12px;
  font-weight: 700;
}

.copy {
  margin: 0;
  color: #2d3435;
  line-height: 1.62;
  white-space: pre-wrap;
  word-break: break-word;
}

.image-strip {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 6px;
}

.image-strip img {
  width: 100%;
  aspect-ratio: 1;
  border-radius: 6px;
  object-fit: cover;
  background: #e7ebe6;
}

.empty-state {
  margin-top: 18px;
  padding: 28px;
  border: 1px dashed var(--line-strong);
  background: var(--paper);
  text-align: center;
  color: var(--muted);
}

.load-more-button {
  display: block;
  width: min(360px, 100%);
  margin: 20px auto 0;
  height: 46px;
  border: 1px solid var(--pine);
  border-radius: 6px;
  background: var(--pine);
  color: #fff;
  font: inherit;
  font-weight: 900;
  cursor: pointer;
}

.load-more-button:hover {
  background: #17322e;
}

@media (max-width: 860px) {
  .page-shell {
    padding: 14px;
  }

  .inventory-header {
    align-items: flex-start;
    flex-direction: column;
  }

  .ownership-notice {
    grid-template-columns: 1fr;
  }

  .toolbar {
    grid-template-columns: 1fr 1fr;
  }

  .field-search {
    grid-column: 1 / -1;
  }
}

@media (max-width: 520px) {
  .toolbar {
    grid-template-columns: 1fr;
  }

  .product-grid {
    grid-template-columns: 1fr;
  }
}
""",
        encoding="utf-8",
    )
    (target_dir / "app.js").write_text(
        ("""const PRODUCTS_URL = "__PRODUCTS_URL__";
const PRODUCTS_ENCRYPTED = __PRODUCTS_ENCRYPTED__;
const ACCESS_STORAGE_KEY = "xingxing-ccd-access-password";
const ACCESS_STORAGE_EXPIRES_KEY = "xingxing-ccd-access-expires";

const state = {
  products: [],
  query: "",
  brand: "",
  price: "",
  image: "",
  sort: "latest",
};

const searchInput = document.getElementById("searchInput");
const brandFilter = document.getElementById("brandFilter");
const priceFilter = document.getElementById("priceFilter");
const imageFilter = document.getElementById("imageFilter");
const sortFilter = document.getElementById("sortFilter");
const productGrid = document.getElementById("productGrid");
const emptyState = document.getElementById("emptyState");
const resultCount = document.getElementById("resultCount");
const loadMoreButton = document.getElementById("loadMoreButton");
const accessGate = document.getElementById("accessGate");
const inventoryApp = document.getElementById("inventoryApp");
const accessForm = document.getElementById("accessForm");
const accessPasswordInput = document.getElementById("accessPasswordInput");
const rememberAccessInput = document.getElementById("rememberAccessInput");
const accessError = document.getElementById("accessError");

const PAGE_SIZE = 120;
let visibleLimit = PAGE_SIZE;

function priceText(value) {
  return Number.isFinite(value) ? `${value} 元` : "询价";
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function inPriceRange(product) {
  if (!state.price) return true;
  const [min, max] = state.price.split("-").map((part) => Number.parseInt(part, 10));
  const price = product.displayPrice;
  return Number.isFinite(price) && price >= min && price <= max;
}

function matchesImages(product) {
  if (!state.image) return true;
  const hasBody = product.bodyImages.length > 0;
  const hasSample = product.sampleImages.length > 0;
  if (state.image === "body") return hasBody;
  if (state.image === "sample") return hasSample;
  if (state.image === "both") return hasBody && hasSample;
  return true;
}

function matchesSearch(product) {
  if (!state.query) return true;
  const haystack = [
    product.model,
    product.brand,
    product.displayCopy,
    product.rawCopy,
  ].join(" ").toLowerCase();
  return haystack.includes(state.query);
}

function filteredProducts() {
  const products = state.products
    .filter((product) => !state.brand || product.brand === state.brand)
    .filter(inPriceRange)
    .filter(matchesImages)
    .filter(matchesSearch);
  products.sort((left, right) => {
    if (state.sort === "priceAsc") return (left.displayPrice || 0) - (right.displayPrice || 0);
    if (state.sort === "priceDesc") return (right.displayPrice || 0) - (left.displayPrice || 0);
    return String(right.publishedAt).localeCompare(String(left.publishedAt));
  });
  return products;
}

function renderBrands() {
  const brands = [...new Set(state.products.map((product) => product.brand).filter(Boolean))].sort();
  for (const brand of brands) {
    const option = document.createElement("option");
    option.value = brand;
    option.textContent = brand;
    brandFilter.appendChild(option);
  }
}

function renderImages(images, className) {
  if (images.length === 0) return "";
  return `<div class="${className}">${images.map((src) => `<img src="${src}" alt="">`).join("")}</div>`;
}

function renderProduct(product) {
  const mainImage = product.bodyImages[0]
    ? `<img class="product-main-image" src="${product.bodyImages[0]}" alt="">`
    : `<div class="product-main-image" aria-label="暂无机身图"></div>`;
  const sampleStrip = product.sampleImages.length
    ? `<div class="sample-title">出片参考</div>${renderImages(product.sampleImages.slice(0, 4), "image-strip")}`
    : "";
  return `<article class="product-card">
    ${mainImage}
    <div class="product-content">
      <div class="product-title-row">
        <h2>${escapeHtml(product.model)}</h2>
        <div class="price">${priceText(product.displayPrice)}</div>
      </div>
      <div class="meta-row">${escapeHtml(product.brand || "未识别品牌")}</div>
      <p class="copy">${escapeHtml(product.displayCopy || product.rawCopy || "")}</p>
      ${sampleStrip}
    </div>
  </article>`;
}

function render() {
  const products = filteredProducts();
  const visibleProducts = products.slice(0, visibleLimit);
  resultCount.textContent = `${visibleProducts.length} / ${products.length} 台`;
  productGrid.innerHTML = visibleProducts.map(renderProduct).join("");
  emptyState.hidden = products.length !== 0;
  loadMoreButton.hidden = visibleLimit >= products.length;
}

function resetAndRender() {
  visibleLimit = PAGE_SIZE;
  render();
}

searchInput.addEventListener("input", (event) => {
  state.query = event.target.value.trim().toLowerCase();
  resetAndRender();
});
brandFilter.addEventListener("change", (event) => {
  state.brand = event.target.value;
  resetAndRender();
});
priceFilter.addEventListener("change", (event) => {
  state.price = event.target.value;
  resetAndRender();
});
imageFilter.addEventListener("change", (event) => {
  state.image = event.target.value;
  resetAndRender();
});
sortFilter.addEventListener("change", (event) => {
  state.sort = event.target.value;
  resetAndRender();
});
loadMoreButton.addEventListener("click", () => {
  visibleLimit += PAGE_SIZE;
  render();
});

async function loadPlainProducts() {
  const response = await fetch(PRODUCTS_URL);
  if (!response.ok) throw new Error("库存文件加载失败");
  return response.json();
}

function base64ToBytes(value) {
  const binary = atob(value);
  const bytes = new Uint8Array(binary.length);
  for (let index = 0; index < binary.length; index += 1) {
    bytes[index] = binary.charCodeAt(index);
  }
  return bytes;
}

async function decryptProductsPayload(payload, password) {
  const encoder = new TextEncoder();
  const passwordKey = await crypto.subtle.importKey(
    "raw",
    encoder.encode(password),
    "PBKDF2",
    false,
    ["deriveKey"],
  );
  const key = await crypto.subtle.deriveKey(
    {
      name: "PBKDF2",
      salt: base64ToBytes(payload.salt),
      iterations: Number(payload.iterations),
      hash: "SHA-256",
    },
    passwordKey,
    { name: "AES-GCM", length: 256 },
    false,
    ["decrypt"],
  );
  const plaintext = await crypto.subtle.decrypt(
    {
      name: "AES-GCM",
      iv: base64ToBytes(payload.nonce),
      additionalData: base64ToBytes(payload.salt),
    },
    key,
    base64ToBytes(payload.ciphertext),
  );
  return JSON.parse(new TextDecoder().decode(plaintext));
}

function showAccessError(message) {
  accessError.textContent = message;
  accessError.hidden = false;
}

function rememberPassword(password) {
  if (!rememberAccessInput.checked) return;
  const expiresAt = Date.now() + 7 * 24 * 60 * 60 * 1000;
  localStorage.setItem(ACCESS_STORAGE_KEY, password);
  localStorage.setItem(ACCESS_STORAGE_EXPIRES_KEY, String(expiresAt));
}

function readRememberedPassword() {
  const expiresAt = Number(localStorage.getItem(ACCESS_STORAGE_EXPIRES_KEY) || "0");
  if (!expiresAt || Date.now() > expiresAt) {
    localStorage.removeItem(ACCESS_STORAGE_KEY);
    localStorage.removeItem(ACCESS_STORAGE_EXPIRES_KEY);
    return "";
  }
  return localStorage.getItem(ACCESS_STORAGE_KEY) || "";
}

function enterInventory(data) {
  state.products = Array.isArray(data.products) ? data.products : [];
  accessGate.hidden = true;
  inventoryApp.hidden = false;
  renderBrands();
  render();
}

async function unlockEncryptedProducts(password) {
  const response = await fetch(PRODUCTS_URL);
  if (!response.ok) throw new Error("库存文件加载失败");
  const encryptedPayload = await response.json();
  return decryptProductsPayload(encryptedPayload, password);
}

async function loadProducts() {
  if (!PRODUCTS_ENCRYPTED) {
    enterInventory(await loadPlainProducts());
    return;
  }

  const rememberedPassword = readRememberedPassword();
  if (rememberedPassword) {
    try {
      enterInventory(await unlockEncryptedProducts(rememberedPassword));
      return;
    } catch {
      localStorage.removeItem(ACCESS_STORAGE_KEY);
      localStorage.removeItem(ACCESS_STORAGE_EXPIRES_KEY);
    }
  }

  accessGate.hidden = false;
  inventoryApp.hidden = true;
}

accessForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  accessError.hidden = true;
  const password = accessPasswordInput.value.trim();
  if (!password) {
    showAccessError("请输入本周口令。");
    return;
  }
  try {
    const data = await unlockEncryptedProducts(password);
    rememberPassword(password);
    enterInventory(data);
  } catch {
    showAccessError("口令错误或已过期，请私信星星CCD获取最新口令。");
  }
});

loadProducts().catch(() => {
  if (PRODUCTS_ENCRYPTED) {
    showAccessError("库存文件加载失败，请稍后重试。");
    accessGate.hidden = false;
    inventoryApp.hidden = true;
    return;
  }
  emptyState.hidden = false;
  emptyState.textContent = "库存文件加载失败，请稍后重试。";
});
""")
        .replace("__PRODUCTS_URL__", "products.encrypted.json" if encrypted else "products.json")
        .replace("__PRODUCTS_ENCRYPTED__", "true" if encrypted else "false"),
        encoding="utf-8",
    )


def _safe_asset_segment(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._\-\u4e00-\u9fff]+", "_", value).strip("._")
    return cleaned or "product"
