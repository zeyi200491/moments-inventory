from __future__ import annotations

from datetime import datetime, timedelta
from typing import Callable
import uuid

from moments_inventory.config import Settings
from moments_inventory.logging_utils import get_logger
from moments_inventory.matcher import deduplicate_and_merge
from moments_inventory.models import InventoryRecord, TargetContact
from moments_inventory.storage import InventoryStore
from moments_inventory.weflow_client import WeFlowClient


LOGGER = get_logger(__name__)


class BatchRunService:
    def __init__(
        self,
        settings: Settings,
        store: InventoryStore | None = None,
        client: WeFlowClient | None = None,
        warmup_runner: Callable[[list[TargetContact]], None] | None = None,
    ) -> None:
        self._settings = settings
        self._store = store or InventoryStore(settings.paths.sqlite_db)
        self._client = client or WeFlowClient(settings)
        self._warmup_runner = warmup_runner

    @staticmethod
    def _is_relevant_record(record: InventoryRecord) -> bool:
        return bool(record.model)

    @staticmethod
    def _deduplicate_targets(targets: list[TargetContact]) -> list[TargetContact]:
        seen: set[tuple[str, str]] = set()
        deduplicated: list[TargetContact] = []
        for target in targets:
            if target.wxid:
                key = ("wxid", target.wxid)
            elif target.remark_name:
                key = ("remark_name", target.remark_name)
            else:
                key = ("anonymous", "")
            if key in seen:
                continue
            seen.add(key)
            deduplicated.append(target)
        return deduplicated

    @staticmethod
    def _deduplicate_usernames(usernames: list[str]) -> list[str]:
        seen: set[str] = set()
        deduplicated: list[str] = []
        for username in usernames:
            if username in seen:
                continue
            seen.add(username)
            deduplicated.append(username)
        return deduplicated

    @staticmethod
    def _chunk_targets(targets: list[TargetContact], batch_size: int) -> list[list[TargetContact]]:
        return [
            targets[index:index + batch_size]
            for index in range(0, len(targets), batch_size)
        ]

    def run(self, now: datetime | None = None) -> list[InventoryRecord]:
        if now is None:
            current_time = datetime.now().astimezone()
        elif now.tzinfo is None:
            current_time = now.astimezone()
        else:
            current_time = now

        run_id = uuid.uuid4().hex
        deduplicated_targets = self._deduplicate_targets(self._settings.targets)
        batches = self._chunk_targets(
            deduplicated_targets,
            self._settings.batch_run.batch_size,
        )
        start_time = current_time - timedelta(days=self._settings.task.days)
        processed_usernames: set[str] = set()

        try:
            for batch_index, batch_targets in enumerate(batches):
                usernames = self._deduplicate_usernames(
                    self._client.resolve_usernames(batch_targets)
                )
                usernames = [
                    username for username in usernames
                    if username not in processed_usernames
                ]
                if not usernames:
                    continue

                if self._warmup_runner is not None:
                    self._warmup_runner(batch_targets)

                moments = []
                for username in usernames:
                    moments.extend(
                        self._client.fetch_timeline(
                            usernames=[username],
                            start=start_time.isoformat(),
                            end=current_time.isoformat(),
                        )
                    )
                processed_usernames.update(usernames)

                records = deduplicate_and_merge(
                    moments,
                    model_keywords=self._settings.model_keywords,
                    merge_minutes=self._settings.task.merge_window_minutes,
                )
                records = [record for record in records if self._is_relevant_record(record)]
                self._store.stage_records(run_id, batch_index, records)

            self._store.replace_current_records_from_stage(
                run_id,
                committed_at=current_time.isoformat(),
            )
            records = self._store.list_all_records()
            self._store.clear_staged_records(run_id)
            LOGGER.info(
                "batch run completed",
                extra={
                    "run_id": run_id,
                    "batch_count": len(batches),
                    "record_count": len(records),
                },
            )
            return records
        except Exception:
            self._store.clear_staged_records(run_id)
            LOGGER.exception(
                "batch run failed",
                extra={"run_id": run_id, "batch_count": len(batches)},
            )
            raise
