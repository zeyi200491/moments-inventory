import json
from datetime import datetime, timedelta
from pathlib import Path
import shutil
import tempfile
from urllib.error import HTTPError, URLError

import pytest

import moments_inventory.weflow_client as weflow_module
from moments_inventory.cli import build_parser
from moments_inventory.config import load_settings
from moments_inventory.models import RawMoment
from moments_inventory.service import SyncService
from moments_inventory.weflow_client import WeFlowClient, WeFlowRequestError, parse_timeline_response


PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _make_temp_root(prefix: str) -> Path:
    return Path(tempfile.mkdtemp(prefix=prefix))


def test_parse_timeline_response_maps_raw_moments():
    fixture_path = PROJECT_ROOT / "tests" / "fixtures" / "weflow_timeline.json"
    payload = json.loads(fixture_path.read_text(encoding="utf-8"))

    moments = parse_timeline_response(payload)

    assert len(moments) == 2
    assert moments[0].moment_id == "sns_001"
    assert moments[0].author_remark_name
    assert moments[0].video_urls == []
    assert moments[1].video_urls == ["https://example.com/video.mp4"]
    assert isinstance(moments[0].published_at, datetime)


def test_parse_timeline_response_supports_real_weflow_shape():
    payload = {
        "success": True,
        "count": 1,
        "timeline": [
            {
                "tid": "-1",
                "id": "14909013234860823112",
                "username": "wxid_demo",
                "nickname": "demo",
                "createTime": 1777292875,
                "contentDesc": "ixus 95 850 A12",
                "media": [
                    {
                        "type": 6,
                        "url": "http://127.0.0.1:5031/video.mp4",
                        "thumb": "http://127.0.0.1:5031/thumb.jpg",
                    }
                ],
            }
        ],
    }

    moments = parse_timeline_response(payload)

    assert len(moments) == 1
    assert moments[0].moment_id == "14909013234860823112"
    assert moments[0].author_wxid == "wxid_demo"
    assert moments[0].content == "ixus 95 850 A12"
    assert moments[0].video_urls == ["http://127.0.0.1:5031/video.mp4"]
    assert moments[0].image_urls == []


def test_parse_timeline_response_prefers_raw_video_url_but_skips_video_cover_image():
    payload = {
        "success": True,
        "count": 1,
        "timeline": [
            {
                "tid": "-1",
                "id": "14909017727237493252",
                "username": "wxid_demo",
                "nickname": "demo",
                "createTime": 1777293411,
                "contentDesc": "sony wx300",
                "media": [
                    {
                        "type": 6,
                        "url": "http://127.0.0.1:5031/api/v1/sns/media/proxy?url=https%3A%2F%2Fvideo.qq.com%2Fvideo.mp4&key=1",
                        "thumb": "http://127.0.0.1:5031/api/v1/sns/media/proxy?url=https%3A%2F%2Fthumb.qq.com%2Fthumb.jpg&key=2",
                        "rawUrl": "https://video.qq.com/video.mp4",
                        "rawThumb": "https://thumb.qq.com/thumb.jpg",
                    }
                ],
            }
        ],
    }

    moments = parse_timeline_response(payload)

    assert moments[0].video_urls == ["https://video.qq.com/video.mp4"]
    assert moments[0].image_urls == []


def test_parse_timeline_response_prefers_proxy_url_for_image_posts():
    payload = {
        "success": True,
        "count": 1,
        "timeline": [
            {
                "tid": "-1",
                "id": "14909017727237493253",
                "username": "wxid_demo",
                "nickname": "demo",
                "createTime": 1777293411,
                "contentDesc": "image post",
                "media": [
                    {
                        "type": 2,
                        "url": "http://127.0.0.1:5031/api/v1/sns/media/proxy?url=https%3A%2F%2Fimage.qq.com%2Fimage.jpg&key=1",
                        "proxyUrl": "http://127.0.0.1:5031/api/v1/sns/media/proxy?url=https%3A%2F%2Fimage.qq.com%2Fproxy-image.jpg&key=9",
                        "thumb": "http://127.0.0.1:5031/api/v1/sns/media/proxy?url=https%3A%2F%2Fimage.qq.com%2Fthumb.jpg&key=2",
                        "rawUrl": "https://image.qq.com/image.jpg",
                        "rawThumb": "https://image.qq.com/thumb.jpg",
                    }
                ],
            }
        ],
    }

    moments = parse_timeline_response(payload)

    assert moments[0].image_urls == [
        "http://127.0.0.1:5031/api/v1/sns/media/proxy?url=https%3A%2F%2Fimage.qq.com%2Fproxy-image.jpg&key=9"
    ]


class FakeClient:
    def resolve_usernames(self, targets):
        return ["wxid_123"]

    def fetch_timeline(self, usernames, start, end):
        return []


