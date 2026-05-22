from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


@dataclass(slots=True)
class TargetContact:
    remark_name: str | None
    wxid: str | None
    tier: int = 2


@dataclass(slots=True)
class ParsedFields:
    model: str | None = None
    price: int | None = None
    serial_no: str | None = None
    note: str = ""
    needs_manual: bool = False


@dataclass(slots=True)
class RawMoment:
    moment_id: str
    author_remark_name: str | None
    author_wxid: str | None
    published_at: datetime
    content: str
    image_urls: list[str] = field(default_factory=list)
    video_urls: list[str] = field(default_factory=list)


@dataclass(slots=True)
class InventoryRecord:
    record_key: str
    remark_name: str | None
    wxid: str | None
    published_at: datetime
    model: str | None
    price: int | None
    serial_no: str | None
    status: str
    image_urls: list[str] = field(default_factory=list)
    video_urls: list[str] = field(default_factory=list)
    content_text: str = ""
    note: str = ""
    needs_manual: bool = False
    source_moment_ids: list[str] = field(default_factory=list)
