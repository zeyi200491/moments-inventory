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


def _current_status() -> str:
    return next(iter(exporter.CURRENT_STATUSES))


def _build_export_record(
    record_key: str,
    *,
    remark_name: str | None = "user-a",
    wxid: str | None = "wxid_123",
    model: str | None = "IXUS 100",
    price: int | None = 880,
    serial_no: str | None = "A12",
    status: str | None = None,
    content_text: str | None = None,
    lifecycle_status: str = "current",
    risk_flags: list[str] | None = None,
    product_key: str | None = None,
    price_history: list[str] | None = None,
    image_urls: list[str] | None = None,
    video_urls: list[str] | None = None,
    needs_manual: bool = False,
) -> InventoryRecord:
    return InventoryRecord(
        record_key=record_key,
        remark_name=remark_name,
        wxid=wxid,
        published_at=datetime.fromisoformat("2026-04-20T10:00:00+08:00"),
        model=model,
        price=price,
        serial_no=serial_no,
        status=status or _current_status(),
        image_urls=image_urls or [],
        video_urls=video_urls or [],
        content_text=content_text if content_text is not None else f"{model or 'unknown'} {price}💰 A12",
        note="",
        needs_manual=needs_manual,
        source_moment_ids=[f"sns_{record_key}"],
        product_key=product_key or f"product-{record_key}",
        lifecycle_status=lifecycle_status,
        risk_flags=risk_flags or [],
        price_history=price_history or [],
    )


def test_export_records_creates_only_current_workbook() -> None:
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
                status=_current_status(),
                image_urls=[],
                video_urls=[],
                content_text="ixus 95 850💰 A12",
                note="",
                needs_manual=False,
                source_moment_ids=["sns_001"],
            )
        ]

        current_path = export_records(records, temp_root)
        current_rows = _read_sheet_rows(current_path)

        assert current_rows[1][2] == _current_status()
        assert current_rows[1][0] == "ixus 95"
        assert current_path.name == exporter.DEFAULT_WORKBOOK_FILENAME
        assert current_rows[0] == tuple(exporter.HEADERS)
    finally:
        shutil.rmtree(temp_root, ignore_errors=True)


def test_export_records_treats_unsold_status_as_current() -> None:
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
                status=_current_status(),
                image_urls=[],
                video_urls=[],
                content_text="ixus 80 680💰 B18",
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


def test_export_records_treats_real_unsold_status_as_current() -> None:
    temp_root = _make_temp_root(f"pytest-export-real-unsold-{uuid.uuid4().hex}-")

    try:
        records = [
            InventoryRecord(
                record_key="record-real-unsold",
                remark_name="user-a",
                wxid="wxid_123",
                published_at=datetime.fromisoformat("2026-04-20T10:00:00+08:00"),
                model="ixus real unsold",
                price=699,
                serial_no="C08",
                status="未售出",
                image_urls=[],
                video_urls=[],
                content_text="ixus real unsold 699💰 C08",
                note="",
                needs_manual=False,
                source_moment_ids=["sns_003"],
            )
        ]

        current_path = export_records(records, temp_root)
        current_rows = _read_sheet_rows(current_path)

        assert len(current_rows) == 2
        assert current_rows[1][0] == "ixus real unsold"
        assert current_rows[1][2] == "未售出"
    finally:
        shutil.rmtree(temp_root, ignore_errors=True)


def test_export_records_only_includes_current_status_records_in_workbook() -> None:
    temp_root = _make_temp_root(f"pytest-export-mixed-status-{uuid.uuid4().hex}-")

    try:
        records = [
            InventoryRecord(
                record_key="record-current",
                remark_name="user-a",
                wxid="wxid_123",
                published_at=datetime.fromisoformat("2026-04-20T10:00:00+08:00"),
                model="ixus current",
                price=850,
                serial_no="A12",
                status=_current_status(),
                image_urls=[],
                video_urls=[],
                content_text="ixus current 850💰 A12",
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
                status="宸插敭鍑?",
                image_urls=[],
                video_urls=[],
                content_text="ixus sold 680💰 B18",
                note="",
                needs_manual=False,
                source_moment_ids=["sns_002"],
            ),
        ]

        current_path = export_records(records, temp_root)
        current_rows = _read_sheet_rows(current_path)

        assert len(current_rows) == 2
        assert current_rows[1][0] == "ixus current"
        assert current_rows[1][2] == _current_status()
        assert all("ixus sold" not in row for row in current_rows[1:])
    finally:
        shutil.rmtree(temp_root, ignore_errors=True)


