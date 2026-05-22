from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from moments_inventory.config import WarmupSettings
from moments_inventory.logging_utils import get_logger
from moments_inventory.models import TargetContact
from moments_inventory.warmup_report import (
    WarmupContactResult,
    WarmupRunResult,
    write_warmup_report,
)
from moments_inventory.warmup_state import WarmupContactDiagnostics, WarmupPageState


logger = get_logger(__name__)


class WarmupAdapter(Protocol):
    def prepare(self, start_page: str) -> None:
        ...

    def warmup_contact(self, remark_name: str) -> WarmupContactDiagnostics:
        ...


@dataclass(slots=True)
class WarmupRunner:
    settings: WarmupSettings
    targets: list[TargetContact]
    adapter: WarmupAdapter
    output_dir: str | Path

    def run(self) -> WarmupRunResult:
        self.adapter.prepare(self.settings.start_page)

        contact_results: list[WarmupContactResult] = []
        success_count = 0
        failure_count = 0
        consecutive_failures = 0
        aborted = False

        for segment_index, segment_targets in enumerate(self._iter_segments()):
            for target in segment_targets:
                if not target.remark_name:
                    failure_count += 1
                    consecutive_failures += 1
                    contact_results.append(
                        WarmupContactResult(
                            remark_name=target.remark_name,
                            success=False,
                            reason="鑱旂郴浜虹己灏戝娉ㄥ悕锛屾棤娉曟墽琛岄鍒锋柊",
                        )
                    )
                else:
                    diagnostics = self.adapter.warmup_contact(target.remark_name)
                    is_success = self._is_successful_diagnostics(diagnostics)
                    if is_success:
                        success_count += 1
                        consecutive_failures = 0
                        contact_results.append(
                            WarmupContactResult(
                                remark_name=target.remark_name,
                                success=True,
                                reason="棰勫埛鏂版垚鍔?",
                                diagnostics=diagnostics,
                            )
                        )
                    else:
                        failure_count += 1
                        consecutive_failures += 1
                        contact_results.append(
                            WarmupContactResult(
                                remark_name=target.remark_name,
                                success=False,
                                reason="閫傞厤鍣ㄦ墽琛岄鍒锋柊澶辫触",
                                diagnostics=diagnostics,
                            )
                        )

                if consecutive_failures >= self.settings.max_consecutive_failures:
                    aborted = True
                    break

            if aborted:
                break

            self._best_effort_segment_recovery(segment_index)

        should_export = (
            (not aborted)
            and success_count >= self.settings.min_success_count
            and self.settings.auto_export_on_success
        )

        result = WarmupRunResult(
            success_count=success_count,
            failure_count=failure_count,
            aborted=aborted,
            should_export=should_export,
            contact_results=contact_results,
        )
        report_path = write_warmup_report(self.output_dir, result)
        result.report_path = str(report_path)

        logger.info(
            "棰勫埛鏂版墽琛屽畬鎴愶細鎴愬姛 %s锛屽け璐?%s锛屼腑姝?%s锛屽缓璁鍑?%s锛屾姤鍛?%s",
            result.success_count,
            result.failure_count,
            result.aborted,
            result.should_export,
            result.report_path,
        )
        return result

    def _iter_segments(self) -> list[list[TargetContact]]:
        size = max(1, self.settings.segment_size)
        return [
            self.targets[index : index + size]
            for index in range(0, len(self.targets), size)
        ]

    def _best_effort_segment_recovery(self, segment_index: int) -> None:
        try:
            self.adapter.prepare(self.settings.start_page)
        except Exception:
            logger.warning("绗?%s 娈垫仮澶嶅け璐?", segment_index + 1, exc_info=True)

    @staticmethod
    def _is_successful_diagnostics(diagnostics: WarmupContactDiagnostics) -> bool:
        return (
            diagnostics.search_ok
            and diagnostics.select_contact_ok
            and diagnostics.profile_ok
            and diagnostics.timeline_open_ok
            and diagnostics.timeline_scroll_ok
            and diagnostics.reset_ok
            and diagnostics.final_page_state is WarmupPageState.SEARCH_READY
        )
