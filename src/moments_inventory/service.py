from __future__ import annotations

from datetime import datetime, timedelta

from moments_inventory.config import Settings
from moments_inventory.logging_utils import get_logger
from moments_inventory.models import RawMoment
from moments_inventory.matcher import deduplicate_and_merge
from moments_inventory.storage import InventoryStore
from moments_inventory.weflow_client import WeFlowClient


LOGGER = get_logger(__name__)


class SyncService:
    def __init__(self, settings: Settings, client: WeFlowClient | None = None) -> None:
        self._settings = settings
        self._client = client or WeFlowClient(settings)
        self._store = InventoryStore(settings.paths.sqlite_db)

    @staticmethod
    def _is_relevant_record(record) -> bool:
        return bool(record.model)

    def _target_remark_names_by_wxid(self) -> dict[str, str]:
        return {
            target.wxid: target.remark_name
            for target in self._settings.targets
            if target.wxid and target.remark_name
        }

    @staticmethod
    def _canonicalize_moment_remark_names(
        moments: list[RawMoment],
        target_remark_names_by_wxid: dict[str, str],
    ) -> None:
        for moment in moments:
            if not moment.author_wxid:
                continue
            target_remark_name = target_remark_names_by_wxid.get(moment.author_wxid)
            if target_remark_name:
                moment.author_remark_name = target_remark_name

    def sync(self, now: datetime | None = None):
        if now is None:
            current_time = datetime.now().astimezone()
        elif now.tzinfo is None:
            current_time = now.astimezone()
        else:
            current_time = now
        start_time = current_time - timedelta(days=self._settings.task.days)
        LOGGER.info(
            "sync started",
            extra={"target_count": len(self._settings.targets), "days": self._settings.task.days},
        )
        usernames = self._client.resolve_usernames(self._settings.targets)
        target_remark_names_by_wxid = self._target_remark_names_by_wxid()
        moments = []
        snapshot_complete = True
        for username in usernames:
            try:
                user_moments = self._client.fetch_timeline(
                    usernames=[username],
                    start=start_time.isoformat(),
                    end=current_time.isoformat(),
                )
                self._canonicalize_moment_remark_names(
                    user_moments,
                    target_remark_names_by_wxid,
                )
                moments.extend(user_moments)
            except Exception:
                snapshot_complete = False
                LOGGER.exception("sync fetch failed", extra={"username": username})
        records = deduplicate_and_merge(
            moments,
            model_keywords=self._settings.model_keywords,
            merge_minutes=self._settings.task.merge_window_minutes,
        )
        records = [record for record in records if self._is_relevant_record(record)]
        fetched_moment_ids = {moment.moment_id for moment in moments}
        self._store.upsert_records(
            records=records,
            fetched_moment_ids=fetched_moment_ids,
            sync_started_at=current_time.isoformat(),
            snapshot_complete=snapshot_complete,
        )
        LOGGER.info(
            "sync completed",
            extra={
                "username_count": len(usernames),
                "moment_count": len(moments),
                "record_count": len(records),
                "snapshot_complete": snapshot_complete,
            },
        )
        return records

    def load_records(self):
        return self._store.list_all_records()