def test_export_records_exports_media_files_and_writes_local_paths() -> None:
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
                status=_current_status(),
                image_urls=[
                    "http://127.0.0.1:5031/api/v1/sns/media/proxy?url=https%3A%2F%2Fexample.com%2Fa.jpg&key=1",
                    "https://example.com/b.png",
                ],
                video_urls=["https://example.com/v.mp4"],
                content_text="ixus 95 850💰 A12",
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


def test_export_records_uses_fixed_failure_text_when_media_download_fails() -> None:
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
                status=_current_status(),
                image_urls=["https://example.com/a.jpg"],
                video_urls=["https://example.com/v.mp4"],
                content_text="ixus 95 850💰 A12",
                note="",
                needs_manual=False,
                source_moment_ids=["sns_001"],
            )
        ]

        current_path = export_records(records, temp_root)
        rows = _read_sheet_rows(current_path)

        assert rows[1][7] == exporter.IMAGE_FAILURE_TEXT
        assert rows[1][8] == exporter.VIDEO_FAILURE_TEXT
    finally:
        exporter.urlopen = original_urlopen
        shutil.rmtree(temp_root, ignore_errors=True)


def test_export_records_skips_media_download_when_disabled() -> None:
    temp_root = _make_temp_root(f"pytest-export-no-media-{uuid.uuid4().hex}-")

    def fake_urlopen(request, timeout):
        raise AssertionError("urlopen should not be called when download_media is false")

    original_urlopen = exporter.urlopen
    exporter.urlopen = fake_urlopen
    try:
        records = [
            InventoryRecord(
                record_key="record-no-media",
                remark_name="user-a",
                wxid="wxid_123",
                published_at=datetime.fromisoformat("2026-04-20T10:00:00+08:00"),
                model="ixus 95",
                price=850,
                serial_no="A12",
                status=_current_status(),
                image_urls=["https://example.com/a.jpg"],
                video_urls=["https://example.com/v.mp4"],
                content_text="ixus 95 850💰 A12",
                note="",
                needs_manual=False,
                source_moment_ids=["sns_001"],
            )
        ]

        current_path = export_records(records, temp_root, download_media=False)
        rows = _read_sheet_rows(current_path)

        assert rows[1][7] in ("", None)
        assert rows[1][8] in ("", None)
        assert not any((temp_root / "media").rglob("*.*"))
    finally:
        exporter.urlopen = original_urlopen
        shutil.rmtree(temp_root, ignore_errors=True)


def test_export_records_downloads_media_only_for_workbook_records_once() -> None:
    temp_root = _make_temp_root(f"pytest-export-media-scope-{uuid.uuid4().hex}-")
    downloaded_urls: list[str] = []

    def fake_download_media(url, base_url, access_token):
        downloaded_urls.append(url)
        return f"payload-{url}".encode(), "image/jpeg"

    original_download_media = exporter._download_media
    exporter._download_media = fake_download_media
    try:
        current_record = _build_export_record(
            "current-media",
            model="IXUS current media",
            image_urls=["https://example.com/current.jpg"],
        )
        review_record = _build_export_record(
            "review-media",
            model="IXUS review media",
            lifecycle_status="review",
            image_urls=["https://example.com/review.jpg"],
        )
        price_drop_record = _build_export_record(
            "price-drop-media",
            model="IXUS price drop media",
            risk_flags=["price_drop_repost"],
            image_urls=["https://example.com/price-drop.jpg"],
        )
        low_price_record = _build_export_record(
            "low-price-media",
            model="IXUS low price media",
            price=35,
            image_urls=["https://example.com/low-price.jpg"],
        )
        missing_model_record = _build_export_record(
            "missing-model-media",
            model=None,
            image_urls=["https://example.com/missing-model.jpg"],
        )
        non_formal_record = _build_export_record(
            "non-formal-media",
            model="IXUS non formal media",
            content_text="IXUS non formal media 880 A12",
            image_urls=["https://example.com/non-formal.jpg"],
        )

        export_records(
            [
                current_record,
                review_record,
                price_drop_record,
                low_price_record,
                missing_model_record,
                non_formal_record,
            ],
            temp_root,
        )

        assert set(downloaded_urls) == {
            "https://example.com/current.jpg",
            "https://example.com/review.jpg",
            "https://example.com/price-drop.jpg",
            "https://example.com/low-price.jpg",
        }
        assert len(downloaded_urls) == 4
        assert downloaded_urls.count("https://example.com/price-drop.jpg") == 1
        assert "https://example.com/missing-model.jpg" not in downloaded_urls
        assert "https://example.com/non-formal.jpg" not in downloaded_urls
    finally:
        exporter._download_media = original_download_media
        shutil.rmtree(temp_root, ignore_errors=True)


