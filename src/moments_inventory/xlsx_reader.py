"""通用 XLSX 读取，不依赖 AI 工作台业务模块。"""
from io import BytesIO
from xml.etree import ElementTree as ET
import zipfile

_XML_NS = {"main": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
_REL_NS = {"rel": "http://schemas.openxmlformats.org/package/2006/relationships"}
_WORKBOOK_REL_NS = {**_XML_NS, "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships"}


def read_xlsx_rows_from_bytes(data: bytes) -> list[list[object]]:
    return _read_xlsx_workbook_rows(data)


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
