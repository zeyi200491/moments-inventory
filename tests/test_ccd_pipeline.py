from __future__ import annotations

import json
import hashlib
import subprocess
import pytest

from moments_inventory.ccd_pipeline_commands import (
    PipelineCommandError,
    PipelinePreflightError,
    run_command,
    validate_preflight,
)
from moments_inventory.ccd_pipeline import PipelineError, PipelineRunner
from moments_inventory.ccd_pipeline_commands import PreflightResult
from moments_inventory.ccd_pipeline_state import RunStateStore


def _valid_roots(tmp_path):
    project = tmp_path / "ccd"
    (project / "src" / "moments_inventory" / "showcase_web").mkdir(parents=True)
    (project / "run_full_mode.bat").write_text("@echo off", encoding="utf-8")
    (project / "pyproject.toml").write_text('[project]\nname="moments-inventory"\n', encoding="utf-8")
    config = project / "config" / "showcase.yaml"
    config.parent.mkdir()
    config.write_text(
        "database: ../data/showcase.db\nstorage_dir: ../storage/showcase_images\n"
        "sample_images_dir: ../output/ccdcpt\nmanual_xlsx: ../manual/stock.xlsx\n"
        "backup_dir: ../backup/showcase\n",
        encoding="utf-8",
    )
    (project / "data").mkdir()
    database = project / "data" / "showcase.db"
    database.write_bytes(b"temporary test db")
    cloud = tmp_path / "cloud"
    (cloud / "scripts").mkdir(parents=True)
    (cloud / "package.json").write_text(json.dumps({"name": "xingxing-ccd-showcase"}), encoding="utf-8")
    for name in ("export-local-showcase.py", "sync-cloudflare.mjs", "verify-deploy-config.mjs"):
        (cloud / "scripts" / name).write_text("", encoding="utf-8")
    (cloud / "wrangler.toml").write_text(
        '[[d1_databases]]\nbinding="DB"\ndatabase_name="db"\n'
        '[[r2_buckets]]\nbinding="IMAGES"\nbucket_name="bucket"\n',
        encoding="utf-8",
    )
    for directory in ("storage/showcase_images", "output/ccdcpt", "manual", "backup/showcase"):
        (project / directory).mkdir(parents=True, exist_ok=True)
    for repository in (project, cloud):
        subprocess.run(["git", "-C", str(repository), "init", "--quiet"], check=True)
        subprocess.run(["git", "-C", str(repository), "config", "user.name", "CCD Pipeline Test"], check=True)
        subprocess.run(["git", "-C", str(repository), "config", "user.email", "ccd-pipeline-test@example.invalid"], check=True)
        subprocess.run(["git", "-C", str(repository), "add", "--all"], check=True)
        subprocess.run(["git", "-C", str(repository), "commit", "--quiet", "-m", "test fixture"], check=True)
    return project, config, cloud, database


def _test_environment_gate(*args, **kwargs):
    return {"environment_id": "temporary-test-only"}


def test_preflight_rejects_invalid_cloud_repo_before_commands(tmp_path):
    project, config, cloud, database = _valid_roots(tmp_path)
    (cloud / "scripts" / "sync-cloudflare.mjs").unlink()
    calls = []

    with pytest.raises(PipelinePreflightError):
        validate_preflight(
            project, cloud, config_path=config,
            command_probe=lambda argv: calls.append(argv), environment_verifier=_test_environment_gate,
        )

    assert calls == []


def test_preflight_rejects_other_cloud_project_even_if_scripts_match(tmp_path):
    project, config, cloud, database = _valid_roots(tmp_path)
    (cloud / "package.json").write_text('{"name":"another-project"}', encoding="utf-8")

    with pytest.raises(PipelinePreflightError):
        validate_preflight(
            project, cloud, config_path=config, require_tools=False,
            environment_verifier=_test_environment_gate,
        )