def test_export_records_filters_xml_control_characters() -> None:
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
                status=_current_status(),
                image_urls=[],
                video_urls=[],
                content_text="hello\x01world 850💰",
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


def test_export_records_excludes_records_without_money_symbol() -> None:
    temp_root = _make_temp_root(f"pytest-export-no-money-symbol-{uuid.uuid4().hex}-")

    try:
        records = [
            InventoryRecord(
                record_key="record-no-money-symbol",
                remark_name="user-a",
                wxid="wxid_123",
                published_at=datetime.fromisoformat("2026-04-20T10:00:00+08:00"),
                model="ixus no money symbol",
                price=850,
                serial_no="A12",
                status=_current_status(),
                image_urls=[],
                video_urls=[],
                content_text="ixus no money symbol 850 A12",
                note="",
                needs_manual=False,
                source_moment_ids=["sns_010"],
            )
        ]

        current_path = export_records(records, temp_root)
        current_rows = _read_sheet_rows(current_path)

        assert current_rows == [tuple(exporter.HEADERS)]
    finally:
        shutil.rmtree(temp_root, ignore_errors=True)


def test_export_records_includes_prices_below_99() -> None:
    temp_root = _make_temp_root(f"pytest-export-low-price-{uuid.uuid4().hex}-")

    try:
        records = [
            InventoryRecord(
                record_key="record-low-price",
                remark_name="user-a",
                wxid="wxid_123",
                published_at=datetime.fromisoformat("2026-04-20T10:00:00+08:00"),
                model="ixus low price",
                price=35,
                serial_no="A12",
                status=_current_status(),
                image_urls=[],
                video_urls=[],
                content_text="ixus low price 35💰 A12",
                note="",
                needs_manual=False,
                source_moment_ids=["sns_011"],
            )
        ]

        current_path = export_records(records, temp_root)
        current_rows = _read_sheet_rows(current_path)

        assert current_rows[1][0] == "ixus low price"
        assert current_rows[1][1] == 35
    finally:
        shutil.rmtree(temp_root, ignore_errors=True)


def test_export_records_allows_no_money_symbol_for_configured_source() -> None:
    temp_root = _make_temp_root(f"pytest-export-no-money-allowed-{uuid.uuid4().hex}-")

    try:
        records = [
            _build_export_record(
                "allowed-remark",
                remark_name="童百万库存湖北武汉圆通货源",
                content_text="ixus allowed remark 850 A12",
            ),
            _build_export_record(
                "allowed-wxid",
                wxid="wxid_d500glk2ukjn12",
                content_text="ixus allowed wxid 860 A13",
            ),
        ]

        current_path = export_records(records, temp_root, download_media=False)
        current_rows = _read_sheet_rows(current_path)

        assert [row[0] for row in current_rows[1:]] == [
            "IXUS 100",
            "IXUS 100",
        ]
    finally:
        shutil.rmtree(temp_root, ignore_errors=True)


def test_export_records_redacts_price_from_content_text() -> None:
    temp_root = _make_temp_root(f"pytest-export-redact-price-{uuid.uuid4().hex}-")

    try:
        records = [
            _build_export_record(
                "redact-price",
                content_text="980💰佳能ixus100 香槟色\n成色不错 1210万像素，RMB880备用价",
            )
        ]

        current_path = export_records(records, temp_root, download_media=False)
        current_rows = _read_sheet_rows(current_path)
        content_text = current_rows[1][9]

        assert "980" not in content_text
        assert "💰" not in content_text
        assert "RMB880" not in content_text
        assert "佳能ixus100" in content_text
        assert "1210万像素" in content_text
    finally:
        shutil.rmtree(temp_root, ignore_errors=True)


