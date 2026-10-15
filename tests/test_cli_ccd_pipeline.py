from __future__ import annotations

import pytest

from moments_inventory import cli


def test_ccd_pipeline_help_has_run_status_resume(capsys):
    with pytest.raises(SystemExit) as exc_info:
        cli.build_parser().parse_args(["ccd-pipeline", "--help"])

    assert exc_info.value.code == 0
    output = capsys.readouterr().out
    assert "run" in output
    assert "status" in output
    assert "resume" in output


def test_run_and_resume_require_explicit_cloud_repo():
    parser = cli.build_parser()

    with pytest.raises(SystemExit):
        parser.parse_args(["ccd-pipeline", "run"])
    with pytest.raises(SystemExit):
        parser.parse_args(["ccd-pipeline", "resume", "--run-id", "run-a"])


def test_pipeline_apply_flag_is_opt_in():
    parser = cli.build_parser()
    run_args = parser.parse_args(["ccd-pipeline", "run", "--cloud-repo", "cloud"])
    resume_args = parser.parse_args([
        "ccd-pipeline", "resume", "--run-id", "run-a", "--cloud-repo", "cloud",
    ])

    assert run_args.apply is False
    assert resume_args.apply is False
