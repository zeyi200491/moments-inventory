from datetime import datetime
from pathlib import Path
import shutil
import tempfile
import uuid
from xml.etree import ElementTree as ET
import zipfile

import moments_inventory.exporter as exporter
from moments_inventory.exporter import export_records
from moments_inventory.models import InventoryRecord


PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _make_temp_root(prefix: str) -> Path:
    return Path(tempfile.mkdtemp(prefix=prefix))


def _read_sheet_rows(workbook_path: Path) -> list[tuple]:
    namespace = {"main": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
    with zipfile.ZipFile(workbook_path) as archive:
        sheet_xml = archive.read("xl/worksheets/sheet1.xml")

    root = ET.fromstring(sheet_xml)
    rows: list[tuple] = []
    for row in root.findall(".//main:sheetData/main:row", namespace):
        values: list[str | int | None] = []
        for cell in row.findall("main:c", namespace):
            cell_type = cell.attrib.get("t")
            if cell_type == "inlineStr":
                text_node = cell.find("main:is/main:t", namespace)
                values.append(text_node.text if text_node is not None else "")
                continue
            value_node = cell.find("main:v", namespace)
            if value_node is None:
                values.append(None)
            else:
                raw = value_node.text or ""
                values.append(int(raw) if raw.isdigit() else raw)
        rows.append(tuple(values))
    return rows


def test_export_records_creates_only_current_workbook():
    temp_root = _make_temp_root(f"pytest-export-{uuid.uuid4().hex}-")

    try:
        records = [
            InventoryRecord(
                record_key="record-1",
                remark_name="user-a",
                wxid="wxid_123",
                published_at=datetime.fromisoformat("2026-04-20T10:00:00+08:00"),
                model="ixus 95",
                price=850,
                serial_no="A12",
                status="未售出",
                image_urls=[],
                video_urls=[],
                content_text="ixus 95 850 A12",
                note="",
                needs_manual=False,
                source_moment_ids=["sns_001"],
            )
        ]

        current_path = export_records(records, temp_root)

        current_rows = _read_sheet_rows(current_path)

        assert current_rows[1][2] == "未售出"
        assert current_rows[1][0] == "ixus 95"
        assert current_path.name == "当前在售库.xlsx"
        assert not (temp_root / "历史总库.xlsx").exists()
    finally:
        shutil.rmtree(temp_root, ignore_errors=True)


def test_export_records_treats_unsold_status_as_current():
    temp_root = _make_temp_root(f"pytest-export-status-{uuid.uuid4().hex}-")

    try:
        records = [
            InventoryRecord(
                record_key="record-2",
                remark_name="user-a",
                wxid="wxid_123",
                published_at=datetime.fromisoformat("2026-04-20T10:00:00+08:00"),
                model="ixus 80",
                price=680,
                serial_no="B18",
                status="未售出",
                image_urls=[],
                video_urls=[],
                content_text="ixus 80 680 B18",
                note="",
                needs_manual=False,
                source_moment_ids=["sns_002"],
            )
        ]

        current_path = export_records(records, temp_root)
        current_rows = _read_sheet_rows(current_path)

        assert current_rows[1][0] == "ixus 80"
    finally:
        shutil.rmtree(temp_root, ignore_errors=True)


def test_export_records_only_includes_current_status_records_in_workbook():
    temp_root = _make_temp_root(f"pytest-export-mixed-status-{uuid.uuid4().hex}-")

    try:
        current_status = next(iter(exporter.CURRENT_STATUSES))
        records = [
            InventoryRecord(
                record_key="record-current",
                remark_name="user-a",
                wxid="wxid_123",
                published_at=datetime.fromisoformat("2026-04-20T10:00:00+08:00"),
                model="ixus current",
                price=850,
                serial_no="A12",
                status=current_status,
                image_urls=[],
                video_urls=[],
                content_text="ixus current 850 A12",
                note="",
                needs_manual=False,
                source_moment_ids=["sns_001"],
            ),
            InventoryRecord(
                record_key="record-sold",
                remark_name="user-b",
                wxid="wxid_456",
                published_at=datetime.fromisoformat("2026-04-21T10:00:00+08:00"),
                model="ixus sold",
                price=680,
                serial_no="B18",
                status="已售出",
                image_urls=[],
                video_urls=[],
                content_text="ixus sold 680 B18",
                note="",
                needs_manual=False,
                source_moment_ids=["sns_002"],
            ),
        ]

        current_path = export_records(records, temp_root)
        current_rows = _read_sheet_rows(current_path)

        assert len(current_rows) == 2
        assert current_rows[1][0] == "ixus current"
        assert current_rows[1][2] == current_status
        assert all("ixus sold" not in row for row in current_rows[1:])
    finally:
        shutil.rmtree(temp_root, ignore_errors=True)


def test_export_records_exports_media_files_and_writes_local_paths():
    temp_root = _make_temp_root(f"pytest-export-media-{uuid.uuid4().hex}-")

    responses = {
        "http://127.0.0.1:5031/api/v1/sns/media/proxy?url=https%3A%2F%2Fexample.com%2Fa.jpg&key=1&access_token=secret-token": (b"image-a", "image/jpeg"),
        "https://example.com/b.png": (b"image-b", "image/png"),
        "https://example.com/v.mp4": (b"fake-video", "video/mp4"),
    }

    class FakeResponse:
        def __init__(self, payload: bytes, content_type: str):
            self._payload = payload
            self.headers = {"Content-Type": content_type}

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self):
            return self._payload

    def fake_urlopen(request, timeout):
        payload, content_type = responses[request.full_url]
        return FakeResponse(payload, content_type)

    original_urlopen = exporter.urlopen
    exporter.urlopen = fake_urlopen
    try:
        records = [
            InventoryRecord(
                record_key="record-1",
                remark_name="user-a",
                wxid="wxid_123",
                published_at=datetime.fromisoformat("2026-04-20T10:00:00+08:00"),
                model="ixus 95",
                price=850,
                serial_no="A12",
                status="未售出",
                image_urls=[
                    "http://127.0.0.1:5031/api/v1/sns/media/proxy?url=https%3A%2F%2Fexample.com%2Fa.jpg&key=1",
                    "https://example.com/b.png",
                ],
                video_urls=["https://example.com/v.mp4"],
                content_text="ixus 95 850 A12",
                note="",
                needs_manual=False,
                source_moment_ids=["sns_001"],
            )
        ]

        current_path = exporter.export_records(
            records,
            temp_root,
            base_url="http://127.0.0.1:5031",
            access_token="secret-token",
        )

        rows = _read_sheet_rows(current_path)
        assert rows[1][7] == "media/record-1/image-1.jpg\nmedia/record-1/image-2.png"
        assert rows[1][8] == "media/record-1/video-1.mp4"
        assert not (temp_root / "历史总库.xlsx").exists()
        assert (temp_root / "media" / "record-1" / "image-1.jpg").read_bytes() == b"image-a"
        assert (temp_root / "media" / "record-1" / "image-2.png").read_bytes() == b"image-b"
        assert (temp_root / "media" / "record-1" / "video-1.mp4").read_bytes() == b"fake-video"

        with zipfile.ZipFile(current_path) as archive:
            assert "xl/worksheets/_rels/sheet1.xml.rels" not in archive.namelist()
            assert "xl/drawings/drawing1.xml" not in archive.namelist()
            assert "xl/media/image1.png" not in archive.namelist()
    finally:
        exporter.urlopen = original_urlopen
        shutil.rmtree(temp_root, ignore_errors=True)