def test_export_records_excludes_sold_and_delisted_lifecycle_records_from_current() -> None:
    temp_root = _make_temp_root(f"pytest-export-lifecycle-{uuid.uuid4().hex}-")

    try:
        records = [
            _build_export_record("current-life", model="IXUS current"),
            _build_export_record(
                "sold-life",
                model="IXUS sold",
                lifecycle_status="sold",
                risk_flags=["sold_keyword"],
            ),
            _build_export_record(
                "delisted-life",
                model="IXUS delisted",
                lifecycle_status="delisted",
                risk_flags=["deleted_missing"],
            ),
        ]

        current_path = export_records(records, temp_root, download_media=False)
        current_rows = _read_sheet_rows(current_path)

        assert len(current_rows) == 2
        assert current_rows[1][0] == "IXUS current"
        assert all("IXUS sold" not in row for row in current_rows[1:])
        assert all("IXUS delisted" not in row for row in current_rows[1:])
    finally:
        shutil.rmtree(temp_root, ignore_errors=True)


def test_export_records_writes_review_workbook_for_review_lifecycle_and_risky_records() -> None:
    temp_root = _make_temp_root(f"pytest-export-review-{uuid.uuid4().hex}-")

    try:
        review_record = _build_export_record(
            "review-life",
            model="IXUS review",
            lifecycle_status="review",
            risk_flags=["ambiguous_model", "reference_model"],
            price_history=["2026-04-19: 980", "2026-04-20: 880"],
        )
        risky_record = _build_export_record(
            "risky-current",
            model="IXUS risky",
            risk_flags=["model_conflict"],
        )

        export_records([review_record, risky_record], temp_root, download_media=False)
        review_rows = _read_sheet_rows(temp_root / "review_needed.xlsx")
        header = review_rows[0]
        risk_flags_index = header.index("risk_flags")
        lifecycle_index = header.index("lifecycle_status")
        price_history_index = header.index("price_history")

        assert len(review_rows) == 3
        assert review_rows[1][0] == "IXUS review"
        assert review_rows[1][lifecycle_index] == "review"
        assert "ambiguous_model" in review_rows[1][risk_flags_index]
        assert "reference_model" in review_rows[1][risk_flags_index]
        assert "2026-04-19: 980" in review_rows[1][price_history_index]
        assert review_rows[2][0] == "IXUS risky"
        assert "model_conflict" in review_rows[2][risk_flags_index]
    finally:
        shutil.rmtree(temp_root, ignore_errors=True)


def test_export_records_current_workbook_only_contains_formal_current_inventory() -> None:
    temp_root = _make_temp_root(f"pytest-export-formal-current-{uuid.uuid4().hex}-")

    try:
        records = [
            _build_export_record("valid-current", model="IXUS valid", price=880),
            _build_export_record("review-life", model="IXUS review", lifecycle_status="review"),
            _build_export_record("wrong-status", model="IXUS wrong status", status="已售出"),
            _build_export_record("missing-model", model=None),
            _build_export_record("missing-price", model="IXUS missing price", price=None),
            _build_export_record("low-price", model="IXUS low price", price=98),
            _build_export_record(
                "missing-money",
                model="IXUS missing money",
                content_text="IXUS missing money 880 A12",
            ),
            _build_export_record(
                "allowed-missing-money",
                remark_name="童百万库存湖北武汉圆通货源",
                model="IXUS allowed missing money",
                content_text="IXUS allowed missing money 880 A12",
            ),
            _build_export_record(
                "missing-serial",
                model="IXUS missing serial",
                serial_no=None,
                needs_manual=True,
            ),
            _build_export_record(
                "low-confidence",
                model="IXUS low confidence",
                risk_flags=["low_model_confidence"],
            ),
            _build_export_record(
                "unmatched-model",
                model=None,
                risk_flags=["unmatched_model"],
            ),
            _build_export_record(
                "sold-keyword",
                model="IXUS sold keyword",
                risk_flags=["sold_keyword"],
            ),
            _build_export_record(
                "deleted-missing",
                model="IXUS deleted missing",
                risk_flags=["deleted_missing"],
            ),
            _build_export_record(
                "model-conflict",
                model="IXUS model conflict",
                risk_flags=["model_conflict"],
            ),
            _build_export_record(
                "price-conflict",
                model="IXUS price conflict",
                risk_flags=["price_conflict"],
            ),
            _build_export_record(
                "price-drop",
                model="IXUS price drop",
                risk_flags=["price_drop_repost"],
                price_history=["2026-04-19: 980", "2026-04-20: 880"],
            ),
        ]

        current_path = export_records(records, temp_root, download_media=False)
        current_rows = _read_sheet_rows(current_path)
        exported_models = [row[0] for row in current_rows[1:]]

        assert exported_models == [
            "IXUS valid",
            "IXUS low price",
            "IXUS allowed missing money",
            "IXUS missing serial",
            "IXUS price drop",
        ]
    finally:
        shutil.rmtree(temp_root, ignore_errors=True)


