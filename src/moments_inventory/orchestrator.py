from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime
import csv
import json
from pathlib import Path
from typing import Callable
import uuid

from moments_inventory.batch_run import BatchRunService
from moments_inventory.config import Settings
from moments_inventory.exporter import export_records
from moments_inventory.logging_utils import get_logger
from moments_inventory.models import InventoryRecord, TargetContact
from moments_inventory.storage import InventoryStore
from moments_inventory.weflow_client import WeFlowClient


LOGGER = get_logger(__name__)
DEFAULT_EXPORT_FILENAME = "current.xlsx"


@dataclass(slots=True)
class FailedTarget:
    remark_name: str | None
    wxid: str | None
    tier: int
    batch_label: str
    reason: str


class OrchestratedRunService:
    def __init__(
        self,
        settings: Settings,
        store: InventoryStore | None = None,
        client: WeFlowClient | None = None,
        warmup_runner: Callable[[list[TargetContact]], None] | None = None,
        export_func: Callable[..., Path] = export_records,
    ) -> None:
        self._settings = settings
        self._output_dir = Path(settings.task.output_dir)
        self._store = store or InventoryStore(settings.paths.sqlite_db)
        self._batch_service = BatchRunService(
            settings=settings,
            store=self._store,
            client=client,
            warmup_runner=warmup_runner,
        )
        self._export_func = export_func

    def run(
        self,
        *,
        mode: str | None = None,
        resume: bool = False,
        now: datetime | None = None,
    ) -> list[InventoryRecord]:
        selected_mode = mode or self._settings.orchestrator.mode
        if selected_mode not in {"priority_only", "full"}:
            raise RuntimeError(f"unsupported orchestrator mode: {selected_mode}")

        current_time = self._batch_service.normalize_now(now)
        deduplicated_targets = self._batch_service.deduplicate_targets(self._settings.targets)
        if not deduplicated_targets:
            raise RuntimeError("no targets configured")
        priority_targets = [target for target in deduplicated_targets if target.tier == 1]
        secondary_targets = [target for target in deduplicated_targets if target.tier != 1]
        progress = self._load_or_initialize_progress(
            mode=selected_mode,
            resume=resume,
            priority_targets=priority_targets,
            secondary_targets=secondary_targets,
        )
        run_id = str(progress["run_id"])
        processed_usernames = set(str(item) for item in progress.get("processed_usernames", []))
        failed_targets: list[FailedTarget] = []
        priority_retry_batches = {
            str(item) for item in progress.get("priority_failed_batches", [])
        } if resume else set()
        if resume:
            progress["failed_targets"] = []
            progress["priority_failed_batches"] = []
            progress["secondary_failed_batches"] = []
            if priority_retry_batches:
                progress["priority_export_done"] = False
            self._write_progress(progress)

        try:
            if not progress["priority_done"] or priority_retry_batches:
                priority_batches = self._batch_service.chunk_targets(
                    priority_targets,
                    self._settings.orchestrator.batch_size,
                )
                completed_priority_batches = set(
                    str(item) for item in progress.get("priority_completed_batches", [])
                )
                for batch_offset, batch_targets in enumerate(priority_batches):
                    batch_label = f"p1-{batch_offset + 1:02d}"
                    if resume and batch_label not in priority_retry_batches and (
                        progress["priority_done"] or batch_label in completed_priority_batches
                    ):
                        continue
                    try:
                        result = self._batch_service.stage_batch(
                            run_id=run_id,
                            batch_index=batch_offset,
                            batch_targets=batch_targets,
                            current_time=current_time,
                            processed_usernames=processed_usernames,
                        )
                        processed_usernames.update(result.usernames)
                        progress["priority_completed_batches"] = progress.get(
                            "priority_completed_batches",
                            [],
                        ) + [batch_label]
                        progress["processed_usernames"] = sorted(processed_usernames)
                        self._write_progress(progress)
                    except Exception as exc:
                        failed_targets.extend(
                            self._failed_targets_for_batch(batch_targets, batch_label, str(exc))
                        )
                        progress["failed_targets"] = [asdict(item) for item in failed_targets]
                        progress["priority_failed_batches"] = progress.get(
                            "priority_failed_batches",
                            [],
                        ) + [batch_label]
                        self._write_progress(progress)
                        self._write_failed_targets(failed_targets)
                        if self._settings.batch_run.stop_on_batch_failure:
                            raise
                progress["priority_done"] = True
                progress["processed_usernames"] = sorted(processed_usernames)
                self._write_progress(progress)

            if (
                self._settings.orchestrator.export_priority_after_p1
                and not progress["priority_export_done"]
                and not (
                    failed_targets
                    and self._settings.batch_run.export_only_when_all_batches_succeed
                )
            ):
                staged_records = self._batch_service.list_staged_records(run_id)
                priority_records = self._filter_records_for_targets(staged_records, priority_targets)
                self._export_named_records(
                    priority_records,
                    self._settings.orchestrator.priority_output_name,
                )
                progress["priority_export_done"] = True
                self._write_progress(progress)

            if selected_mode == "priority_only":
                staged_records = self._batch_service.list_staged_records(run_id)
                priority_records = self._filter_records_for_targets(staged_records, priority_targets)
                if (
                    failed_targets
                    and self._settings.batch_run.export_only_when_all_batches_succeed
                ):
                    LOGGER.warning(
                        "priority-only run finished with failures, skipped final export",
                        extra={"run_id": run_id, "failure_count": len(failed_targets)},
                    )
                    self._write_failed_targets(failed_targets)
                    return priority_records
                self._batch_service.clear_run(run_id)
                progress["completed"] = True
                self._write_progress(progress)
                if self._settings.orchestrator.write_failed_targets:
                    self._write_failed_targets(failed_targets)
                return priority_records

            secondary_batches = self._batch_service.chunk_targets(
                secondary_targets,
                self._settings.orchestrator.batch_size,
            )
            start_batch = int(progress.get("secondary_next_batch", 0))
            priority_batch_count = len(
                self._batch_service.chunk_targets(
                    priority_targets,
                    self._settings.orchestrator.batch_size,
                )
            )
            for batch_offset in range(start_batch, len(secondary_batches)):
                batch_targets = secondary_batches[batch_offset]
                batch_label = f"p2-{batch_offset + 1:02d}"
                try:
                    result = self._batch_service.stage_batch(
                        run_id=run_id,
                        batch_index=priority_batch_count + batch_offset,
                        batch_targets=batch_targets,
                        current_time=current_time,
                        processed_usernames=processed_usernames,
                    )
                    processed_usernames.update(result.usernames)
                    progress["secondary_next_batch"] = batch_offset + 1
                    progress["secondary_completed_batches"] = progress.get(
                        "secondary_completed_batches",
                        [],
                    ) + [batch_label]
                    progress["processed_usernames"] = sorted(processed_usernames)
                    self._write_progress(progress)
                except Exception as exc:
                    failed_targets.extend(
                        self._failed_targets_for_batch(batch_targets, batch_label, str(exc))
                    )
                    progress["failed_targets"] = [asdict(item) for item in failed_targets]
                    progress["secondary_failed_batches"] = progress.get(
                        "secondary_failed_batches",
                        [],
                    ) + [batch_label]
                    self._write_progress(progress)
                    self._write_failed_targets(failed_targets)
                    if self._settings.batch_run.stop_on_batch_failure:
                        raise

            if failed_targets and self._settings.batch_run.export_only_when_all_batches_succeed:
                LOGGER.warning(
                    "orchestrated run finished with failures, skipped final export",
                    extra={"run_id": run_id, "failure_count": len(failed_targets)},
                )
                return self._batch_service.list_staged_records(run_id)

            final_records = self._batch_service.finalize_run(
                run_id=run_id,
                current_time=current_time,
            )
            if self._settings.orchestrator.export_full_after_all:
                self._export_named_records(
                    final_records,
                    self._settings.orchestrator.full_output_name,
                )
            progress["full_export_done"] = self._settings.orchestrator.export_full_after_all
            progress["completed"] = True
            self._write_progress(progress)
            if self._settings.orchestrator.write_failed_targets:
                self._write_failed_targets(failed_targets)
            return final_records
        except Exception:
            progress["failed_targets"] = [asdict(item) for item in failed_targets]
            self._write_progress(progress)
            if self._settings.orchestrator.write_failed_targets:
                self._write_failed_targets(failed_targets)
            raise

    def _load_or_initialize_progress(
        self,
        *,
        mode: str,
        resume: bool,
        priority_targets: list[TargetContact],
        secondary_targets: list[TargetContact],
    ) -> dict[str, object]:
        self._output_dir.mkdir(parents=True, exist_ok=True)
        progress_path = self._progress_path()
        if resume:
            if not self._settings.orchestrator.resume_enabled:
                raise RuntimeError("resume is disabled by orchestrator config")
            if not progress_path.exists():
                raise RuntimeError("progress file missing for resume")
            progress = json.loads(progress_path.read_text(encoding="utf-8"))
            if progress.get("completed") is True:
                raise RuntimeError("completed run cannot be resumed")
            stored_mode = progress.get("mode")
            if stored_mode != mode:
                raise RuntimeError(
                    f"resume mode mismatch: progress={stored_mode}, requested={mode}"
                )
            return progress

        if progress_path.exists():
            existing = json.loads(progress_path.read_text(encoding="utf-8"))
            existing_run_id = existing.get("run_id")
            if isinstance(existing_run_id, str) and existing_run_id:
                self._batch_service.clear_run(existing_run_id)

        progress = {
            "run_id": uuid.uuid4().hex,
            "mode": mode,
            "priority_done": False,
            "priority_export_done": False,
            "priority_completed_batches": [],
            "priority_failed_batches": [],
            "secondary_next_batch": 0,
            "secondary_completed_batches": [],
            "secondary_failed_batches": [],
            "processed_usernames": [],
            "failed_targets": [],
            "completed": False,
            "full_export_done": False,
            "priority_target_count": len(priority_targets),
            "secondary_target_count": len(secondary_targets),
        }
        self._write_progress(progress)
        self._write_failed_targets([])
        return progress

    def _progress_path(self) -> Path:
        return self._output_dir / "progress.json"

    def _failed_targets_path(self) -> Path:
        return self._output_dir / "failed_targets.csv"

    def _write_progress(self, progress: dict[str, object]) -> None:
        self._output_dir.mkdir(parents=True, exist_ok=True)
        self._progress_path().write_text(
            json.dumps(progress, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

    def _write_failed_targets(self, failed_targets: list[FailedTarget]) -> None:
        if not self._settings.orchestrator.write_failed_targets:
            return
        with self._failed_targets_path().open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(
                handle,
                fieldnames=["remark_name", "wxid", "tier", "batch_label", "reason"],
            )
            writer.writeheader()
            for failed_target in failed_targets:
                writer.writerow(asdict(failed_target))

    @staticmethod
    def _failed_targets_for_batch(
        batch_targets: list[TargetContact],
        batch_label: str,
        reason: str,
    ) -> list[FailedTarget]:
        return [
            FailedTarget(
                remark_name=target.remark_name,
                wxid=target.wxid,
                tier=target.tier,
                batch_label=batch_label,
                reason=reason,
            )
            for target in batch_targets
        ]

    @staticmethod
    def _filter_records_for_targets(
        records: list[InventoryRecord],
        targets: list[TargetContact],
    ) -> list[InventoryRecord]:
        wxids = {target.wxid for target in targets if target.wxid}
        remark_names = {target.remark_name for target in targets if target.remark_name}
        return [
            record
            for record in records
            if (record.wxid and record.wxid in wxids)
            or (record.remark_name and record.remark_name in remark_names)
        ]

    def _export_named_records(
        self,
        records: list[InventoryRecord],
        filename: str,
    ) -> Path:
        exported_path = self._export_func(
            records,
            self._output_dir,
            base_url=self._settings.weflow.base_url,
            access_token=self._settings.weflow.access_token,
            download_media=self._settings.task.download_media,
            filename=DEFAULT_EXPORT_FILENAME,
        )
        target_path = self._output_dir / filename
        if exported_path == target_path:
            return exported_path
        if target_path.exists():
            target_path.unlink()
        exported_path.replace(target_path)
        return target_path
