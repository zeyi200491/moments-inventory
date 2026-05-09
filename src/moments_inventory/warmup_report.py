from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path


@dataclass(slots=True)
class WarmupContactResult:
    remark_name: str | None
    success: bool
    reason: str


@dataclass(slots=True)
class WarmupRunResult:
    success_count: int
    failure_count: int
    aborted: bool
    should_export: bool
    contact_results: list[WarmupContactResult] = field(default_factory=list)
    report_path: str | None = None


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
        "微信预刷新报告",
        f"success_count: {result.success_count}",
        f"failure_count: {result.failure_count}",
        f"aborted: {result.aborted}",
        f"should_export: {result.should_export}",
        "",
        "联系人结果:",
    ]

    for contact_result in result.contact_results:
        status_text = "成功" if contact_result.success else "失败"
        remark_name = contact_result.remark_name or "（缺失备注名）"
        lines.append(
            f"- remark_name: {remark_name} | status: {status_text} | reason: {contact_result.reason}"
        )

    report_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return report_path