def test_export_records_uses_fixed_failure_text_when_media_download_fails():
    temp_root = _make_temp_root(f"pytest-export-failed-media-{uuid.uuid4().hex}-")

    def fake_urlopen(request, timeout):
        raise RuntimeError("download failed")

    original_urlopen = exporter.urlopen
    exporter.urlopen = fake_urlopen
    try:
        records = [
            InventoryRecord(
                record_key="record-failed",
                remark_name="user-a",
                wxid="wxid_123",
                published_at=datetime.fromisoformat("2026-04-20T10:00:00+08:00"),
                model="ixus 95",
                price=850,
                serial_no="A12",
                status="未售出",
                image_urls=["https://example.com/a.jpg"],
                video_urls=["https://example.com/v.mp4"],
                content_text="ixus 95 850 A12",
                note="",
                needs_manual=False,
                source_moment_ids=["sns_001"],
            )
        ]

        current_path = export_records(records, temp_root)
        rows = _read_sheet_rows(current_path)

        assert rows[1][7] == "图片未成功下载"
        assert rows[1][8] == "视频未成功下载"
    finally:
        exporter.urlopen = original_urlopen
        shutil.rmtree(temp_root, ignore_errors=True)


def test_export_records_filters_xml_control_characters():
    temp_root = _make_temp_root(f"pytest-export-xml-{uuid.uuid4().hex}-")

    try:
        records = [
            InventoryRecord(
                record_key="record-xml",
                remark_name="user-a",
                wxid="wxid_123",
                published_at=datetime.fromisoformat("2026-04-20T10:00:00+08:00"),
                model="ixus 95",
                price=850,
                serial_no="A12",
                status=next(iter(exporter.CURRENT_STATUSES)),
                image_urls=[],
                video_urls=[],
                content_text="hello\x01world",
                note="bad\x02note",
                needs_manual=False,
                source_moment_ids=["sns_001"],
            )
        ]

        current_path = export_records(records, temp_root)
        rows = _read_sheet_rows(current_path)

        assert rows[1][9] == "helloworld"
        assert rows[1][10] == "badnote"
    finally:
        shutil.rmtree(temp_root, ignore_errors=True)
