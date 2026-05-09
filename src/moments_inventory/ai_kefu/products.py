from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from xml.etree import ElementTree as ET
import re
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


def import_products_from_xlsx(xlsx_path: str | Path) -> list[ProductRecord]:
    rows = _read_workbook_rows(xlsx_path)
    if not rows:
        return []

    header = [str(value or "").strip() for value in rows[0]]
    header_map = {name: index for index, name in enumerate(header)}
    products: list[ProductRecord] = []
    seen_product_ids: dict[str, int] = {}
    for row in rows[1:]:
        model = _get_cell(row, header_map, HEADERS[0])
        if not model:
            continue

        cost_price = _parse_price(_get_cell(row, header_map, HEADERS[1]))
        if cost_price is None:
            continue

        image_path = _get_cell(row, header_map, HEADERS[7])
        video_path = _get_cell(row, header_map, HEADERS[8])
        raw_copy = _get_cell(row, header_map, HEADERS[9])
        source_wxid = _get_cell(row, header_map, HEADERS[4])
        published_at = _get_cell(row, header_map, HEADERS[5])
        source_record_id = _get_cell(row, header_map, HEADERS[6]) or model
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
                sale_status=_get_cell(row, header_map, HEADERS[2]),
                is_functional=_is_functional(raw_copy),
                has_inspection_video=_has_media(video_path),
                has_sample_output=_has_media(image_path),
                cost_price=cost_price,
                sale_price=cost_price,
                profit_amount=0,
                source_name=_get_cell(row, header_map, HEADERS[3]),
                source_wxid=source_wxid,
                published_at=published_at,
                image_path=image_path,
                video_path=video_path,
                raw_copy=raw_copy,
                manual_review_needed=_is_true_value(_get_cell(row, header_map, HEADERS[11])),
            )
        )

    return _apply_pricing_recommendations(products)


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


def _read_workbook_rows(xlsx_path: str | Path) -> list[list[object]]:
    with zipfile.ZipFile(xlsx_path) as archive:
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
            values[index] = _read_cell_value(cell, shared_strings)
        rows.append(values)
    return rows


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
        raise ValueError("xlsx 中没有可读取的工作表")

    relation_id = first_sheet.attrib.get(
        "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id"
    )
    if not relation_id:
        raise ValueError("xlsx 工作表缺少关系 ID")

    for relation in rel_root.findall("rel:Relationship", _REL_NS):
        if relation.attrib.get("Id") == relation_id:
            target = relation.attrib.get("Target", "").lstrip("/")
            if target.startswith("xl/"):
                return target
            return f"xl/{target}"
    raise ValueError("xlsx 工作表关系解析失败")


def _read_cell_value(cell: ET.Element, shared_strings: list[str]) -> object:
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
