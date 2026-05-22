from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from moments_inventory.warmup_state import (
    WarmupContactDiagnostics,
    WarmupStepStatus,
)


@dataclass(slots=True)
class WarmupContactResult:
    remark_name: str | None
    success: bool
    reason: str
    diagnostics: WarmupContactDiagnostics | None = None


@dataclass(slots=True)
class WarmupRunResult:
    success_count: int
    failure_count: int
    aborted: bool
    should_export: bool
    contact_results: list[WarmupContactResult] = field(default_factory=list)
    report_path: str | None = None


def _build_step_summary(contact_results: list[WarmupContactResult]) -> dict[str, int]:
    summary: dict[str, int] = {}
    for contact_result in contact_results:
        diagnostics = contact_result.diagnostics
        if diagnostics is None:
            continue
        for step_result in diagnostics.step_results:
            if step_result.status is not WarmupStepStatus.FAILED:
                continue
            summary_key = f"{step_result.step}_failed"
            summary[summary_key] = summary.get(summary_key, 0) + 1
    return summary


def _count_forced_recovery_used(contact_results: list[WarmupContactResult]) -> int:
    return sum(
        1
        for contact_result in contact_results
        if contact_result.diagnostics is not None
        and contact_result.diagnostics.forced_recovery_used
    )


def write_warmup_report(output_dir: str | Path, result: WarmupRunResult) -> Path:
    report_dir = Path(output_dir)
    report_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().strftime("%Y-%m-%d-%H%M%S")
    report_path = report_dir / f"warmup-report-{timestamp}.txt"
    suffix = 1
    while report_path.exists():
        report_path = report_dir / f"warmup-report-{timestamp}-{suffix}.txt"
        suffix += 1

    lines = [
        "寰俊棰勫埛鏂版姤鍛?",
        f"success_count: {result.success_count}",
        f"failure_count: {result.failure_count}",
        f"aborted: {result.aborted}",
        f"should_export: {result.should_export}",
        "",
        "鑱旂郴浜虹粨鏋?",
    ]

    for contact_result in result.contact_results:
        status_text = "鎴愬姛" if contact_result.success else "澶辫触"
        remark_name = contact_result.remark_name or "锛堢己澶卞娉ㄥ悕锛?"
        lines.append(
            f"- remark_name: {remark_name} | status: {status_text} | reason: {contact_result.reason}"
        )

    lines.append("")
    lines.append("step_summary:")
    for step_name, count in sorted(_build_step_summary(result.contact_results).items()):
        lines.append(f"{step_name}: {count}")
    lines.append(
        f"forced_recovery_used: {_count_forced_recovery_used(result.contact_results)}"
    )

    report_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return report_path
