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


logger = get_logger(__name__)


class WarmupAdapter(Protocol):
    def prepare(self, start_page: str) -> None:
        ...

    def warmup_contact(self, remark_name: str) -> bool:
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

        for target in self.targets:
            if not target.remark_name:
                failure_count += 1
                consecutive_failures += 1
                contact_results.append(
                    WarmupContactResult(
                        remark_name=target.remark_name,
                        success=False,
                        reason="联系人缺少备注名，无法执行预刷新",
                    )
                )
            else:
                is_success = self.adapter.warmup_contact(target.remark_name)
                if is_success:
                    success_count += 1
                    consecutive_failures = 0
                    contact_results.append(
                        WarmupContactResult(
                            remark_name=target.remark_name,
                            success=True,
                            reason="预刷新成功",
                        )
                    )
                else:
                    failure_count += 1
                    consecutive_failures += 1
                    contact_results.append(
                        WarmupContactResult(
                            remark_name=target.remark_name,
                            success=False,
                            reason="适配器执行预刷新失败",
                        )
                    )

            if consecutive_failures >= self.settings.max_consecutive_failures:
                aborted = True
                break

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
            "预刷新执行完成：成功 %s，失败 %s，中止=%s，建议导出=%s，报告=%s",
            result.success_count,
            result.failure_count,
            result.aborted,
            result.should_export,
            result.report_path,
        )
        return result
