from __future__ import annotations

import json
from datetime import datetime
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from moments_inventory.config import Settings
from moments_inventory.logging_utils import get_logger
from moments_inventory.models import RawMoment, TargetContact


LOGGER = get_logger(__name__)
MAX_RETRIES = 3
RETRY_DELAY_SECONDS = 0.1
RETRYABLE_STATUS_CODES = {408, 429, 500, 502, 503, 504}


class WeFlowRequestError(RuntimeError):
    pass


def _looks_like_video_url(url: str | None) -> bool:
    if not url:
        return False
    lowered = url.lower()
    return "video.qq.com" in lowered or "snsvideodownload" in lowered or ".mp4" in lowered


def _pick_video_url(media: dict) -> str | None:
    return media.get("rawUrl") or media.get("url")


def _pick_image_url(media: dict) -> str | None:
    return (
        media.get("proxyUrl")
        or media.get("resolvedUrl")
        or media.get("url")
        or media.get("proxyThumbUrl")
        or media.get("resolvedThumbUrl")
        or media.get("thumb")
        or media.get("rawUrl")
        or media.get("rawThumb")
    )


def parse_timeline_response(payload: dict) -> list[RawMoment]:
    items = payload.get("data") or payload.get("timeline") or []
    moments: list[RawMoment] = []
    for item in items:
        if "create_time" in item:
            published_at = datetime.fromisoformat(item["create_time"])
            content = item.get("content", "")
            image_urls = item.get("images", [])
            video_urls = item.get("videos", [])
        else:
            published_at = datetime.fromtimestamp(item["createTime"]).astimezone()
            content = item.get("contentDesc", "")
            image_urls = []
            video_urls = []
            for media in item.get("media", []):
                media_type = media.get("type")
                video_url = _pick_video_url(media)
                if media_type == 6 or _looks_like_video_url(video_url):
                    if video_url:
                        video_urls.append(video_url)
                    continue

                image_url = _pick_image_url(media)
                if image_url:
                    image_urls.append(image_url)

        moments.append(
            RawMoment(
                moment_id=str(item["id"]),
                author_remark_name=item.get("remark") or item.get("displayName") or item.get("nickname"),
                author_wxid=item.get("username"),
                published_at=published_at,
                content=content,
                image_urls=image_urls,
                video_urls=video_urls,
            )
        )
    return moments


class WeFlowClient:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def _build_headers(self) -> dict[str, str]:
        headers: dict[str, str] = {}
        if self._settings.weflow.access_token:
            headers["Authorization"] = f"Bearer {self._settings.weflow.access_token}"
        return headers

    def _build_url(self, path: str, query: dict[str, str] | None = None) -> str:
        url = f"{self._settings.weflow.base_url.rstrip('/')}{path}"
        if query:
            url = f"{url}?{urlencode(query)}"
        return url

    def _should_retry_http_error(self, error: HTTPError) -> bool:
        return error.code in RETRYABLE_STATUS_CODES

    def _get_json(self, path: str, query: dict[str, str] | None = None) -> dict:
        url = self._build_url(path, query)
        request = Request(url, headers=self._build_headers())

        for attempt in range(1, MAX_RETRIES + 1):
            try:
                with urlopen(request, timeout=self._settings.weflow.timeout_seconds) as response:
                    payload = response.read().decode("utf-8")
                return json.loads(payload)
            except HTTPError as error:
                if attempt < MAX_RETRIES and self._should_retry_http_error(error):
                    LOGGER.warning(
                        "weflow request retrying after HTTP error",
                        extra={"path": path, "attempt": attempt, "status_code": error.code},
                    )
                    time.sleep(RETRY_DELAY_SECONDS)
                    continue
                LOGGER.error("weflow request failed", extra={"path": path, "status_code": error.code})
                raise WeFlowRequestError(f"WeFlow 请求失败: {error.code} {path}") from error
            except URLError as error:
                if attempt < MAX_RETRIES:
                    LOGGER.warning(
                        "weflow request retrying after network error",
                        extra={"path": path, "attempt": attempt, "reason": str(error.reason)},
                    )
                    time.sleep(RETRY_DELAY_SECONDS)
                    continue
                LOGGER.error("weflow request network failure", extra={"path": path, "reason": str(error.reason)})
                raise WeFlowRequestError(f"WeFlow 网络请求失败: {path}") from error
            except json.JSONDecodeError as error:
                LOGGER.error("weflow response is not valid json", extra={"path": path})
                raise WeFlowRequestError(f"WeFlow 返回了非法 JSON: {path}") from error
            except OSError as error:
                if attempt < MAX_RETRIES:
                    LOGGER.warning(
                        "weflow request retrying after os error",
                        extra={"path": path, "attempt": attempt, "reason": str(error)},
                    )
                    time.sleep(RETRY_DELAY_SECONDS)
                    continue
                LOGGER.error("weflow request os failure", extra={"path": path, "reason": str(error)})
                raise WeFlowRequestError(f"WeFlow 请求失败: {path}") from error

        raise WeFlowRequestError(f"WeFlow 请求失败: {path}")

    def resolve_usernames(self, targets: list[TargetContact]) -> list[str]:
        contacts_payload = self._get_json("/api/v1/contacts", {"count": "2000"})
        contacts = contacts_payload.get("contacts", [])

        usernames: list[str] = []
        for target in targets:
            if target.wxid:
                usernames.append(target.wxid)
                continue
            if not target.remark_name:
                continue
            match = next(
                (
                    contact
                    for contact in contacts
                    if target.remark_name
                    in " ".join(
                        [
                            str(contact.get("displayName", "")),
                            str(contact.get("remark", "")),
                            str(contact.get("nickname", "")),
                            str(contact.get("alias", "")),
                        ]
                    )
                ),
                None,
            )
            if match and match.get("username"):
                usernames.append(match["username"])
        LOGGER.info("resolved usernames", extra={"target_count": len(targets), "username_count": len(usernames)})
        return usernames

    def fetch_timeline(self, usernames: list[str], start: str, end: str) -> list[RawMoment]:
        payload = self._get_json(
            "/api/v1/sns/timeline",
            {
                "usernames": ",".join(usernames),
                "start": start,
                "end": end,
                "limit": "500",
            }
        )
        moments = parse_timeline_response(payload)
        LOGGER.info("fetched timeline", extra={"username_count": len(usernames), "moment_count": len(moments)})
        return moments
