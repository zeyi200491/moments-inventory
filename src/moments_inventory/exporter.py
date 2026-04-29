from __future__ import annotations

from pathlib import Path
import re
from urllib.parse import parse_qsl, quote, urlencode, urlparse, urlunparse
from urllib.request import Request, urlopen
from xml.sax.saxutils import escape
import zipfile

from moments_inventory.models import InventoryRecord


HEADERS = [
    "型号",
    "价格",
    "状态",
    "来源备注名",
    "来源 wxid",
    "朋友圈发布时间",
    "编号",
    "图片本地路径",
    "视频本地路径",
    "文案原文",
    "备注",
    "是否待人工补充",
]

CURRENT_STATUSES = {"未售出", "未售卖"}


def _column_name(index: int) -> str:
    result = ""
    current = index
    while current > 0:
        current, remainder = divmod(current - 1, 26)
        result = chr(65 + remainder) + result
    return result


def _cell_xml(ref: str, value: str | int | None) -> str:
    if value is None:
        return f'<c r="{ref}"/>'
    if isinstance(value, int):
        return f'<c r="{ref}"><v>{value}</v></c>'
    return f'<c r="{ref}" t="inlineStr"><is><t>{escape(str(value))}</t></is></c>'


def _sheet_xml(rows: list[list[str | int | None]]) -> str:
    xml_rows: list[str] = []
    for row_index, row in enumerate(rows, start=1):
        cells = [
            _cell_xml(f"{_column_name(column_index)}{row_index}", value)
            for column_index, value in enumerate(row, start=1)
        ]
        xml_rows.append(f'<row r="{row_index}">{"".join(cells)}</row>')
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        f"<sheetData>{''.join(xml_rows)}</sheetData>"
        "</worksheet>"
    )


def _workbook_files(rows: list[list[str | int | None]]) -> dict[str, str]:
    return {
        "[Content_Types].xml": (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
            '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
            '<Default Extension="xml" ContentType="application/xml"/>'
            '<Override PartName="/xl/workbook.xml" '
            'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
            '<Override PartName="/xl/worksheets/sheet1.xml" '
            'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
            "</Types>"
        ),
        "_rels/.rels": (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" '
            'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" '
            'Target="xl/workbook.xml"/>'
            "</Relationships>"
        ),
        "xl/workbook.xml": (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
            'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
            '<sheets><sheet name="Sheet1" sheetId="1" r:id="rId1"/></sheets>'
            "</workbook>"
        ),
        "xl/_rels/workbook.xml.rels": (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" '
            'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" '
            'Target="worksheets/sheet1.xml"/>'
            "</Relationships>"
        ),
        "xl/worksheets/sheet1.xml": _sheet_xml(rows),
    }


def _write_workbook(path: Path, rows: list[list[str | int | None]]) -> None:
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for file_path, content in _workbook_files(rows).items():
            archive.writestr(file_path, content)


def _build_media_text(values: list[str]) -> str:
    return "\n".join(values)