def test_preflight_returns_explicit_database_and_cloud_target_fingerprints(tmp_path):
    project, config, cloud, database = _valid_roots(tmp_path)

    result = validate_preflight(
        project, cloud, config_path=config, require_tools=False,
        environment_verifier=_test_environment_gate,
    )

    assert result.database == database.resolve()
    assert result.database_name == "db"
    assert result.bucket_name == "bucket"
    assert result.environment_fingerprint
    assert result.target_fingerprint


def test_preflight_requires_formal_environment_gate_before_creating_run_state(tmp_path):
    project, config, cloud, database = _valid_roots(tmp_path)
    gate_calls = []

    def reject_formal_path(config_path, *, entrypoint_root):
        gate_calls.append((config_path, entrypoint_root))
        raise ValueError("非正式工作树")

    with pytest.raises(PipelinePreflightError, match="正式工作树"):
        validate_preflight(
            project, cloud, config_path=config, require_tools=False,
            environment_verifier=reject_formal_path,
        )

    assert gate_calls == [(config.resolve(), project.resolve())]
    assert not (project / "output" / "ccd-pipeline" / "runs").exists()


def test_preflight_fingerprint_changes_when_cloud_target_config_changes(tmp_path):
    project, config, cloud, database = _valid_roots(tmp_path)
    first = validate_preflight(
        project, cloud, config_path=config, require_tools=False,
        environment_verifier=_test_environment_gate,
    )
    cloud_config = cloud / "wrangler.toml"
    cloud_config.write_text(cloud_config.read_text(encoding="utf-8") + "# target changed\n", encoding="utf-8")

    second = validate_preflight(
        project, cloud, config_path=config, require_tools=False,
        environment_verifier=_test_environment_gate,
    )

    assert first.target_fingerprint != second.target_fingerprint


def test_run_command_uses_argument_array_and_sanitizes_secret_output(monkeypatch):
    observed = {}

    def fake_run(argv, **kwargs):
        observed["argv"] = argv
        observed["kwargs"] = kwargs

        class Result:
            returncode = 0
            stdout = "credential is top-secret-value"
            stderr = ""

        return Result()

    monkeypatch.setenv("CCD_PIPELINE_TEST_TOKEN", "top-secret-value")
    result = run_command(["python", "path with spaces.py"], cwd=".", runner=fake_run)

    assert observed["argv"] == ["python", "path with spaces.py"]
    assert observed["kwargs"]["shell"] is False
    assert "top-secret-value" not in result.stdout
    assert "[已脱敏]" in result.stdout


def test_run_command_timeout_is_marked_unknown():
    def fake_run(argv, **kwargs):
        raise __import__("subprocess").TimeoutExpired(argv, 1)

    with pytest.raises(PipelineCommandError) as exc_info:
        run_command(["fake"], cwd=".", timeout=1, runner=fake_run)

    assert exc_info.value.unknown is True


def test_run_stops_at_review_and_does_not_apply_by_default(tmp_path):
    project, config, cloud, database = _valid_roots(tmp_path)
    preflight = PreflightResult(
        project_root=project,
        cloud_repo=cloud,
        showcase_config=config,
        database=database,
        storage_dir=project / "storage" / "showcase_images",
        sample_images_dir=project / "output" / "ccdcpt",
        manual_xlsx=project / "manual" / "stock.xlsx",
        backup_dir=project / "backup" / "showcase",
        cloud_config=cloud / "wrangler.toml",
        database_name="db",
        bucket_name="bucket",
        environment_fingerprint="env-a",
        target_fingerprint="target-a",
    )
    calls = []
    adapters = {
        "preflight": lambda: preflight,
        "inventory_refresh": lambda context: calls.append("inventory_refresh") or {"source_hash": "a"},
        "workbook_merge": lambda context: calls.append("workbook_merge") or {"manual_hash": "b"},
        "import_review": lambda context: calls.append("import_review") or {"batch_id": "batch-1"},
        "review_check": lambda context, batch_id: calls.append("review_check") or {"status": "pending"},
        "media_export": lambda context: calls.append("media_export") or {"package_hash": "c"},
        "cloud_dry_run": lambda context: calls.append("cloud_dry_run") or {"dry_run": True},
        "cloud_apply": lambda context: calls.append("cloud_apply") or {"published": True},
    }
    runner = PipelineRunner(
        project_root=project,
        cloud_repo=cloud,
        state_store=RunStateStore(project / "output" / "ccd-pipeline" / "runs"),
        adapters=adapters,
    )

    result = runner.run()

    assert result["status"] == "paused"
    assert result["stages"]["import_review"]["output"]["batch_id"] == "batch-1"
    assert calls == ["inventory_refresh", "workbook_merge", "import_review"]
    assert "管理页完成同一复核批次" in runner.next_action(result)