def test_sync_service_handles_empty_result_without_error():
    temp_root = _make_temp_root("pytest-service-temp-")

    try:
        model_file = temp_root / "models.txt"
        model_file.write_text("ixus 95\n", encoding="utf-8")
        config_file = temp_root / "config.yaml"
        config_file.write_text(
            f"""
weflow:
  base_url: "http://127.0.0.1:5030"
  timeout_seconds: 20
task:
  days: 30
  merge_window_minutes: 10
  output_dir: "{(temp_root / 'output').as_posix()}"
targets:
  - remark_name: "user-a"
    wxid: "wxid_123"
rules:
  required_fields:
    - model
    - price
    - serial_no
paths:
  sqlite_db: "{(temp_root / 'inventory.db').as_posix()}"
  model_dict: "{model_file.as_posix()}"
""",
            encoding="utf-8",
        )
        settings = load_settings(config_file)
        service = SyncService(settings=settings, client=FakeClient())

        records = service.sync(now=datetime.fromisoformat("2026-04-27T12:00:00+08:00"))

        assert records == []
    finally:
        shutil.rmtree(temp_root, ignore_errors=True)


def test_sync_service_filters_out_posts_without_ccd_model():
    temp_root = _make_temp_root("pytest-service-filter-temp-")

    try:
        model_file = temp_root / "models.txt"
        model_file.write_text("ixus 95\n", encoding="utf-8")
        config_file = temp_root / "config.yaml"
        config_file.write_text(
            f"""
weflow:
  base_url: "http://127.0.0.1:5030"
  timeout_seconds: 20
task:
  days: 30
  merge_window_minutes: 10
  output_dir: "{(temp_root / 'output').as_posix()}"
targets:
  - remark_name: "user-a"
    wxid: "wxid_123"
rules:
  required_fields:
    - model
    - price
    - serial_no
paths:
  sqlite_db: "{(temp_root / 'inventory.db').as_posix()}"
  model_dict: "{model_file.as_posix()}"
""",
            encoding="utf-8",
        )
        settings = load_settings(config_file)

        class NonCcdClient:
            def resolve_usernames(self, targets):
                return ["wxid_123"]

            def fetch_timeline(self, usernames, start, end):
                return [
                    RawMoment(
                        "m1",
                        "user-a",
                        "wxid_123",
                        datetime.fromisoformat("2026-04-27T12:00:00+08:00"),
                        "rest day",
                        [],
                        [],
                    )
                ]

        service = SyncService(settings=settings, client=NonCcdClient())

        records = service.sync(now=datetime.fromisoformat("2026-04-27T12:30:00+08:00"))

        assert records == []
        assert service.load_records() == []
    finally:
        shutil.rmtree(temp_root, ignore_errors=True)


def test_sync_service_fetches_each_username_separately_to_avoid_global_limit_loss():
    temp_root = _make_temp_root("pytest-service-per-user-temp-")

    try:
        model_file = temp_root / "models.txt"
        model_file.write_text("canon a2400\ncanon ixus95\n", encoding="utf-8")
        config_file = temp_root / "config.yaml"
        config_file.write_text(
            f"""
weflow:
  base_url: "http://127.0.0.1:5030"
  timeout_seconds: 20
task:
  days: 30
  merge_window_minutes: 10
  output_dir: "{(temp_root / 'output').as_posix()}"
targets:
  - remark_name: "user-1"
    wxid: "wxid_1"
  - remark_name: "user-2"
    wxid: "wxid_2"
rules:
  required_fields:
    - model
    - price
    - serial_no
paths:
  sqlite_db: "{(temp_root / 'inventory.db').as_posix()}"
  model_dict: "{model_file.as_posix()}"
""",
            encoding="utf-8",
        )
        settings = load_settings(config_file)

        class PerUserClient:
            def __init__(self):
                self.fetch_calls = []

            def resolve_usernames(self, targets):
                return ["wxid_1", "wxid_2"]

            def fetch_timeline(self, usernames, start, end):
                self.fetch_calls.append(list(usernames))
                if usernames == ["wxid_1"]:
                    published_at = datetime.fromisoformat("2026-04-25T20:25:40+08:00")
                    return [
                        RawMoment(
                            "m1",
                            "user-1",
                            "wxid_1",
                            published_at,
                            "馃挵799 canon a2400",
                            ["a.jpg"],
                            [],
                        ),
                        RawMoment(
                            "m2",
                            "user-1",
                            "wxid_1",
                            published_at + timedelta(seconds=27),
                            "canon a2400",
                            [],
                            [],
                        ),
                    ]
                if usernames == ["wxid_2"]:
                    published_at = datetime.fromisoformat("2026-04-26T10:00:00+08:00")
                    return [
                        RawMoment(
                            "m3",
                            "user-2",
                            "wxid_2",
                            published_at,
                            "馃挵568 canon ixus95 A12",
                            ["b.jpg"],
                            [],
                        )
                    ]
                return []

        client = PerUserClient()
        service = SyncService(settings=settings, client=client)

        records = service.sync(now=datetime.fromisoformat("2026-04-27T12:00:00+08:00"))

        assert client.fetch_calls == [["wxid_1"], ["wxid_2"]]
        a2400_records = [r for r in records if r.model == "canon a2400"]
        assert len(a2400_records) == 1
        assert a2400_records[0].source_moment_ids == ["m1", "m2"]
    finally:
        shutil.rmtree(temp_root, ignore_errors=True)


