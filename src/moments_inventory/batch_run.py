from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Callable
import uuid

from moments_inventory.config import Settings
from moments_inventory.logging_utils import get_logger
from moments_inventory.matcher import deduplicate_and_merge
from moments_inventory.models import InventoryRecord, RawMoment, TargetContact
from moments_inventory.storage import InventoryStore
from moments_inventory.weflow_client import WeFlowClient


LOGGER = get_logger(__name__)


@dataclass(slots=True)
class BatchStageResult:
    batch_index: int
    targets: list[TargetContact]
    usernames: list[str] = field(default_factory=list)
    records: list[InventoryRecord] = field(default_factory=list)


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
    def deduplicate_targets(targets: list[TargetContact]) -> list[TargetContact]:
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
    def _target_remark_names_by_wxid(targets: list[TargetContact]) -> dict[str, str]:
        return {
            target.wxid: target.remark_name
            for target in targets
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

    @staticmethod
    def chunk_targets(targets: list[TargetContact], batch_size: int) -> list[list[TargetContact]]:
        return [
            targets[index:index + batch_size]
            for index in range(0, len(targets), batch_size)
        ]

    @staticmethod
    def normalize_now(now: datetime | None = None) -> datetime:
        if now is None:
            return datetime.now().astimezone()
        if now.tzinfo is None:
            return now.astimezone()
        return now

    def stage_batch(
        self,
        *,
        run_id: str,
        batch_index: int,
        batch_targets: list[TargetContact],
        current_time: datetime,
        processed_usernames: set[str] | None = None,
    ) -> BatchStageResult:
        processed_usernames = processed_usernames or set()
        start_time = current_time - timedelta(days=self._settings.task.days)
        target_remark_names_by_wxid = self._target_remark_names_by_wxid(batch_targets)
        usernames = self._deduplicate_usernames(
            self._client.resolve_usernames(batch_targets)
        )
        usernames = [
            username for username in usernames
            if username not in processed_usernames
        ]
        if not usernames:
            return BatchStageResult(
                batch_index=batch_index,
                targets=list(batch_targets),
                usernames=[],
                records=[],
            )

        if self._warmup_runner is not None:
            self._warmup_runner(batch_targets)

        moments: list[RawMoment] = []
        for username in usernames:
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

        records = deduplicate_and_merge(
            moments,
            model_keywords=self._settings.model_keywords,
            merge_minutes=self._settings.task.merge_window_minutes,
        )
        records = [record for record in records if self._is_relevant_record(record)]
        self._store.stage_records(run_id, batch_index, records)
        return BatchStageResult(
            batch_index=batch_index,
            targets=list(batch_targets),
            usernames=usernames,
            records=records,
        )

    def finalize_run(
        self,
        *,
        run_id: str,
        current_time: datetime,
    ) -> list[InventoryRecord]:
        self._store.replace_current_records_from_stage(
            run_id,
            committed_at=current_time.isoformat(),
        )
        records = self._store.list_all_records()
        self._store.clear_staged_records(run_id)
        return records

    def clear_run(self, run_id: str) -> None:
        self._store.clear_staged_records(run_id)

    def list_staged_records(self, run_id: str) -> list[InventoryRecord]:
        return self._store.list_staged_records(run_id)

    def run(self, now: datetime | None = None) -> list[InventoryRecord]:
        current_time = self.normalize_now(now)
        run_id = uuid.uuid4().hex
        deduplicated_targets = self.deduplicate_targets(self._settings.targets)
        batches = self.chunk_targets(
            deduplicated_targets,
            self._settings.batch_run.batch_size,
        )
        processed_usernames: set[str] = set()

        try:
            for batch_index, batch_targets in enumerate(batches):
                result = self.stage_batch(
                    run_id=run_id,
                    batch_index=batch_index,
                    batch_targets=batch_targets,
                    current_time=current_time,
                    processed_usernames=processed_usernames,
                )
                processed_usernames.update(result.usernames)

            records = self.finalize_run(run_id=run_id, current_time=current_time)
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
            self.clear_run(run_id)
            LOGGER.exception(
                "batch run failed",
                extra={"run_id": run_id, "batch_count": len(batches)},
            )
            raise
