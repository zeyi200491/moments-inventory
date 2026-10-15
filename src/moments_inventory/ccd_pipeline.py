from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import sys
from typing import Any, Callable

from moments_inventory.ccd_pipeline_commands import (
    PipelineCommandError,
    PipelinePreflightError,
    PreflightResult,
    run_command,
    validate_preflight,
)
from moments_inventory.ccd_pipeline_state import RunStateStore, sha256_file


class PipelineError(RuntimeError):
    """CCD 全流程停止，状态文件中保留具体阶段。"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _digest(value: Any) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


class PipelineRunner:
    """按本地库存权威源编排 CCD 采集、人工复核与可选云端快照发布。"""

    def __init__(
        self,
        *,
        project_root: str | Path,
        cloud_repo: str | Path,
        config_path: str | Path | None = None,
        cloud_config_path: str | Path | None = None,
        state_store: RunStateStore | None = None,
        adapters: dict[str, Callable] | None = None,
    ):
        self.project_root = Path(project_root).resolve()
        self.cloud_repo = Path(cloud_repo).resolve()
        self.config_path = Path(config_path).resolve() if config_path else None
        self.cloud_config_path = Path(cloud_config_path).resolve() if cloud_config_path else None
        self.state_store = state_store or RunStateStore(self.project_root / "output" / "ccd-pipeline" / "runs")
        self.adapters = adapters or {}

    def _call(self, name: str, context: dict[str, Any], *args: Any) -> dict[str, Any]:
        adapter = self.adapters.get(name)
        if adapter is not None:
            value = adapter(context, *args)
        else:
            value = getattr(self, f"_default_{name}")(context, *args)
        if not isinstance(value, dict):
            raise PipelineError(f"阶段 {name} 未返回有效状态")
        return value

    def _preflight(self) -> PreflightResult:
        adapter = self.adapters.get("preflight")
        if adapter is not None:
            return adapter()
        return validate_preflight(
            self.project_root,
            self.cloud_repo,
            config_path=self.config_path,
            cloud_config_path=self.cloud_config_path,
        )

    @staticmethod
    def _environment(preflight: PreflightResult) -> dict[str, str]:
        return {
            "fingerprint": preflight.environment_fingerprint,
            "project_root": str(preflight.project_root),
            "showcase_config": str(preflight.showcase_config),
            "database": str(preflight.database),
        }

    @staticmethod
    def _target(preflight: PreflightResult) -> dict[str, str]:
        return {
            "fingerprint": preflight.target_fingerprint,
            "cloud_repo": str(preflight.cloud_repo),
            "cloud_config": str(preflight.cloud_config),
            "database_name": preflight.database_name,
            "bucket_name": preflight.bucket_name,
        }

    def run(self) -> dict[str, Any]:
        preflight = self._preflight()
        state = self.state_store.create_run(
            environment=self._environment(preflight),
            target=self._target(preflight),
        )
        context = {"preflight": preflight, "state": state, "project_root": self.project_root}
        self._complete_stage(state, "preflight", {
            "environment_fingerprint": preflight.environment_fingerprint,
            "target_fingerprint": preflight.target_fingerprint,
        })
        self.state_store.save_run(state)
        try:
            for name in ("inventory_refresh", "workbook_merge", "import_review"):
                self._start_stage(state, name)
                self.state_store.save_run(state)
                output = self._call(name, context)
                self._complete_stage(state, name, output)
                context["state"] = state
                self.state_store.save_run(state)
                if name == "import_review":
                    state["current_stage"] = "import_review"
                    state["status"] = "paused"
                    state["pause_reason"] = "等待管理员在展示后台完成导入复核并提交"
                    self.state_store.save_run(state)
                    return state
            return state
        except Exception as exc:
            self._record_failure(state, exc)
            detail = f"；命令诊断：{exc}" if isinstance(exc, PipelineCommandError) else ""
            raise PipelineError(self._diagnostic(state) + detail) from exc

    def status(self, run_id: str) -> dict[str, Any]:
        return self.state_store.load_run(run_id)

    @staticmethod
    def next_action(state: dict[str, Any]) -> str:
        run_id = str(state.get("run_id", ""))
        cloud_repo = str(state.get("target", {}).get("cloud_repo", ""))
        resume = f'python -m moments_inventory.cli ccd-pipeline resume --run-id "{run_id}" --cloud-repo "{cloud_repo}"'
        current = state.get("current_stage")
        if state.get("status") == "published":
            return "流程已发布；按发布手册检查客户页并结束维护窗口。"
        if state.get("status") == "unknown" and current == "cloud_apply":
            return f"先核对原 package 的同步 state、远端 marker 和维护状态；确认可恢复后再运行：{resume} --apply"
        if state.get("status") == "unknown":
            return "结果未知，先人工核查当前阶段的外部副作用；确认前不要自动重试或创建新发布包。"
        if state.get("status") == "failed":
            return "该阶段不能安全续跑；核对本地库存和外部命令结果，修复后新建一次 run。"
        if state.get("status") == "paused" and current == "import_review":
            return f"先在管理页完成同一复核批次并提交，再运行：{resume}"
        if state.get("status") == "succeeded":
            return f"本地检查与远端 dry-run 已完成；若获准发布，再运行：{resume} --apply"
        return f"检查阶段状态后从安全断点续跑：{resume}"

    def resume(self, run_id: str, *, apply: bool = False) -> dict[str, Any]:
        state = self.state_store.load_run(run_id)
        if state["status"] == "published":
            return state
        if state["status"] == "unknown" and state.get("current_stage") != "cloud_apply":
            raise PipelineError("运行结果未知，不能自动重试；请先核对停点和外部命令结果")
        if state["status"] == "failed" and state.get("current_stage") not in {"import_review", "media_export", "cloud_dry_run"}:
            raise PipelineError("该阶段失败后不能安全自动续跑；核对本地库存状态并创建新流程")
        preflight = self._preflight()
        if self._environment(preflight) != state["environment"] or self._target(preflight) != state["target"]:
            raise PipelineError("当前 CCD 数据库或 Cloudflare 目标与原运行不一致，禁止续跑")
        context = {"preflight": preflight, "state": state, "project_root": self.project_root}
        try:
            for stage in state.get("stages", {}).values():
                if stage.get("status") == "succeeded":
                    self._verify_stage_artifacts(stage)
            batch_id = self._review_batch_id(state, context)
            if not batch_id:
                raise PipelineError("复核阶段缺少可核验的批次编号，停止续跑以防重复导入")
            self._start_stage(state, "review_check")
            self.state_store.save_run(state)
            review = self._call("review_check", context, batch_id)
            if review.get("status") == "pending":
                self._complete_stage(state, "review_check", {"status": "pending"})
                state["current_stage"] = "import_review"
                state["status"] = "paused"
                state["pause_reason"] = "后台复核批次仍待处理"
                self.state_store.save_run(state)
                return state
            if review.get("status") != "committed":
                raise PipelineError("原复核批次不存在、已取消或处于不可续跑状态")
            self._complete_stage(state, "review_check", {"status": "committed"})
            self._complete_stage(state, "local_commit_check", {"batch_id": batch_id, "status": "committed"})
            self.state_store.save_run(state)

            for name in ("media_export", "cloud_dry_run"):
                if name in state["stages"] and state["stages"][name]["status"] == "succeeded":
                    self._verify_stage_artifacts(state["stages"][name])
                    continue
                self._start_stage(state, name)
                self.state_store.save_run(state)
                output = self._call(name, context)
                self._complete_stage(state, name, output)
                self.state_store.save_run(state)

            if apply:
                if state["stages"].get("cloud_dry_run", {}).get("status") != "succeeded":
                    raise PipelineError("Cloudflare dry-run 尚未成功，禁止 apply")
                self._start_stage(state, "cloud_apply")
                self.state_store.save_run(state)
                output = self._call("cloud_apply", context)
                expected_manifest = state["stages"]["media_export"]["output"].get("package_hash")
                if (output.get("mode") != "apply" or output.get("maintenance_mode") != "disabled"
                        or output.get("manifest_sha256") != expected_manifest
                        or not isinstance(output.get("remote_d1_validation"), dict)):
                    state["current_stage"] = "cloud_apply"
                    state["status"] = "unknown"
                    state["stages"]["cloud_apply"] = {
                        "status": "unknown", "finished_at": _now(),
                        "error": "同步器未返回可核验的完整发布结果",
                    }
                    self.state_store.save_run(state)
                    return state
                self._complete_stage(state, "cloud_apply", output)
                state["current_stage"] = "published"
                state["status"] = "published"
                self.state_store.save_run(state)
            else:
                state["current_stage"] = "cloud_dry_run"
                state["status"] = "succeeded"
                self.state_store.save_run(state)
            return state
        except Exception as exc:
            self._record_failure(state, exc)
            detail = f"；命令诊断：{exc}" if isinstance(exc, PipelineCommandError) else ""
            raise PipelineError(self._diagnostic(state) + detail) from exc

    def _review_batch_id(self, state: dict[str, Any], context: dict[str, Any]) -> str | None:
        review_stage = state.get("stages", {}).get("import_review", {})
        output = review_stage.get("output", {})
        batch_id = output.get("batch_id") if isinstance(output, dict) else None
        if batch_id:
            return str(batch_id)
        # 若进程在创建批次后、保存 batch_id 前退出，只能恢复唯一的原始待复核批次。
        recovered = self._call("recover_review", context, state["run_id"])
        recovered_id = recovered.get("batch_id")
        if recovered_id:
            review_stage["status"] = "succeeded"
            review_stage["output"] = {"batch_id": str(recovered_id)}
            review_stage["output_hash"] = _digest(review_stage["output"])
            review_stage["finished_at"] = _now()
            state["stages"]["import_review"] = review_stage
            self.state_store.save_run(state)
            return str(recovered_id)
        return None

    @staticmethod
    def _start_stage(state: dict[str, Any], name: str) -> None:
        state["current_stage"] = name
        state["status"] = "running"
        state.setdefault("stages", {})[name] = {"status": "running", "started_at": _now()}

    @staticmethod
    def _complete_stage(state: dict[str, Any], name: str, output: dict[str, Any]) -> None:
        safe_output = json.loads(json.dumps(output, ensure_ascii=False))
        state.setdefault("stages", {})[name] = {
            "status": "succeeded",
            "finished_at": _now(),
            "output": safe_output,
            "output_hash": _digest(safe_output),
        }

    @staticmethod
    def _verify_stage_artifacts(stage: dict[str, Any]) -> None:
        output = stage.get("output", {})
        for artifact in output.get("artifacts", []):
            path = Path(artifact["path"])
            if not path.is_file() or sha256_file(path) != artifact["sha256"]:
                raise PipelineError("已完成阶段的产物发生变化，不能沿用旧运行")

    def _record_failure(self, state: dict[str, Any], exc: Exception) -> None:
        stage = state.get("current_stage", "unknown")
        unknown = (isinstance(exc, PipelineCommandError) and exc.unknown) or stage == "cloud_apply"
        state["status"] = "unknown" if unknown else "failed"
        stage_record = state.setdefault("stages", {}).setdefault(stage, {})
        stage_record.update({
            "status": "unknown" if unknown else "failed",
            "finished_at": _now(),
            "error": f"{type(exc).__name__}：阶段执行未通过安全校验；详情未写入运行状态",
        })
        self.state_store.save_run(state)

    @staticmethod
    def _diagnostic(state: dict[str, Any]) -> str:
        return f"CCD 流程在阶段 {state.get('current_stage')} 停止，状态={state.get('status')}，运行编号={state.get('run_id')}"

    def _default_inventory_refresh(self, context: dict[str, Any]) -> dict[str, Any]:
        if os.name != "nt":
            raise PipelinePreflightError("全量朋友圈刷新入口仅支持 Windows")
        script = self.project_root / "run_full_mode.bat"
        env = os.environ.copy()
        env["MOMENTS_INVENTORY_NONINTERACTIVE"] = "1"
        run_command(["cmd.exe", "/d", "/s", "/c", str(script)], cwd=self.project_root, timeout=4 * 60 * 60, environment=env)
        source = self.project_root / "output" / "全量当前库.xlsx"
        if not source.is_file():
            raise PipelineError("全量刷新未生成 output/全量当前库.xlsx")
        return {"source_path": str(source), "artifacts": [{"path": str(source), "sha256": sha256_file(source)}]}

    def _default_workbook_merge(self, context: dict[str, Any]) -> dict[str, Any]:
        from moments_inventory.showcase import merge_showcase_workbook

        preflight: PreflightResult = context["preflight"]
        source = self.project_root / "output" / "全量当前库.xlsx"
        merge_showcase_workbook(str(source), str(preflight.manual_xlsx))
        return {
            "source_path": str(source),
            "manual_path": str(preflight.manual_xlsx),
            "artifacts": [{"path": str(preflight.manual_xlsx), "sha256": sha256_file(preflight.manual_xlsx)}],
        }

    def _repository(self, context: dict[str, Any]):
        from moments_inventory.showcase_web.repository import SQLiteShowcaseRepository

        repository = SQLiteShowcaseRepository(str(context["preflight"].database))
        repository.initialize()
        return repository

    def _default_import_review(self, context: dict[str, Any]) -> dict[str, Any]:
        from moments_inventory.showcase_web.import_review_service import create_import_review_batch

        manual = context["preflight"].manual_xlsx
        run_id = context["state"]["run_id"]
        content = manual.read_bytes()
        batch = create_import_review_batch(
            self._repository(context),
            content,
            source_scope="default",
            mode="incremental",
            source_path=str(manual),
            source_label=f"CCD pipeline {run_id}",
        )
        return {
            "batch_id": str(batch["batch_id"]),
            "source_hash": hashlib.sha256(content).hexdigest(),
            "admin_url": context["preflight"].admin_url,
        }

    def _default_recover_review(self, context: dict[str, Any], run_id: str) -> dict[str, Any]:
        repository = self._repository(context)
        candidates = repository.find_import_review_batches_by_source_label(f"CCD pipeline {run_id}")
        if len(candidates) > 1:
            raise PipelineError("发现多个同一流程的待复核批次，需人工排查后才能续跑")
        return {"batch_id": str(candidates[0]["batch_id"]), "status": str(candidates[0]["status"])} if candidates else {}

    def _default_review_check(self, context: dict[str, Any], batch_id: str) -> dict[str, Any]:
        from moments_inventory.showcase_web.import_review_service import get_import_review_batch

        batch = get_import_review_batch(self._repository(context), batch_id)
        return {"status": str(batch["status"]), "completed_at": batch.get("completed_at")}

    def _default_media_export(self, context: dict[str, Any]) -> dict[str, Any]:
        preflight: PreflightResult = context["preflight"]
        run_id = context["state"]["run_id"]
        package = self.project_root / "output" / "ccd-pipeline" / "runs" / run_id / "package"
        script = preflight.cloud_repo / "scripts" / "export-local-showcase.py"
        command = [
            sys.executable, str(script), "--showcase-config", str(preflight.showcase_config),
            "--database", str(preflight.database), "--media-root", str(preflight.storage_dir),
            "--media-root", f"sample-images={preflight.sample_images_dir}", "--output", str(package),
        ]
        run_command(command, cwd=preflight.cloud_repo, timeout=4 * 60 * 60)
        ready = package / "READY"
        manifest = package / "manifest.json"
        verification = package / "verification.json"
        if not all(path.is_file() for path in (ready, manifest, verification)):
            raise PipelineError("导出包缺少 READY、manifest 或 verification")
        ready_hash = ready.read_text(encoding="ascii").strip()
        if sha256_file(manifest) != ready_hash:
            raise PipelineError("导出包 READY 与 manifest 摘要不一致")
        manifest_data = json.loads(manifest.read_text(encoding="utf-8"))
        verification_path = package / manifest_data["verification"]["path"]
        if not verification_path.is_file() or sha256_file(verification_path) != manifest_data["verification"]["sha256"]:
            raise PipelineError("导出包媒体验证摘要不匹配")
        return {
            "package_path": str(package),
            "package_hash": ready_hash,
            "artifacts": [
                {"path": str(path), "sha256": sha256_file(path)}
                for path in (ready, manifest, verification_path)
            ],
        }

    def _cloud_command(self, context: dict[str, Any], *, apply: bool) -> dict[str, Any]:
        preflight: PreflightResult = context["preflight"]
        package = context["state"]["stages"]["media_export"]["output"]["package_path"]
        sync_script = preflight.cloud_repo / "scripts" / "sync-cloudflare.mjs"
        command = [
            "node", str(sync_script), "--package", package,
            "--config", str(preflight.cloud_config),
            "--database", preflight.database_name,
            "--bucket", preflight.bucket_name,
        ]
        if apply:
            command.append("--apply")
        result = run_command(command, cwd=preflight.cloud_repo, timeout=4 * 60 * 60)
        try:
            payload = json.loads(result.stdout.strip().splitlines()[-1])
        except (IndexError, json.JSONDecodeError) as exc:
            raise PipelineCommandError("Cloudflare 同步器输出不完整，结果未知", unknown=apply) from exc
        if not isinstance(payload, dict):
            raise PipelineCommandError("Cloudflare 同步器返回结构无效", unknown=apply)
        if apply:
            if payload.get("mode") != "apply" or payload.get("maintenance_mode") != "disabled":
                raise PipelineCommandError("Cloudflare 发布结果缺少维护状态验收，结果未知", unknown=True)
            return payload
        expected_manifest = context["state"]["stages"]["media_export"]["output"].get("package_hash")
        if payload.get("mode") != "dry-run" or payload.get("manifest_sha256") != expected_manifest:
            raise PipelineCommandError("Cloudflare dry-run 未返回预期计划")
        return {"mode": "dry-run", "manifest_sha256": payload.get("manifest_sha256")}

    def _default_cloud_dry_run(self, context: dict[str, Any]) -> dict[str, Any]:
        return self._cloud_command(context, apply=False)

    def _default_cloud_apply(self, context: dict[str, Any]) -> dict[str, Any]:
        return self._cloud_command(context, apply=True)
