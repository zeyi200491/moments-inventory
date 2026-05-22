from moments_inventory.warmup_state import (
    WarmupContactDiagnostics,
    WarmupPageState,
    WarmupStepResult,
    WarmupStepStatus,
)


def test_warmup_contact_diagnostics_defaults() -> None:
    diagnostics = WarmupContactDiagnostics(remark_name="白得一批")

    assert diagnostics.remark_name == "白得一批"
    assert diagnostics.final_page_state is WarmupPageState.UNKNOWN
    assert diagnostics.search_ok is False
    assert diagnostics.timeline_open_ok is False
    assert diagnostics.reset_ok is False
    assert diagnostics.step_results == []


def test_warmup_step_result_records_status_and_reason() -> None:
    result = WarmupStepResult(
        step="open_timeline",
        status=WarmupStepStatus.FAILED,
        reason="timeline popup not found",
    )

    assert result.step == "open_timeline"
    assert result.status is WarmupStepStatus.FAILED
    assert result.reason == "timeline popup not found"
