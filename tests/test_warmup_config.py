from pathlib import Path
import shutil
import tempfile
import uuid

import pytest

from moments_inventory.config import ConfigError, load_settings


def _make_temp_root(prefix: str) -> Path:
    return Path(tempfile.mkdtemp(prefix=prefix))


def _write_config_file(
    temp_root: Path,
    warmup_yaml: str = "",
    extra_yaml: str = "",
) -> Path:
    config_file = temp_root / "config.yaml"
    model_file = temp_root / "models.txt"
    model_file.write_text("ixus 95\n", encoding="utf-8")
    config_text = (
        """
weflow:
  base_url: "http://127.0.0.1:5030"
  timeout_seconds: 20
task:
  days: 30
  merge_window_minutes: 10
  output_dir: "./output"
targets:
  - remark_name: "user-a"
    wxid: "wxid_123"
rules:
  required_fields:
    - model
    - price
    - serial_no
paths:
  sqlite_db: "./data/inventory.db"
  model_dict: "MODELS_FILE"
WARMUP_BLOCK
EXTRA_BLOCK
        """
        .replace("MODELS_FILE", str(model_file).replace("\\", "/"))
        .replace("WARMUP_BLOCK", warmup_yaml)
        .replace("EXTRA_BLOCK", extra_yaml)
    )
    config_file.write_text(config_text, encoding="utf-8")
    return config_file


def test_load_settings_reads_warmup_config():
    temp_root = _make_temp_root(f"pytest-warmup-{uuid.uuid4().hex}-")

    try:
        config_file = _write_config_file(
            temp_root,
            """
warmup:
  enabled: true
  start_page: "chat_list"
  search_delay_ms: 900
  open_profile_delay_ms: 1100
  open_timeline_delay_ms: 1300
  timeline_sync_wait_ms: 1700
  scroll_count: 5
  scroll_delay_ms: 950
  back_delay_ms: 700
  max_consecutive_failures: 4
  min_success_count: 2
  auto_export_on_success: false
            """,
        )

        settings = load_settings(config_file)

        assert settings.warmup.enabled is True
        assert settings.warmup.start_page == "chat_list"
        assert settings.warmup.search_delay_ms == 900
        assert settings.warmup.open_profile_delay_ms == 1100
        assert settings.warmup.open_timeline_delay_ms == 1300
        assert settings.warmup.timeline_sync_wait_ms == 1700
        assert settings.warmup.scroll_count == 5
        assert settings.warmup.scroll_delay_ms == 950
        assert settings.warmup.back_delay_ms == 700
        assert settings.warmup.max_consecutive_failures == 4
        assert settings.warmup.min_success_count == 2
        assert settings.warmup.auto_export_on_success is False
        assert settings.warmup.segment_size == 5
        assert settings.warmup.verify_state_after_each_contact is True
        assert settings.warmup.force_recovery_on_reset_failure is True
        assert settings.warmup.log_step_details is True
    finally:
        shutil.rmtree(temp_root, ignore_errors=True)


def test_load_settings_parses_warmup_stability_options():
    temp_root = _make_temp_root(f"pytest-warmup-stability-{uuid.uuid4().hex}-")

    try:
        config_file = _write_config_file(
            temp_root,
            """
warmup:
  enabled: true
  segment_size: 5
  verify_state_after_each_contact: true
  force_recovery_on_reset_failure: true
  log_step_details: true
            """,
        )

        settings = load_settings(config_file)

        assert settings.warmup.segment_size == 5
        assert settings.warmup.verify_state_after_each_contact is True
        assert settings.warmup.force_recovery_on_reset_failure is True
        assert settings.warmup.log_step_details is True
    finally:
        shutil.rmtree(temp_root, ignore_errors=True)


def test_load_settings_rejects_invalid_warmup_start_page():
    temp_root = _make_temp_root(f"pytest-warmup-invalid-{uuid.uuid4().hex}-")

    try:
        config_file = _write_config_file(
            temp_root,
            """
warmup:
  start_page: "timeline"
            """,
        )

        with pytest.raises(ConfigError, match="warmup.start_page"):
            load_settings(config_file)
    finally:
        shutil.rmtree(temp_root, ignore_errors=True)


def test_load_settings_uses_default_warmup_when_section_missing():
    temp_root = _make_temp_root(f"pytest-warmup-default-{uuid.uuid4().hex}-")

    try:
        config_file = _write_config_file(temp_root)

        settings = load_settings(config_file)

        assert settings.warmup.enabled is False
        assert settings.warmup.start_page == "contacts"
        assert settings.warmup.search_delay_ms == 800
        assert settings.warmup.open_profile_delay_ms == 1000
        assert settings.warmup.open_timeline_delay_ms == 1200
        assert settings.warmup.timeline_sync_wait_ms == 1500
        assert settings.warmup.scroll_count == 50
        assert settings.warmup.scroll_delay_ms == 900
        assert settings.warmup.back_delay_ms == 600
        assert settings.warmup.max_consecutive_failures == 3
        assert settings.warmup.min_success_count == 1
        assert settings.warmup.auto_export_on_success is True
        assert settings.warmup.segment_size == 5
        assert settings.warmup.verify_state_after_each_contact is True
        assert settings.warmup.force_recovery_on_reset_failure is True
        assert settings.warmup.log_step_details is True
        assert settings.batch_run.enabled is False
        assert settings.batch_run.batch_size == 25
        assert settings.batch_run.stop_on_batch_failure is True
        assert settings.batch_run.export_only_when_all_batches_succeed is True
        assert settings.batch_run.keep_batch_temp_reports is True
    finally:
        shutil.rmtree(temp_root, ignore_errors=True)


def test_load_settings_reads_batch_run_config():
    temp_root = _make_temp_root(f"pytest-batch-run-{uuid.uuid4().hex}-")

    try:
        config_file = _write_config_file(
            temp_root,
            extra_yaml="""
batch_run:
  enabled: true
  batch_size: 10
  stop_on_batch_failure: false
  export_only_when_all_batches_succeed: false
  keep_batch_temp_reports: false
            """,
        )

        settings = load_settings(config_file)

        assert settings.batch_run.enabled is True
        assert settings.batch_run.batch_size == 10
        assert settings.batch_run.stop_on_batch_failure is False
        assert settings.batch_run.export_only_when_all_batches_succeed is False
        assert settings.batch_run.keep_batch_temp_reports is False
    finally:
        shutil.rmtree(temp_root, ignore_errors=True)
