from __future__ import annotations

import json

import pytest

from moments_inventory.ccd_pipeline_state import (
    PipelineStateError,
    RunStateStore,
    sha256_file,
)


def test_run_state_is_atomically_saved_and_loaded(tmp_path):
    store = RunStateStore(tmp_path / "output" / "ccd-pipeline" / "runs")
    state = store.create_run(environment={"root": str(tmp_path)}, target={"cloud_repo": "repo-a"})

    store.save_run(state)

    assert store.load_run(state["run_id"]) == state
    assert list(store.root.iterdir()) == [store.path_for(state["run_id"])]


def test_file_sha256_matches_content(tmp_path):
    source = tmp_path / "source.bin"
    source.write_bytes(b"ccd pipeline")

    assert sha256_file(source) == "3746cc761a9a776136532dabf9613c6b3610a5acf532ae8758a187947415b491"


def test_state_rejects_secret_field_without_echoing_secret(tmp_path):
    store = RunStateStore(tmp_path)
    state = store.create_run(environment={}, target={})
    state["api_token"] = "do-not-print-this-value"

    with pytest.raises(PipelineStateError) as exc_info:
        store.save_run(state)

    assert "do-not-print-this-value" not in str(exc_info.value)


def test_corrupt_state_is_not_overwritten(tmp_path):
    store = RunStateStore(tmp_path)
    path = store.path_for("run-corrupt")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{broken", encoding="utf-8")

    with pytest.raises(PipelineStateError):
        store.load_run("run-corrupt")

    assert path.read_text(encoding="utf-8") == "{broken"