def test_summarize_export_records_uses_current_and_review_workbook_rules() -> None:
    from moments_inventory.exporter import summarize_export_records

    records = [
        _build_export_record("valid-current", model="IXUS valid", price=880),
        _build_export_record("review-life", model="IXUS review", lifecycle_status="review"),
        _build_export_record("wrong-status", model="IXUS wrong status", status="已售出"),
        _build_export_record("missing-model", model=None),
        _build_export_record("missing-price", model="IXUS missing price", price=None),
        _build_export_record("low-price", model="IXUS low price", price=98),
        _build_export_record(
            "missing-money",
            model="IXUS missing money",
            content_text="IXUS missing money 880 A12",
        ),
        _build_export_record("sold-keyword", model="IXUS sold keyword", risk_flags=["sold_keyword"]),
        _build_export_record("unmatched", model=None, risk_flags=["unmatched_model"]),
        _build_export_record(
            "low-confidence",
            model="IXUS low confidence",
            risk_flags=["low_model_confidence"],
        ),
        _build_export_record("reference", model="IXUS reference", risk_flags=["reference_model"]),
        _build_export_record(
            "deleted-missing",
            model="IXUS deleted missing",
            risk_flags=["deleted_missing"],
        ),
        _build_export_record("model-conflict", model="IXUS model conflict", risk_flags=["model_conflict"]),
        _build_export_record("price-conflict", model="IXUS price conflict", risk_flags=["price_conflict"]),
        _build_export_record(
            "price-drop",
            model="IXUS price drop",
            risk_flags=["price_drop_repost"],
            price_history=["2026-04-19: 980", "2026-04-20: 880"],
        ),
        _build_export_record("sold-life", model="IXUS sold", lifecycle_status="sold"),
        _build_export_record("delisted-life", model="IXUS delisted", lifecycle_status="delisted"),
    ]

    summary = summarize_export_records(records)

    assert summary.candidate_count == 17
    assert summary.current_count == 4
    assert summary.review_count == 11
    assert summary.price_drop_repost_count == 1
    assert summary.sold_or_delisted_count == 4
    assert summary.unmatched_model_count == 2
    assert summary.low_confidence_model_count == 1
    assert summary.reference_model_count == 1
    assert summary.model_conflict_count == 1


def test_export_records_writes_review_headers_with_audit_columns() -> None:
    temp_root = _make_temp_root(f"pytest-export-review-header-{uuid.uuid4().hex}-")

    try:
        record = _build_export_record(
            "review-header",
            model="IXUS review header",
            lifecycle_status="review",
            risk_flags=["ambiguous_model"],
            product_key="ixus-review-header",
            price_history=["2026-04-20: 880"],
        )

        export_records([record], temp_root, download_media=False)
        review_rows = _read_sheet_rows(temp_root / "review_needed.xlsx")
        header = review_rows[0]

        assert header[: len(exporter.HEADERS)] == tuple(exporter.HEADERS)
        assert "product_key" in header
        assert "risk_flags" in header
        assert "lifecycle_status" in header
        assert "price_history" in header
        assert review_rows[1][header.index("product_key")] == "ixus-review-header"
        assert review_rows[1][header.index("lifecycle_status")] == "review"
        assert review_rows[1][header.index("risk_flags")] == "ambiguous_model"
        assert review_rows[1][header.index("price_history")] == "2026-04-20: 880"
    finally:
        shutil.rmtree(temp_root, ignore_errors=True)