def test_resume_waits_for_committed_batch_then_runs_local_dry_run_only(tmp_path):
    project, config, cloud, database = _valid_roots(tmp_path)
    preflight = PreflightResult(
        project_root=project, cloud_repo=cloud, showcase_config=config, database=database,
        storage_dir=project / "storage" / "showcase_images", sample_images_dir=project / "output" / "ccdcpt",
        manual_xlsx=project / "manual" / "stock.xlsx", backup_dir=project / "backup" / "showcase",
        cloud_config=cloud / "wrangler.toml", database_name="db", bucket_name="bucket",
        environment_fingerprint="env-a", target_fingerprint="target-a",
    )
    review_status = {"value": "pending"}
    calls = []
    adapters = {
        "preflight": lambda: preflight,
        "inventory_refresh": lambda context: {"source_hash": "source"},
        "workbook_merge": lambda context: {"manual_hash": "manual"},
        "import_review": lambda context: {"batch_id": "batch-1"},
        "review_check": lambda context, batch_id: {"status": review_status["value"]},
        "media_export": lambda context: calls.append("media_export") or {"package_hash": "pkg"},
        "cloud_dry_run": lambda context: calls.append("cloud_dry_run") or {"mode": "dry-run"},
        "cloud_apply": lambda context: calls.append("cloud_apply") or {"mode": "apply", "maintenance_mode": "disabled"},
    }
    runner = PipelineRunner(
        project_root=project, cloud_repo=cloud,
        state_store=RunStateStore(project / "output" / "ccd-pipeline" / "runs"), adapters=adapters,
    )
    paused = runner.run()

    still_paused = runner.resume(paused["run_id"])

    assert still_paused["status"] == "paused"
    assert calls == []

    review_status["value"] = "committed"
    finished = runner.resume(paused["run_id"])

    assert finished["status"] == "succeeded"
    assert calls == ["media_export", "cloud_dry_run"]


def test_resume_apply_requires_explicit_apply_flag_and_verified_result(tmp_path):
    project, config, cloud, database = _valid_roots(tmp_path)
    preflight = PreflightResult(
        project_root=project, cloud_repo=cloud, showcase_config=config, database=database,
        storage_dir=project / "storage" / "showcase_images", sample_images_dir=project / "output" / "ccdcpt",
        manual_xlsx=project / "manual" / "stock.xlsx", backup_dir=project / "backup" / "showcase",
        cloud_config=cloud / "wrangler.toml", database_name="db", bucket_name="bucket",
        environment_fingerprint="env-a", target_fingerprint="target-a",
    )
    calls = []
    adapters = {
        "preflight": lambda: preflight,
        "inventory_refresh": lambda context: {"source_hash": "source"},
        "workbook_merge": lambda context: {"manual_hash": "manual"},
        "import_review": lambda context: {"batch_id": "batch-2"},
        "review_check": lambda context, batch_id: {"status": "committed"},
        "media_export": lambda context: {"package_hash": "pkg"},
        "cloud_dry_run": lambda context: {"mode": "dry-run"},
        "cloud_apply": lambda context: calls.append("cloud_apply") or {
            "mode": "apply", "maintenance_mode": "disabled", "manifest_sha256": "pkg",
            "remote_d1_validation": {},
        },
    }
    runner = PipelineRunner(
        project_root=project, cloud_repo=cloud,
        state_store=RunStateStore(project / "output" / "ccd-pipeline" / "runs"), adapters=adapters,
    )
    paused = runner.run()
    runner.resume(paused["run_id"])
    assert calls == []

    published = runner.resume(paused["run_id"], apply=True)

    assert published["status"] == "published"
    assert calls == ["cloud_apply"]