def _sanitize_segment(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", value).strip("._")
    return cleaned or "record"


def _guess_extension(url: str, content_type: str | None, default: str) -> str:
    if content_type:
        normalized = content_type.split(";", 1)[0].strip().lower()
        by_type = {
            "image/jpeg": "jpg",
            "image/png": "png",
            "image/gif": "gif",
            "image/webp": "webp",
            "video/mp4": "mp4",
            "video/quicktime": "mov",
            "video/x-msvideo": "avi",
        }
        if normalized in by_type:
            return by_type[normalized]

    suffix = Path(urlparse(url).path).suffix.lower().lstrip(".")
    return suffix or default


def _build_download_urls(
    url: str,
    base_url: str | None,
    access_token: str | None,
) -> list[str]:
    if not url:
        return []

    parsed_url = urlparse(url)
    query = dict(parse_qsl(parsed_url.query, keep_blank_values=True))
    candidates: list[str] = []

    if base_url and access_token:
        parsed_base = urlparse(base_url.rstrip("/"))
        if (
            parsed_url.scheme == parsed_base.scheme
            and parsed_url.netloc == parsed_base.netloc
            and parsed_url.path.startswith("/api/v1/")
        ):
            query.setdefault("access_token", access_token)
            candidates.append(urlunparse(parsed_url._replace(query=urlencode(query))))

    if parsed_url.path == "/api/v1/sns/media/proxy":
        candidates.append(url)

    raw_media_url = query.get("url")
    if raw_media_url:
        candidates.append(raw_media_url)

    if (
        base_url
        and access_token
        and parsed_url.scheme in {"http", "https"}
        and parsed_url.path != "/api/v1/sns/media/proxy"
    ):
        candidates.append(
            f"{base_url.rstrip('/')}/api/v1/sns/media/proxy?"
            f"url={quote(url, safe='')}&access_token={quote(access_token, safe='')}"
        )

    candidates.append(url)
    return list(dict.fromkeys(candidates))


def _download_media(
    url: str,
    base_url: str | None,
    access_token: str | None,
) -> tuple[bytes, str | None] | None:
    headers = {"User-Agent": "Mozilla/5.0"}
    for candidate in _build_download_urls(url, base_url, access_token):
        request = Request(candidate, headers=headers)
        try:
            with urlopen(request, timeout=20) as response:
                return response.read(), response.headers.get("Content-Type")
        except Exception:
            continue
    return None


def _find_existing_media(record_dir: Path, prefix: str, index: int) -> Path | None:
    candidates = sorted(record_dir.glob(f"{prefix}-{index}.*"))
    return candidates[0] if candidates else None


def _write_media_file(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)


def _export_media_group(
    record: InventoryRecord,
    urls: list[str],
    media_root: Path,
    prefix: str,
    default_extension: str,
    failure_text: str,
    base_url: str | None,
    access_token: str | None,
) -> list[str]:
    exported_paths: list[str] = []
    record_dir = media_root / _sanitize_segment(record.record_key)

    for index, url in enumerate(urls, start=1):
        existing = _find_existing_media(record_dir, prefix, index)
        if existing:
            exported_paths.append(existing.relative_to(media_root.parent).as_posix())
            continue

        downloaded = _download_media(url, base_url, access_token)
        if not downloaded:
            if failure_text not in exported_paths:
                exported_paths.append(failure_text)
            continue

        content, content_type = downloaded
        extension = _guess_extension(url, content_type, default_extension)
        target_path = record_dir / f"{prefix}-{index}.{extension}"
        _write_media_file(target_path, content)
        exported_paths.append(target_path.relative_to(media_root.parent).as_posix())

    return exported_paths


def _export_media_files(
    records: list[InventoryRecord],
    media_root: Path,
    base_url: str | None,
    access_token: str | None,
) -> dict[str, tuple[list[str], list[str]]]:
    exported: dict[str, tuple[list[str], list[str]]] = {}
    for record in records:
        image_paths = _export_media_group(
            record,
            record.image_urls,
            media_root,
            prefix="image",
            default_extension="jpg",
            failure_text="图片未成功下载",
            base_url=base_url,
            access_token=access_token,
        )
        video_paths = _export_media_group(
            record,
            record.video_urls,
            media_root,
            prefix="video",
            default_extension="mp4",
            failure_text="视频未成功下载",
            base_url=base_url,
            access_token=access_token,
        )
        exported[record.record_key] = (image_paths, video_paths)
    return exported


def _to_rows(
    records: list[InventoryRecord],
    media_paths: dict[str, tuple[list[str], list[str]]],
) -> list[list[str | int | None]]:
    rows: list[list[str | int | None]] = [HEADERS]
    for record in records:
        image_paths, video_paths = media_paths.get(record.record_key, ([], []))
        rows.append(
            [
                record.model,
                record.price,
                record.status,
                record.remark_name,
                record.wxid,
                record.published_at.isoformat(),
                record.serial_no,
                _build_media_text(image_paths),
                _build_media_text(video_paths),
                record.content_text,
                record.note,
                "是" if record.needs_manual else "否",
            ]
        )
    return rows


def export_records(
    records: list[InventoryRecord],
    output_dir: str | Path,
    base_url: str | None = None,
    access_token: str | None = None,
) -> tuple[Path, Path]:
    target_dir = Path(output_dir)
    target_dir.mkdir(parents=True, exist_ok=True)
    media_root = target_dir / "media"
    media_root.mkdir(parents=True, exist_ok=True)
    current_path = target_dir / "当前在售库.xlsx"
    history_path = target_dir / "历史总库.xlsx"

    media_paths = _export_media_files(records, media_root, base_url, access_token)
    current_records = [record for record in records if record.status in CURRENT_STATUSES]
    current_rows = _to_rows(current_records, media_paths)
    history_rows = _to_rows(records, media_paths)

    _write_workbook(current_path, current_rows)
    _write_workbook(history_path, history_rows)
    return current_path, history_path
