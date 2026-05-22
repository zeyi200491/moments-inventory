from __future__ import annotations

from dataclasses import dataclass, replace
from io import BytesIO
from pathlib import Path
from xml.etree import ElementTree as ET
import re
import struct
import zipfile

from moments_inventory.ai_kefu.models import ProductRecord
from moments_inventory.ai_kefu.profit_engine import recommend_sale_price
from moments_inventory.exporter import HEADERS


_XML_NS = {"main": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
_REL_NS = {"rel": "http://schemas.openxmlformats.org/package/2006/relationships"}
_WORKBOOK_REL_NS = {
    "main": "http://schemas.openxmlformats.org/spreadsheetml/2006/main",
    "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
}
_OLE_SIGNATURE = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"
_OLE_END_OF_CHAIN = 0xFFFFFFFE
_OLE_FREE_SECTOR = 0xFFFFFFFF
_XLS_WORKSHEET_RECORD = 0x0000
_XLS_BOUNDSHEET = 0x0085
_XLS_BOF = 0x0809
_XLS_EOF = 0x000A
_XLS_SST = 0x00FC
_XLS_CONTINUE = 0x003C
_XLS_ROW = 0x0208
_XLS_LABEL = 0x0204
_XLS_LABEL_SST = 0x00FD
_XLS_NUMBER = 0x0203
_XLS_RK = 0x027E
_XLS_MULRK = 0x00BD
_KNOWN_BRANDS: tuple[tuple[str, tuple[str, ...]], ...] = (
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
_FUNCTIONAL_KEYWORDS = ("功能正常", "一切正常", "全部正常", "都正常")
_FAILED_MEDIA_TEXT = ("未成功下载", "下载失败")
_HEADER_ALIASES: dict[str, tuple[str, ...]] = {
    "型号": ("型号",),
    "价格": ("价格",),
    "状态": ("状态",),
    "备注名": ("备注名", "来源备注名"),
    "备注名wxid": ("备注名wxid", "来源 wxid", "来源wxid"),
    "发布时间": ("发布时间", "朋友圈发布时间"),
    "序列号": ("序列号", "编号"),
    "图片路径": ("图片路径", "图片本地路径"),
    "视频路径": ("视频路径", "视频本地路径"),
    "原文文案": ("原文文案", "文案原文"),
    "备注": ("备注",),
    "是否需要人工复核": ("是否需要人工复核", "是否待人工补充"),
}


@dataclass(slots=True)
class _OleDirectoryEntry:
    name: str
    object_type: int
    start_sector: int
    stream_size: int


def import_products_from_xlsx(xlsx_path: str | Path) -> list[ProductRecord]:
    return import_products_from_xlsx_bytes(Path(xlsx_path).read_bytes())


def import_products_from_xlsx_bytes(xlsx_bytes: bytes) -> list[ProductRecord]:
    rows = read_xlsx_rows_from_bytes(xlsx_bytes)
    return import_products_from_rows(rows)


def import_products_from_rows(rows: list[list[object]]) -> list[ProductRecord]:
    return _build_products_from_rows(rows)


def read_xlsx_rows_from_bytes(xlsx_bytes: bytes) -> list[list[object]]:
    return _read_workbook_rows(xlsx_bytes)


def _build_products_from_rows(rows: list[list[object]]) -> list[ProductRecord]:
    if not rows:
        return []

    header = [str(value or "").strip() for value in rows[0]]
    header_map = {name: index for index, name in enumerate(header)}
    canonical_header_map = _build_canonical_header_map(header_map)
    products: list[ProductRecord] = []
    seen_product_ids: dict[str, int] = {}
    for row in rows[1:]:
        model = _get_cell(row, canonical_header_map, HEADERS[0])
        if not model:
            continue

        cost_price = _parse_price(_get_cell(row, canonical_header_map, HEADERS[1]))
        if cost_price is None:
            continue

        image_path = _get_cell(row, canonical_header_map, HEADERS[7])
        video_path = _get_cell(row, canonical_header_map, HEADERS[8])
        raw_copy = _get_cell(row, canonical_header_map, HEADERS[9])
        source_wxid = _get_cell(row, canonical_header_map, HEADERS[4])
        published_at = _get_cell(row, canonical_header_map, HEADERS[5])
        source_record_id = _get_cell(row, canonical_header_map, HEADERS[6]) or model
        product_id = _build_unique_product_id(
            seen_product_ids,
            source_record_id=source_record_id,
            model=model,
            source_wxid=source_wxid,
            published_at=published_at,
        )
        brand, model_std = _derive_brand_and_model(model)
        products.append(
            ProductRecord(
                product_id=product_id,
                source_record_id=source_record_id,
                brand=brand,
                model_std=model_std,
                sale_status=_get_cell(row, canonical_header_map, HEADERS[2]),
                is_functional=_is_functional(raw_copy),
                has_inspection_video=_has_media(video_path),
                has_sample_output=_has_media(image_path),
                cost_price=cost_price,
                sale_price=cost_price,
                profit_amount=0,
                source_name=_get_cell(row, canonical_header_map, HEADERS[3]),
                source_wxid=source_wxid,
                published_at=published_at,
                image_path=image_path,
                video_path=video_path,
                raw_copy=raw_copy,
                manual_review_needed=_is_true_value(
                    _get_cell(row, canonical_header_map, HEADERS[11])
                ),
            )
        )
    return _apply_pricing_recommendations(products)


def _build_canonical_header_map(header_map: dict[str, int]) -> dict[str, int]:
    canonical: dict[str, int] = {}
    for header_name in HEADERS:
        aliases = _HEADER_ALIASES.get(header_name, (header_name,))
        for alias in aliases:
            if alias in header_map:
                canonical[header_name] = header_map[alias]
                break
    return canonical


def _apply_pricing_recommendations(products: list[ProductRecord]) -> list[ProductRecord]:
    grouped_products: dict[tuple[str, str], list[ProductRecord]] = {}
    for product in products:
        grouped_products.setdefault((product.brand, product.model_std), []).append(product)

    priced_products: list[ProductRecord] = []
    for product in products:
        peer_cost_prices = [
            peer.cost_price
            for peer in grouped_products[(product.brand, product.model_std)]
            if peer.product_id != product.product_id
        ]
        recommendation = recommend_sale_price(product.cost_price, peer_cost_prices=peer_cost_prices)
        priced_products.append(
            replace(
                product,
                sale_price=recommendation.sale_price,
                profit_amount=recommendation.profit_amount,
            )
        )
    return priced_products


def _build_unique_product_id(
    seen_product_ids: dict[str, int],
    *,
    source_record_id: str,
    model: str,
    source_wxid: str,
    published_at: str,
) -> str:
    base_id = source_record_id.strip()
    if not base_id:
        base_id = "-".join(
            part
            for part in (source_wxid.strip(), model.strip(), published_at.strip())
            if part
        )
    if not base_id:
        base_id = "product"

    occurrence = seen_product_ids.get(base_id, 0) + 1
    seen_product_ids[base_id] = occurrence
    if occurrence == 1:
        return base_id
    return f"{base_id}-{occurrence}"


def _derive_brand_and_model(raw_model: str) -> tuple[str, str]:
    normalized = " ".join(raw_model.strip().split())
    lowered = normalized.lower()
    for brand, aliases in _KNOWN_BRANDS:
        for alias in aliases:
            alias_lower = alias.lower()
            if lowered.startswith(alias_lower):
                remainder = normalized[len(alias) :].strip(" -_")
                return brand, remainder or normalized
            if lowered == alias_lower:
                return brand, normalized
    return "", normalized


def _is_functional(raw_copy: str) -> bool:
    normalized = raw_copy.replace(" ", "")
    return any(keyword in normalized for keyword in _FUNCTIONAL_KEYWORDS)


def _has_media(path_text: str) -> bool:
    normalized = path_text.strip()
    return bool(normalized) and not any(flag in normalized for flag in _FAILED_MEDIA_TEXT)


def _is_true_value(value: str) -> bool:
    return value.strip() in {"是", "true", "True", "TRUE", "1", "Y", "y"}


def _parse_price(raw_value: str) -> int | None:
    digits = re.sub(r"[^\d]", "", raw_value)
    if not digits:
        return None
    return int(digits)


def _get_cell(row: list[object], header_map: dict[str, int], header_name: str) -> str:
    index = header_map.get(header_name)
    if index is None or index >= len(row):
        return ""
    value = row[index]
    if value is None:
        return ""
    return str(value).strip()


def _read_workbook_rows(workbook_source: bytes | str | Path | BytesIO) -> list[list[object]]:
    workbook_bytes = _read_source_bytes(workbook_source)
    if workbook_bytes.startswith(_OLE_SIGNATURE):
        return _read_xls_workbook_rows(workbook_bytes)
    return _read_xlsx_workbook_rows(workbook_bytes)


def _read_source_bytes(workbook_source: bytes | str | Path | BytesIO) -> bytes:
    if isinstance(workbook_source, bytes):
        return workbook_source
    if isinstance(workbook_source, BytesIO):
        return workbook_source.getvalue()
    return Path(workbook_source).read_bytes()


def _read_xlsx_workbook_rows(workbook_bytes: bytes) -> list[list[object]]:
    with zipfile.ZipFile(BytesIO(workbook_bytes)) as archive:
        shared_strings = _read_shared_strings(archive)
        sheet_path = _resolve_first_sheet_path(archive)
        sheet_xml = archive.read(sheet_path)

    root = ET.fromstring(sheet_xml)
    rows: list[list[object]] = []
    for row in root.findall(".//main:sheetData/main:row", _XML_NS):
        values: list[object] = []
        for cell in row.findall("main:c", _XML_NS):
            reference = cell.attrib.get("r", "")
            index = _column_index_from_reference(reference)
            while len(values) <= index:
                values.append("")
            values[index] = _read_xlsx_cell_value(cell, shared_strings)
        rows.append(values)
    return rows


def _read_xls_workbook_rows(workbook_bytes: bytes) -> list[list[object]]:
    workbook_stream = _read_ole_stream(workbook_bytes, ("Workbook", "Book"))
    first_sheet_offset = _resolve_first_xls_sheet_offset(workbook_stream)
    shared_strings = _read_xls_shared_strings(workbook_stream)
    return _read_xls_sheet_rows(workbook_stream, first_sheet_offset, shared_strings)


def _read_ole_stream(workbook_bytes: bytes, stream_names: tuple[str, ...]) -> bytes:
    sector_size = 1 << struct.unpack_from("<H", workbook_bytes, 30)[0]
    mini_sector_size = 1 << struct.unpack_from("<H", workbook_bytes, 32)[0]
    directory_sector = struct.unpack_from("<I", workbook_bytes, 48)[0]
    mini_stream_cutoff = struct.unpack_from("<I", workbook_bytes, 56)[0]
    first_minifat_sector = struct.unpack_from("<I", workbook_bytes, 60)[0]
    minifat_sector_count = struct.unpack_from("<I", workbook_bytes, 64)[0]
    difat_entries = _read_difat_entries(workbook_bytes, sector_size)
    fat = _build_fat(workbook_bytes, sector_size, difat_entries)

    directory_stream = _read_sector_chain(
        workbook_bytes,
        fat,
        sector_size=sector_size,
        start_sector=directory_sector,
    )
    directory_entries = _read_directory_entries(directory_stream)
    root_entry = next((entry for entry in directory_entries if entry.name == "Root Entry"), None)
    if root_entry is None:
        raise ValueError("Excel 文件缺少根目录流")

    target_entry = next((entry for entry in directory_entries if entry.name in stream_names), None)
    if target_entry is None:
        raise ValueError("Excel 文件缺少工作簿流")

    if target_entry.stream_size < mini_stream_cutoff:
        minifat_stream = _read_sector_chain(
            workbook_bytes,
            fat,
            sector_size=sector_size,
            start_sector=first_minifat_sector,
            stream_size=minifat_sector_count * sector_size,
        )
        mini_fat = list(struct.iter_unpack("<I", minifat_stream))
        mini_fat_entries = [item[0] for item in mini_fat]
        mini_stream = _read_sector_chain(
            workbook_bytes,
            fat,
            sector_size=sector_size,
            start_sector=root_entry.start_sector,
            stream_size=root_entry.stream_size,
        )
        return _read_mini_sector_chain(
            mini_stream,
            mini_fat_entries,
            mini_sector_size=mini_sector_size,
            start_sector=target_entry.start_sector,
            stream_size=target_entry.stream_size,
        )

    return _read_sector_chain(
        workbook_bytes,
        fat,
        sector_size=sector_size,
        start_sector=target_entry.start_sector,
        stream_size=target_entry.stream_size,
    )


def _read_difat_entries(workbook_bytes: bytes, sector_size: int) -> list[int]:
    difat_entries = [
        entry
        for entry in struct.unpack_from("<109I", workbook_bytes, 76)
        if entry != _OLE_FREE_SECTOR
    ]
    next_difat_sector = struct.unpack_from("<I", workbook_bytes, 68)[0]
    difat_sector_count = struct.unpack_from("<I", workbook_bytes, 72)[0]

    for _ in range(difat_sector_count):
        if next_difat_sector in {_OLE_END_OF_CHAIN, _OLE_FREE_SECTOR}:
            break
        sector = _read_sector(workbook_bytes, sector_size, next_difat_sector)
        entry_count = sector_size // 4 - 1
        difat_entries.extend(
            entry
            for entry in struct.unpack_from(f"<{entry_count}I", sector, 0)
            if entry != _OLE_FREE_SECTOR
        )
        next_difat_sector = struct.unpack_from("<I", sector, sector_size - 4)[0]
    return difat_entries


def _build_fat(workbook_bytes: bytes, sector_size: int, difat_entries: list[int]) -> list[int]:
    fat: list[int] = []
    for sector_index in difat_entries:
        sector = _read_sector(workbook_bytes, sector_size, sector_index)
        fat.extend(struct.unpack_from(f"<{sector_size // 4}I", sector, 0))
    return fat


def _read_sector(workbook_bytes: bytes, sector_size: int, sector_index: int) -> bytes:
    start = (sector_index + 1) * sector_size
    end = start + sector_size
    return workbook_bytes[start:end]


def _read_sector_chain(
    workbook_bytes: bytes,
    fat: list[int],
    *,
    sector_size: int,
    start_sector: int,
    stream_size: int | None = None,
) -> bytes:
    if start_sector in {_OLE_END_OF_CHAIN, _OLE_FREE_SECTOR}:
        return b""

    chunks: list[bytes] = []
    visited: set[int] = set()
    current_sector = start_sector
    while current_sector not in {_OLE_END_OF_CHAIN, _OLE_FREE_SECTOR}:
        if current_sector in visited or current_sector >= len(fat):
            raise ValueError("Excel 文件扇区链损坏")
        visited.add(current_sector)
        chunks.append(_read_sector(workbook_bytes, sector_size, current_sector))
        current_sector = fat[current_sector]

    data = b"".join(chunks)
    if stream_size is None:
        return data
    return data[:stream_size]


def _read_mini_sector_chain(
    mini_stream: bytes,
    mini_fat: list[int],
    *,
    mini_sector_size: int,
    start_sector: int,
    stream_size: int,
) -> bytes:
    if start_sector in {_OLE_END_OF_CHAIN, _OLE_FREE_SECTOR}:
        return b""

    chunks: list[bytes] = []
    visited: set[int] = set()
    current_sector = start_sector
    while current_sector not in {_OLE_END_OF_CHAIN, _OLE_FREE_SECTOR}:
        if current_sector in visited or current_sector >= len(mini_fat):
            raise ValueError("Excel 文件迷你扇区链损坏")
        visited.add(current_sector)
        start = current_sector * mini_sector_size
        end = start + mini_sector_size
        chunks.append(mini_stream[start:end])
        current_sector = mini_fat[current_sector]

    return b"".join(chunks)[:stream_size]


def _read_directory_entries(directory_stream: bytes) -> list[_OleDirectoryEntry]:
    entries: list[_OleDirectoryEntry] = []
    for offset in range(0, len(directory_stream), 128):
        record = directory_stream[offset : offset + 128]
        if len(record) < 128:
            continue
        name_length = struct.unpack_from("<H", record, 64)[0]
        if name_length < 2:
            continue
        name = record[: name_length - 2].decode("utf-16le")
        entries.append(
            _OleDirectoryEntry(
                name=name,
                object_type=record[66],
                start_sector=struct.unpack_from("<I", record, 116)[0],
                stream_size=struct.unpack_from("<Q", record, 120)[0],
            )
        )
    return entries


def _resolve_first_xls_sheet_offset(workbook_stream: bytes) -> int:
    for _, record_id, record_data in _iter_biff_records(workbook_stream):
        if record_id != _XLS_BOUNDSHEET:
            continue
        sheet_type = record_data[5]
        if sheet_type != _XLS_WORKSHEET_RECORD:
            continue
        return struct.unpack_from("<I", record_data, 0)[0]
    raise ValueError("Excel 中没有可读取的工作表")


def _read_xls_shared_strings(workbook_stream: bytes) -> list[str]:
    records = list(_iter_biff_records(workbook_stream))
    for index, (_, record_id, record_data) in enumerate(records):
        if record_id != _XLS_SST:
            continue
        buffer = bytearray(record_data)
        next_index = index + 1
        while next_index < len(records) and records[next_index][1] == _XLS_CONTINUE:
            buffer.extend(records[next_index][2])
            next_index += 1
        return _parse_xls_sst(bytes(buffer))
    return []


def _parse_xls_sst(record_data: bytes) -> list[str]:
    if len(record_data) < 8:
        return []

    _, unique_count = struct.unpack_from("<II", record_data, 0)
    strings: list[str] = []
    cursor = 8
    for _ in range(unique_count):
        if cursor + 3 > len(record_data):
            break
        char_count = struct.unpack_from("<H", record_data, cursor)[0]
        cursor += 2
        option_flags = record_data[cursor]
        cursor += 1
        is_wide = bool(option_flags & 0x01)
        has_asian_phonetic = bool(option_flags & 0x04)
        has_rich_text = bool(option_flags & 0x08)
        rich_text_run_count = struct.unpack_from("<H", record_data, cursor)[0] if has_rich_text else 0
        if has_rich_text:
            cursor += 2
        phonetic_size = struct.unpack_from("<I", record_data, cursor)[0] if has_asian_phonetic else 0
        if has_asian_phonetic:
            cursor += 4
        char_size = 2 if is_wide else 1
        text_byte_length = char_count * char_size
        text_bytes = record_data[cursor : cursor + text_byte_length]
        cursor += text_byte_length
        if is_wide:
            value = text_bytes.decode("utf-16le")
        else:
            value = text_bytes.decode("latin1")
        cursor += rich_text_run_count * 4
        cursor += phonetic_size
        strings.append(value)
    return strings


def _read_xls_sheet_rows(workbook_stream: bytes, sheet_offset: int, shared_strings: list[str]) -> list[list[object]]:
    rows: dict[int, dict[int, object]] = {}
    started = False

    for offset, record_id, record_data in _iter_biff_records(workbook_stream, start=sheet_offset):
        if offset == sheet_offset and record_id != _XLS_BOF:
            raise ValueError("Excel 工作表起始记录损坏")
        if record_id == _XLS_BOF:
            started = True
            continue
        if record_id == _XLS_EOF and started:
            break
        if record_id == _XLS_ROW:
            row_index = struct.unpack_from("<H", record_data, 0)[0]
            rows.setdefault(row_index, {})
            continue
        if record_id == _XLS_LABEL_SST:
            row_index, column_index, _, shared_string_index = struct.unpack_from("<HHHI", record_data, 0)
            rows.setdefault(row_index, {})[column_index] = (
                shared_strings[shared_string_index] if shared_string_index < len(shared_strings) else ""
            )
            continue
        if record_id == _XLS_LABEL:
            row_index, column_index = struct.unpack_from("<HH", record_data, 0)
            text_length = struct.unpack_from("<H", record_data, 6)[0]
            text = record_data[8 : 8 + text_length].decode("latin1")
            rows.setdefault(row_index, {})[column_index] = text
            continue
        if record_id == _XLS_NUMBER:
            row_index, column_index = struct.unpack_from("<HH", record_data, 0)
            value = struct.unpack_from("<d", record_data, 6)[0]
            rows.setdefault(row_index, {})[column_index] = _normalize_numeric_value(value)
            continue
        if record_id == _XLS_RK:
            row_index, column_index = struct.unpack_from("<HH", record_data, 0)
            rk_value = struct.unpack_from("<I", record_data, 6)[0]
            rows.setdefault(row_index, {})[column_index] = _decode_rk_value(rk_value)
            continue
        if record_id == _XLS_MULRK:
            row_index, first_column = struct.unpack_from("<HH", record_data, 0)
            last_column = struct.unpack_from("<H", record_data, len(record_data) - 2)[0]
            current_offset = 4
            for column_index in range(first_column, last_column + 1):
                rk_value = struct.unpack_from("<I", record_data, current_offset + 2)[0]
                rows.setdefault(row_index, {})[column_index] = _decode_rk_value(rk_value)
                current_offset += 6

    result: list[list[object]] = []
    for row_index in sorted(rows):
        columns = rows[row_index]
        if not columns:
            result.append([])
            continue
        max_column = max(columns)
        values = [""] * (max_column + 1)
        for column_index, value in columns.items():
            values[column_index] = value
        result.append(values)
    return result


def _iter_biff_records(workbook_stream: bytes, start: int = 0):
    offset = start
    while offset + 4 <= len(workbook_stream):
        record_id, record_length = struct.unpack_from("<HH", workbook_stream, offset)
        record_start = offset + 4
        record_end = record_start + record_length
        if record_end > len(workbook_stream):
            raise ValueError("Excel BIFF 记录超出文件边界")
        yield offset, record_id, workbook_stream[record_start:record_end]
        offset = record_end


def _decode_rk_value(raw_value: int) -> int | float:
    if raw_value & 0x02:
        signed_value = struct.unpack("<i", struct.pack("<I", raw_value & 0xFFFFFFFC))[0]
        value = signed_value >> 2
    else:
        number_bits = (raw_value & 0xFFFFFFFC) << 32
        value = struct.unpack("<d", struct.pack("<Q", number_bits))[0]
    if raw_value & 0x01:
        value = value / 100
    return _normalize_numeric_value(value)


def _normalize_numeric_value(value: float) -> int | float:
    if float(value).is_integer():
        return int(value)
    return value


def _column_index_from_reference(reference: str) -> int:
    letters = "".join(character for character in reference if character.isalpha()).upper()
    if not letters:
        return 0

    index = 0
    for letter in letters:
        index = index * 26 + (ord(letter) - 64)
    return index - 1


def _read_shared_strings(archive: zipfile.ZipFile) -> list[str]:
    if "xl/sharedStrings.xml" not in archive.namelist():
        return []
    root = ET.fromstring(archive.read("xl/sharedStrings.xml"))
    strings: list[str] = []
    for item in root.findall("main:si", _XML_NS):
        fragments = [node.text or "" for node in item.findall(".//main:t", _XML_NS)]
        strings.append("".join(fragments))
    return strings


def _resolve_first_sheet_path(archive: zipfile.ZipFile) -> str:
    workbook_root = ET.fromstring(archive.read("xl/workbook.xml"))
    rel_root = ET.fromstring(archive.read("xl/_rels/workbook.xml.rels"))
    first_sheet = workbook_root.find("main:sheets/main:sheet", _WORKBOOK_REL_NS)
    if first_sheet is None:
        raise ValueError("Excel 中没有可读取的工作表")

    relation_id = first_sheet.attrib.get(
        "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id"
    )
    if not relation_id:
        raise ValueError("Excel 工作表缺少关系 ID")

    for relation in rel_root.findall("rel:Relationship", _REL_NS):
        if relation.attrib.get("Id") == relation_id:
            target = relation.attrib.get("Target", "").lstrip("/")
            if target.startswith("xl/"):
                return target
            return f"xl/{target}"
    raise ValueError("Excel 工作表关系解析失败")


def _read_xlsx_cell_value(cell: ET.Element, shared_strings: list[str]) -> object:
    cell_type = cell.attrib.get("t")
    if cell_type == "inlineStr":
        text_node = cell.find("main:is/main:t", _XML_NS)
        return text_node.text if text_node is not None else ""
    if cell_type == "s":
        value_node = cell.find("main:v", _XML_NS)
        if value_node is None or value_node.text is None:
            return ""
        return shared_strings[int(value_node.text)]

    value_node = cell.find("main:v", _XML_NS)
    if value_node is None or value_node.text is None:
        return ""

    raw = value_node.text.strip()
    if raw.isdigit():
        return int(raw)
    return raw