def test_build_parser_supports_sync_export_flag():
    parser = build_parser()
    args = parser.parse_args(["sync", "--export"])

    assert args.command == "sync"
    assert args.export is True


def test_fetch_timeline_adds_bearer_token_header():
    temp_root = _make_temp_root("pytest-token-temp-")

    try:
        model_file = temp_root / "models.txt"
        model_file.write_text("ixus 95\n", encoding="utf-8")
        config_file = temp_root / "config.yaml"
        config_file.write_text(
            f"""
weflow:
  base_url: "http://127.0.0.1:5031"
  timeout_seconds: 20
  access_token: "demo-token"
task:
  days: 30
  merge_window_minutes: 10
  output_dir: "{(temp_root / 'output').as_posix()}"
targets:
  - remark_name: "user-a"
    wxid: "wxid_123"
rules:
  required_fields:
    - model
    - price
    - serial_no
paths:
  sqlite_db: "{(temp_root / 'inventory.db').as_posix()}"
  model_dict: "{model_file.as_posix()}"
""",
            encoding="utf-8",
        )
        settings = load_settings(config_file)

        captured = {}

        class FakeResponse:
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def read(self):
                return b'{"data": []}'

        def fake_urlopen(request, timeout):
            captured["authorization"] = request.headers.get("Authorization")
            captured["timeout"] = timeout
            captured["url"] = request.full_url
            return FakeResponse()

        original_urlopen = weflow_module.urlopen
        weflow_module.urlopen = fake_urlopen
        try:
            client = WeFlowClient(settings)
            client.fetch_timeline(["wxid_123"], "2026-04-01T00:00:00+08:00", "2026-04-27T00:00:00+08:00")
        finally:
            weflow_module.urlopen = original_urlopen

        assert captured["authorization"] == "Bearer demo-token"
        assert captured["timeout"] == 20
        assert captured["url"].startswith("http://127.0.0.1:5031/api/v1/sns/timeline?")
    finally:
        shutil.rmtree(temp_root, ignore_errors=True)


def test_resolve_usernames_prefers_wxid_and_matches_remark_name():
    temp_root = _make_temp_root("pytest-resolve-temp-")

    try:
        model_file = temp_root / "models.txt"
        model_file.write_text("ixus 95\n", encoding="utf-8")
        config_file = temp_root / "config.yaml"
        config_file.write_text(
            f"""
weflow:
  base_url: "http://127.0.0.1:5031"
  timeout_seconds: 20
  access_token: "demo-token"
task:
  days: 30
  merge_window_minutes: 10
  output_dir: "{(temp_root / 'output').as_posix()}"
targets:
  - remark_name: "lookup"
    wxid: ""
  - remark_name: "fixed"
    wxid: "wxid_fixed"
rules:
  required_fields:
    - model
    - price
    - serial_no
paths:
  sqlite_db: "{(temp_root / 'inventory.db').as_posix()}"
  model_dict: "{model_file.as_posix()}"
""",
            encoding="utf-8",
        )
        settings = load_settings(config_file)

        class FakeResponse:
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def read(self):
                return json.dumps(
                    {
                        "success": True,
                        "count": 2,
                        "contacts": [
                            {
                                "username": "wxid_lookup",
                                "displayName": "lookup",
                                "nickname": "lookup",
                                "type": "friend",
                            },
                            {
                                "username": "wxid_other",
                                "displayName": "other",
                                "nickname": "other",
                                "type": "friend",
                            },
                        ],
                    }
                ).encode("utf-8")

        def fake_urlopen(request, timeout):
            return FakeResponse()

        original_urlopen = weflow_module.urlopen
        weflow_module.urlopen = fake_urlopen
        try:
            client = WeFlowClient(settings)
            usernames = client.resolve_usernames(settings.targets)
        finally:
            weflow_module.urlopen = original_urlopen

        assert usernames == ["wxid_lookup", "wxid_fixed"]
    finally:
        shutil.rmtree(temp_root, ignore_errors=True)