def test_resume_rejects_changed_completed_artifact(tmp_path):
    project, config, cloud, database = _valid_roots(tmp_path)
    source = project / "inventory.xlsx"
    source.write_text("version one", encoding="utf-8")
    preflight = PreflightResult(
        project_root=project, cloud_repo=cloud, showcase_config=config, database=database,
        storage_dir=project / "storage" / "showcase_images", sample_images_dir=project / "output" / "ccdcpt",
        manual_xlsx=project / "manual" / "stock.xlsx", backup_dir=project / "backup" / "showcase",
        cloud_config=cloud / "wrangler.toml", database_name="db", bucket_name="bucket",
        environment_fingerprint="env-a", target_fingerprint="target-a",
    )
    calls = []
    adapters = {
        "preflight": lambda: preflight,
        "inventory_refresh": lambda context: {"artifacts": [{"path": str(source), "sha256": hashlib.sha256(source.read_bytes()).hexdigest()}]},
        "workbook_merge": lambda context: {"manual_hash": "manual"},
        "import_review": lambda context: {"batch_id": "batch-stale"},
        "review_check": lambda context, batch_id: {"status": "committed"},
        "media_export": lambda context: calls.append("media_export") or {"package_hash": "pkg"},
        "cloud_dry_run": lambda context: calls.append("cloud_dry_run") or {"mode": "dry-run"},
    }
    runner = PipelineRunner(
        project_root=project, cloud_repo=cloud,
        state_store=RunStateStore(project / "output" / "ccd-pipeline" / "runs"), adapters=adapters,
    )
    paused = runner.run()
    source.write_text("version two", encoding="utf-8")

    with pytest.raises(PipelineError, match="CCD 流程在阶段"):
        runner.resume(paused["run_id"])

    assert calls == []


def test_unknown_cloud_apply_can_resume_only_through_same_apply_adapter(tmp_path):
    project, config, cloud, database = _valid_roots(tmp_path)
    preflight = PreflightResult(
        project_root=project, cloud_repo=cloud, showcase_config=config, database=database,
        storage_dir=project / "storage" / "showcase_images", sample_images_dir=project / "output" / "ccdcpt",
        manual_xlsx=project / "manual" / "stock.xlsx", backup_dir=project / "backup" / "showcase",
        cloud_config=cloud / "wrangler.toml", database_name="db", bucket_name="bucket",
        environment_fingerprint="env-a", target_fingerprint="target-a",
    )
    apply_calls = []

    def apply_adapter(context):
        apply_calls.append("same-run")
        if len(apply_calls) == 1:
            raise PipelineCommandError("timeout", unknown=True)
        return {"mode": "apply", "maintenance_mode": "disabled", "manifest_sha256": "pkg", "remote_d1_validation": {}}

    adapters = {
        "preflight": lambda: preflight,
        "inventory_refresh": lambda context: {},
        "workbook_merge": lambda context: {},
        "import_review": lambda context: {"batch_id": "batch-unknown"},
        "review_check": lambda context, batch_id: {"status": "committed"},
        "media_export": lambda context: {"package_hash": "pkg"},
        "cloud_dry_run": lambda context: {"mode": "dry-run"},
        "cloud_apply": apply_adapter,
    }
    runner = PipelineRunner(
        project_root=project, cloud_repo=cloud,
        state_store=RunStateStore(project / "output" / "ccd-pipeline" / "runs"), adapters=adapters,
    )
    paused = runner.run()
    runner.resume(paused["run_id"])

    with pytest.raises(PipelineError, match="CCD 流程在阶段"):
        runner.resume(paused["run_id"], apply=True)
    assert runner.status(paused["run_id"])["status"] == "unknown"

    recovered = runner.resume(paused["run_id"], apply=True)

    assert recovered["status"] == "published"
    assert apply_calls == ["same-run", "same-run"]
