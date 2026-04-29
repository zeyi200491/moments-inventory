from __future__ import annotations

from datetime import timedelta

from moments_inventory.models import InventoryRecord, RawMoment
from moments_inventory.parser import parse_content
from moments_inventory.utils import normalize_text

SAME_MODEL_FOLLOWUP_MINUTES = 60


def _serial_matches_model(record: InventoryRecord) -> bool:
    if not record.model or not record.serial_no:
        return False
    return normalize_text(record.model).replace(" ", "") == record.serial_no.lower()


def _build_record(moment: RawMoment, model_keywords: list[str]) -> InventoryRecord:
    parsed = parse_content(moment.content, model_keywords)
    key = f"{moment.author_wxid}|{normalize_text(moment.content)}|{moment.published_at.isoformat()}"
    return InventoryRecord(
        record_key=key,
        remark_name=moment.author_remark_name,
        wxid=moment.author_wxid,
        published_at=moment.published_at,
        model=parsed.model,
        price=parsed.price,
        serial_no=parsed.serial_no,
        status="未售卖",
        image_urls=list(moment.image_urls),
        video_urls=list(moment.video_urls),
        content_text=moment.content,
        note=parsed.note,
        needs_manual=parsed.needs_manual,
        source_moment_ids=[moment.moment_id],
    )


def _is_model_stub(record: InventoryRecord) -> bool:
    if not record.model or record.price is not None:
        return False
    return record.serial_no is None or _serial_matches_model(record)


def _can_merge_same_model_followup(
    record: InventoryRecord,
    next_record: InventoryRecord,
    current: RawMoment,
    nxt: RawMoment,
) -> bool:
    if not (
        record.model
        and next_record.model
        and record.model == next_record.model
        and (_is_model_stub(record) or _is_model_stub(next_record))
    ):
        return False

    return nxt.published_at - current.published_at <= timedelta(
        minutes=SAME_MODEL_FOLLOWUP_MINUTES
    )


def deduplicate_and_merge(
    moments: list[RawMoment], model_keywords: list[str], merge_minutes: int = 10
) -> list[InventoryRecord]:
    ordered = sorted(moments, key=lambda item: (item.author_wxid or "", item.published_at))
    deduped: list[RawMoment] = []
    seen: dict[tuple[str | None, str], RawMoment] = {}

    for moment in ordered:
        normalized = normalize_text(moment.content)
        key = (moment.author_wxid, normalized)
        existing = seen.get(key)
        if existing is None:
            seen[key] = moment
            deduped.append(moment)
            continue
        existing.image_urls = sorted(set(existing.image_urls + moment.image_urls))
        existing.video_urls = sorted(set(existing.video_urls + moment.video_urls))

    records: list[InventoryRecord] = []
    index = 0
    while index < len(deduped):
        current = deduped[index]
        record = _build_record(current, model_keywords)
        if index + 1 < len(deduped):
            nxt = deduped[index + 1]
            is_same_author = current.author_wxid == nxt.author_wxid
            different_text = normalize_text(current.content) != normalize_text(nxt.content)
            if is_same_author and different_text:
                next_record = _build_record(nxt, model_keywords)
                is_close = nxt.published_at - current.published_at <= timedelta(
                    minutes=merge_minutes
                )
                conflict_model = (
                    record.model and next_record.model and record.model != next_record.model
                )
                conflict_price = (
                    record.price and next_record.price and record.price != next_record.price
                )
                complementary = (
                    (record.model or record.price)
                    and (next_record.serial_no or next_record.video_urls)
                ) or (
                    (next_record.model or next_record.price)
                    and (record.serial_no or record.video_urls)
                )
                same_model_followup = _can_merge_same_model_followup(
                    record,
                    next_record,
                    current,
                    nxt,
                )
                can_merge = (
                    (is_close and complementary)
                    or same_model_followup
                )
                if can_merge and not conflict_model and not conflict_price:
                    record.model = record.model or next_record.model
                    record.price = record.price or next_record.price
                    record.serial_no = record.serial_no or next_record.serial_no
                    record.image_urls = sorted(set(record.image_urls + next_record.image_urls))
                    record.video_urls = sorted(set(record.video_urls + next_record.video_urls))
                    record.content_text = f"{record.content_text}\n{next_record.content_text}"
                    record.source_moment_ids.extend(next_record.source_moment_ids)
                    record.needs_manual = any(
                        value is None for value in (record.model, record.price, record.serial_no)
                    )
                    index += 2
                    records.append(record)
                    continue
        records.append(record)
        index += 1
    return records