def test_fetch_timeline_retries_after_transient_network_error():
    temp_root = _make_temp_root("pytest-retry-temp-")

    try:
        model_file = temp_root / "models.txt"
        model_file.write_text("ixus 95\n", encoding="utf-8")
        config_file = temp_root / "config.yaml"
        config_file.write_text(
            f"""
weflow:
  base_url: "http://127.0.0.1:5031"
  timeout_seconds: 20
task:
  days: 30
  merge_window_minutes: 10
  output_dir: "{(temp_root / 'output').as_posix()}"
targets:
  - remark_name: "user-a"
    wxid: "wxid_123"
rules:
  required_fields:
    - model
    - price
    - serial_no
paths:
  sqlite_db: "{(temp_root / 'inventory.db').as_posix()}"
  model_dict: "{model_file.as_posix()}"
""",
            encoding="utf-8",
        )
        settings = load_settings(config_file)
        attempts = {"count": 0}

        class FakeResponse:
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def read(self):
                return b'{"data": []}'

        def fake_urlopen(request, timeout):
            attempts["count"] += 1
            if attempts["count"] < 3:
                raise URLError("temporary network issue")
            return FakeResponse()

        original_urlopen = weflow_module.urlopen
        weflow_module.urlopen = fake_urlopen
        try:
            client = WeFlowClient(settings)
            result = client.fetch_timeline(
                ["wxid_123"],
                "2026-04-01T00:00:00+08:00",
                "2026-04-27T00:00:00+08:00",
            )
        finally:
            weflow_module.urlopen = original_urlopen

        assert result == []
        assert attempts["count"] == 3
    finally:
        shutil.rmtree(temp_root, ignore_errors=True)


def test_fetch_timeline_raises_project_error_after_http_failure():
    temp_root = _make_temp_root("pytest-http-fail-temp-")

    try:
        model_file = temp_root / "models.txt"
        model_file.write_text("ixus 95\n", encoding="utf-8")
        config_file = temp_root / "config.yaml"
        config_file.write_text(
            f"""
weflow:
  base_url: "http://127.0.0.1:5031"
  timeout_seconds: 20
task:
  days: 30
  merge_window_minutes: 10
  output_dir: "{(temp_root / 'output').as_posix()}"
targets:
  - remark_name: "user-a"
    wxid: "wxid_123"
rules:
  required_fields:
    - model
    - price
    - serial_no
paths:
  sqlite_db: "{(temp_root / 'inventory.db').as_posix()}"
  model_dict: "{model_file.as_posix()}"
""",
            encoding="utf-8",
        )
        settings = load_settings(config_file)

        def fake_urlopen(request, timeout):
            raise HTTPError(request.full_url, 502, "bad gateway", hdrs=None, fp=None)

        original_urlopen = weflow_module.urlopen
        weflow_module.urlopen = fake_urlopen
        try:
            client = WeFlowClient(settings)
            with pytest.raises(WeFlowRequestError, match="502"):
                client.fetch_timeline(
                    ["wxid_123"],
                    "2026-04-01T00:00:00+08:00",
                    "2026-04-27T00:00:00+08:00",
                )
        finally:
            weflow_module.urlopen = original_urlopen
    finally:
        shutil.rmtree(temp_root, ignore_errors=True)


def test_sync_service_logs_summary(caplog):
    temp_root = _make_temp_root("pytest-service-log-temp-")

    try:
        model_file = temp_root / "models.txt"
        model_file.write_text("ixus 95\n", encoding="utf-8")
        config_file = temp_root / "config.yaml"
        config_file.write_text(
            f"""
weflow:
  base_url: "http://127.0.0.1:5030"
  timeout_seconds: 20
task:
  days: 30
  merge_window_minutes: 10
  output_dir: "{(temp_root / 'output').as_posix()}"
targets:
  - remark_name: "user-a"
    wxid: "wxid_123"
rules:
  required_fields:
    - model
    - price
    - serial_no
paths:
  sqlite_db: "{(temp_root / 'inventory.db').as_posix()}"
  model_dict: "{model_file.as_posix()}"
""",
            encoding="utf-8",
        )
        settings = load_settings(config_file)

        class OneRecordClient:
            def resolve_usernames(self, targets):
                return ["wxid_123"]

            def fetch_timeline(self, usernames, start, end):
                return [
                    RawMoment(
                        "m1",
                        "user-a",
                        "wxid_123",
                        datetime.fromisoformat("2026-04-27T12:00:00+08:00"),
                        "ixus 95 850",
                        ["a.jpg"],
                        [],
                    )
                ]

        caplog.set_level("INFO")
        service = SyncService(settings=settings, client=OneRecordClient())
        service.sync(now=datetime.fromisoformat("2026-04-27T12:30:00+08:00"))

        assert "sync started" in caplog.text
        assert "sync completed" in caplog.text
    finally:
        shutil.rmtree(temp_root, ignore_errors=True)
