from __future__ import annotations

import argparse
from dataclasses import asdict
import getpass
import json
import os
from pathlib import Path
import sys

import uvicorn

from moments_inventory.ai_kefu.app import create_app
from moments_inventory.ai_kefu.indexing import split_document_to_chunks
from moments_inventory.ai_kefu.loaders import load_text_document
from moments_inventory.ai_kefu.models import KnowledgeTier
from moments_inventory.ai_kefu.products import import_products_from_xlsx
from moments_inventory.ai_kefu.settings import load_ai_kefu_settings
from moments_inventory.ai_kefu.storage import SQLiteKefuRepository
from moments_inventory.batch_run import BatchRunService
from moments_inventory.config import Settings, load_settings
from moments_inventory.exporter import export_records, summarize_export_records
from moments_inventory.logging_utils import configure_logging
from moments_inventory.model_catalog import build_model_catalog_index, save_model_catalog_index
from moments_inventory.models import InventoryRecord
from moments_inventory.orchestrator import OrchestratedRunService
from moments_inventory.service import SyncService
from moments_inventory.showcase import build_showcase_site, merge_showcase_workbook
from moments_inventory.showcase_web.app import create_showcase_app
from moments_inventory.showcase_web.auth import hash_password
from moments_inventory.showcase_web.config import load_showcase_settings
from moments_inventory.showcase_web.importer import import_showcase_workbook, preview_showcase_workbook
from moments_inventory.showcase_web.import_service import ImportPreview, commit_import
from moments_inventory.showcase_web.backup_service import backup_showcase, restore_showcase
from moments_inventory.showcase_web.repository import SQLiteShowcaseRepository
from moments_inventory.showcase_web.sample_images import import_sample_images
from moments_inventory.wechat_ui_adapter import (
    PywinautoWechatController,
    WeChatWarmupAdapter,
)
from moments_inventory.wechat_warmup import WarmupRunner


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Moments inventory tooling")
    parser.add_argument("--config", default="config/config.yaml", help="config file path")
    subparsers = parser.add_subparsers(dest="command", required=True)

    sync_parser = subparsers.add_parser("sync", help="sync moments into sqlite")
    sync_parser.add_argument("--export", action="store_true", help="export after sync")

    model_index_parser = subparsers.add_parser(
        "build-model-index",
        help="build camera model catalog index from Excel",
    )
    model_index_parser.add_argument("--excel", required=True, help="model catalog Excel path")
    model_index_parser.add_argument(
        "--output",
        default="data/model_catalog_index.json",
        help="output JSON index path",
    )

    subparsers.add_parser("export", help="export current records to Excel")

    warmup_parser = subparsers.add_parser("warmup", help="run WeChat warmup flow")
    warmup_parser.add_argument(
        "--export",
        action="store_true",
        help="sync and export after warmup if warmup passes the threshold",
    )

    batch_parser = subparsers.add_parser(
        "batch-run",
        help="run warmup and staged sync in batches",
    )
    batch_parser.add_argument(
        "--export",
        action="store_true",
        help="export current Excel after the full batch run succeeds",
    )

    orchestrated_parser = subparsers.add_parser(
        "orchestrated-run",
        help="run priority-only or full staged orchestration",
    )
    orchestrated_parser.add_argument(
        "--mode",
        choices=["priority_only", "full"],
        help="override orchestrator.mode from config",
    )
    orchestrated_parser.add_argument(
        "--resume",
        action="store_true",
        help="resume from progress.json in the configured output directory",
    )

    kefu_parser = subparsers.add_parser("kefu-dev", help="start local AI kefu backend")
    kefu_parser.add_argument("--host", default="127.0.0.1", help="bind host")
    kefu_parser.add_argument("--port", type=int, default=8787, help="bind port")
    kefu_parser.add_argument("--reload", action="store_true", help="enable auto reload")
    kefu_parser.add_argument(
        "--ai-kefu-config",
        default="config/ai_kefu.yaml",
        help="AI kefu config file path",
    )

    import_products_parser = subparsers.add_parser(
        "import-products",
        help="import current inventory Excel into AI kefu product storage",
    )
    import_products_parser.add_argument("--xlsx", required=True, help="Excel path")
    import_products_parser.add_argument(
        "--ai-kefu-config",
        default="config/ai_kefu.yaml",
        help="AI kefu config file path",
    )

    showcase_merge_parser = subparsers.add_parser(
        "showcase-merge",
        help="merge raw inventory Excel into manual showcase Excel",
    )
    showcase_merge_parser.add_argument("--source-xlsx", default="output/全量当前库.xlsx")
    showcase_merge_parser.add_argument("--manual-xlsx", default="manual/客户展示库存.xlsx")

    showcase_build_parser = subparsers.add_parser(
        "showcase-build",
        help="build static CCD showcase site from manual showcase Excel",
    )
    showcase_build_parser.add_argument("--manual-xlsx", default="manual/客户展示库存.xlsx")
    showcase_build_parser.add_argument("--sample-assets-dir", default="showcase_assets")
    showcase_build_parser.add_argument("--output-dir", default="site_dist")
    showcase_build_parser.add_argument(
        "--access-password",
        default=None,
        help="encrypt showcase product data with this customer access password",
    )

    showcase_db_init_parser = subparsers.add_parser(
        "showcase-db-init",
        help="initialize SQLite database for CCD showcase",
    )
    showcase_db_init_parser.add_argument("--database")
    showcase_admin_password_parser = subparsers.add_parser(
        "showcase-admin-password-reset",
        help="interactively reset CCD showcase admin password",
    )
    showcase_admin_password_parser.add_argument("--database")

    showcase_db_import_parser = subparsers.add_parser(
        "showcase-db-import",
        help="import manual showcase Excel into SQLite database",
    )
    showcase_db_import_parser.add_argument("--manual-xlsx")
    showcase_db_import_parser.add_argument("--database")
    showcase_db_import_parser.add_argument("--mode", choices=("incremental", "full"), default="incremental")
    showcase_db_import_parser.add_argument("--scope", default="default")
    showcase_db_import_parser.add_argument("--complete", action="store_true")
    showcase_db_import_parser.add_argument("--max-missing-fraction", type=float, default=0.3)
    showcase_db_import_parser.add_argument("--preview-file")
    showcase_db_import_parser.add_argument("--commit-preview")
    showcase_db_import_parser.add_argument("--yes", action="store_true", help="确认立即提交校验后的导入")

    showcase_server_parser = subparsers.add_parser(
        "showcase-server",
        help="start local CCD showcase server",
    )
    showcase_server_parser.add_argument("--database")
    showcase_server_parser.add_argument("--storage-dir")
    showcase_server_parser.add_argument("--sample-images-dir")
    showcase_server_parser.add_argument("--host")
    showcase_server_parser.add_argument("--port", type=int)

    showcase_sample_images_import_parser = subparsers.add_parser(
        "showcase-sample-images-import",
        help="import CCD sample image paths into SQLite database",
    )
    showcase_sample_images_import_parser.add_argument("--sample-images-dir")
    showcase_sample_images_import_parser.add_argument("--database")

    showcase_backup_parser = subparsers.add_parser(
        "showcase-db-backup",
        help="backup CCD showcase database and uploaded images",
    )
    showcase_backup_parser.add_argument("--database")
    showcase_backup_parser.add_argument("--storage-dir")
    showcase_backup_parser.add_argument("--backup-dir")
    showcase_backup_parser.add_argument("--sample-images-dir")
    showcase_restore_parser = subparsers.add_parser("showcase-db-restore", help="校验备份并恢复到全新目录")
    showcase_restore_parser.add_argument("--snapshot", required=True)
    showcase_restore_parser.add_argument("--destination", required=True)
    for showcase_parser in (
        showcase_db_init_parser, showcase_admin_password_parser, showcase_db_import_parser, showcase_server_parser,
        showcase_sample_images_import_parser, showcase_backup_parser,
    ):
        showcase_parser.add_argument("--showcase-config", help="展示系统配置文件路径")

    pipeline_parser = subparsers.add_parser(
        "ccd-pipeline",
        help="编排 CCD 库存刷新、人工复核、发布包检查与 Cloudflare 快照同步",
    )
    pipeline_commands = pipeline_parser.add_subparsers(dest="pipeline_command", required=True)
    pipeline_run = pipeline_commands.add_parser("run", help="开始一次新的 CCD 更新流程")
    pipeline_run.add_argument("--cloud-repo", required=True, help="Cloudflare 展示仓库的明确路径")
    pipeline_run.add_argument("--showcase-config", help="CCD 展示 SQLite 与媒体配置文件")
    pipeline_run.add_argument("--cloud-config", help="仓库内 Wrangler 配置文件，默认 wrangler.toml")
    pipeline_run.add_argument("--apply", action="store_true", help="记录发布意图；复核完成后仍需 resume --apply")
    pipeline_status = pipeline_commands.add_parser("status", help="只读查看某次运行的阶段状态")
    pipeline_status.add_argument("--run-id", required=True)
    pipeline_resume = pipeline_commands.add_parser("resume", help="从人工复核或安全断点继续流程")
    pipeline_resume.add_argument("--run-id", required=True)
    pipeline_resume.add_argument("--cloud-repo", required=True, help="与原运行相同的 Cloudflare 仓库路径")
    pipeline_resume.add_argument("--showcase-config", help="与原运行相同的 CCD 展示配置文件")
    pipeline_resume.add_argument("--cloud-config", help="与原运行相同的 Wrangler 配置文件")
    pipeline_resume.add_argument("--apply", action="store_true", help="明确授权本次续跑写入 Cloudflare D1/R2")

    import_knowledge_parser = subparsers.add_parser(
        "import-knowledge",
        help="import text knowledge into AI kefu knowledge storage",
    )
    import_knowledge_parser.add_argument("--file", required=True, help="knowledge file path")
    import_knowledge_parser.add_argument("--category", required=True, help="knowledge category")
    import_knowledge_parser.add_argument("--tier", required=True, help="knowledge tier")
    import_knowledge_parser.add_argument("--tags", default="", help="comma-separated tags")
    import_knowledge_parser.add_argument(
        "--ai-kefu-config",
        default="config/ai_kefu.yaml",
        help="AI kefu config file path",
    )
    return parser


def _export_loaded_records(records: list[object], settings: Settings) -> None:
    export_records(
        records,
        settings.task.output_dir,
        base_url=settings.weflow.base_url,
        access_token=settings.weflow.access_token,
        download_media=settings.task.download_media,
    )


def _run_export(service: SyncService, settings: Settings) -> None:
    _export_loaded_records(service.load_records(), settings)


def _format_lifecycle_export_stats(records: list[InventoryRecord]) -> str:
    summary = summarize_export_records(records)
    return "\n".join(
        [
            f"候选记录: {summary.candidate_count}",
            f"展示记录: {summary.current_count}",
            f"复核记录: {summary.review_count}",
            f"疑似降价重发: {summary.price_drop_repost_count}",
            f"疑似已售/下架: {summary.sold_or_delisted_count}",
            f"未匹配型号: {summary.unmatched_model_count}",
            f"低置信型号: {summary.low_confidence_model_count}",
            f"平替/对比文案: {summary.reference_model_count}",
            f"型号冲突: {summary.model_conflict_count}",
        ]
    )


def _print_lifecycle_export_stats(records: list[InventoryRecord]) -> None:
    print(_format_lifecycle_export_stats(records))


def _build_batch_warmup_runner(settings: Settings):
    if not settings.warmup.enabled:
        return None

    controller = PywinautoWechatController()
    adapter = WeChatWarmupAdapter(settings=settings.warmup, controller=controller)

    def warmup_batch(batch_targets):
        runner = WarmupRunner(
            settings=settings.warmup,
            targets=batch_targets,
            adapter=adapter,
            output_dir=settings.task.output_dir,
        )
        result = runner.run()
        if result.aborted:
            raise RuntimeError("batch warmup aborted")
        if (
            settings.batch_run.stop_on_batch_failure
            and result.failure_count > 0
            and not result.should_export
        ):
            raise RuntimeError("batch warmup reported failures")

    return warmup_batch


def _parse_knowledge_tags(raw_tags: str) -> list[str]:
    normalized: list[str] = []
    seen: set[str] = set()
    for raw_tag in raw_tags.split(","):
        tag = raw_tag.strip()
        if not tag or tag in seen:
            continue
        seen.add(tag)
        normalized.append(tag)
    return normalized


def _import_knowledge(
    *,
    file_path: str,
    category: str,
    tier: KnowledgeTier,
    tags: list[str],
    ai_kefu_config: str,
) -> None:
    settings = load_ai_kefu_settings(ai_kefu_config)
    repository = SQLiteKefuRepository(settings.database_path)
    source_path = Path(file_path)
    content = load_text_document(source_path)
    chunks = split_document_to_chunks(
        source_name=source_path.name,
        category=category,
        text=content,
        chunk_size=settings.retrieval.chunk_size,
        chunk_overlap=settings.retrieval.chunk_overlap,
        knowledge_tier=tier,
    )
    for chunk in chunks:
        chunk.tags = list(tags)
    repository.delete_knowledge_chunks_by_source(source_path.name)
    repository.save_knowledge_chunks(chunks)


def _initialize_showcase_database(database_path: str) -> None:
    repository = SQLiteShowcaseRepository(database_path)
    repository.initialize()


def _backup_showcase_database(
    *,
    database_path: str,
    storage_dir: str,
    backup_dir: str,
) -> Path:
    settings = load_showcase_settings()
    return backup_showcase(database_path, storage_dir, settings.sample_images_dir, backup_dir)


def main(argv: list[str] | None = None) -> int:
    configure_logging()
    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        if hasattr(args, "showcase_config"):
            showcase_config_path = args.showcase_config
            if args.command == "ccd-pipeline" and not showcase_config_path:
                local_config = Path.cwd() / "config" / "showcase.local.yaml"
                showcase_config_path = str(
                    local_config if local_config.is_file() else Path.cwd() / "config" / "showcase.yaml"
                )
                args.showcase_config = showcase_config_path
            settings = load_showcase_settings(
                showcase_config_path,
                **{key: getattr(args, key, None) for key in ("database", "storage_dir", "sample_images_dir", "manual_xlsx", "backup_dir", "host", "port")},
            )
            for key, value in vars(settings).items():
                setattr(args, key, value)
    except (OSError, ValueError) as exc:
        if args.command == "ccd-pipeline":
            print(f"CCD 流程配置预检失败：{type(exc).__name__}", file=sys.stderr)
            return 2
        raise

    if args.command == "build-model-index":
        index = build_model_catalog_index(args.excel)
        save_model_catalog_index(index, args.output)
        return 0

    if args.command == "kefu-dev":
        if args.reload:
            os.environ["MOMENTS_AI_KEFU_CONFIG_PATH"] = args.ai_kefu_config
            uvicorn.run(
                "moments_inventory.ai_kefu.app:create_app_from_env",
                host=args.host,
                port=args.port,
                reload=True,
                factory=True,
            )
        else:
            uvicorn.run(
                create_app(args.ai_kefu_config),
                host=args.host,
                port=args.port,
                reload=False,
            )
        return 0

    if args.command == "import-products":
        settings = load_ai_kefu_settings(args.ai_kefu_config)
        repository = SQLiteKefuRepository(settings.database_path)
        repository.replace_products(import_products_from_xlsx(args.xlsx))
        return 0

    if args.command == "showcase-merge":
        merge_showcase_workbook(args.source_xlsx, args.manual_xlsx)
        return 0

    if args.command == "showcase-build":
        build_showcase_site(
            args.manual_xlsx,
            args.sample_assets_dir,
            args.output_dir,
            access_password=args.access_password,
        )
        return 0

    if args.command == "showcase-db-init":
        _initialize_showcase_database(args.database)
        return 0

    if args.command == "showcase-admin-password-reset":
        repository = SQLiteShowcaseRepository(args.database)
        repository.initialize()
        password = getpass.getpass("请输入新的管理员口令：")
        confirmation = getpass.getpass("请再次输入管理员口令：")
        if not password:
            raise ValueError("管理员口令不能为空")
        if password != confirmation:
            raise ValueError("两次输入的管理员口令不一致")
        repository.rotate_admin_password(hash_password(password))
        return 0

    if args.command == "showcase-db-import":
        repository = SQLiteShowcaseRepository(args.database)
        repository.initialize()
        if args.commit_preview:
            saved = json.loads(Path(args.commit_preview).read_text(encoding="utf-8"))
            if saved["database"] != str(Path(args.database).resolve()):
                raise ValueError("预览属于其他数据库")
            result = commit_import(repository, ImportPreview(**saved["preview"]))
            print(json.dumps(asdict(result), ensure_ascii=False))
        elif args.yes:
            result = import_showcase_workbook(args.manual_xlsx, repository, mode=args.mode, scope=args.scope, complete=args.complete, max_missing_fraction=args.max_missing_fraction)
            print(json.dumps(asdict(result), ensure_ascii=False))
        else:
            preview = preview_showcase_workbook(args.manual_xlsx, repository, mode=args.mode, scope=args.scope, complete=args.complete, max_missing_fraction=args.max_missing_fraction)
            summary = {"inserted_count": preview.inserted_count, "updated_count": preview.updated_count, "missing_count": preview.missing_count, "fingerprint": preview.fingerprint, "mode": preview.mode, "scope": preview.scope}
            print(json.dumps(summary, ensure_ascii=False))
            if args.preview_file:
                Path(args.preview_file).write_text(json.dumps({"database": str(Path(args.database).resolve()), "preview": asdict(preview)}, ensure_ascii=False, indent=2), encoding="utf-8")
            print("仅生成预览。确认后使用 --commit-preview 文件，或 --yes 重新校验后提交。")
        return 0

    if args.command == "showcase-server":
        uvicorn.run(
            create_showcase_app(
                database_path=args.database,
                storage_dir=args.storage_dir,
                sample_images_dir=args.sample_images_dir,
                admin_login_path=args.admin_login_path,
                customer_access_cookie_days=args.customer_access_cookie_days,
            ),
            host=args.host,
            port=args.port,
            reload=False,
        )
        return 0

    if args.command == "showcase-sample-images-import":
        repository = SQLiteShowcaseRepository(args.database)
        repository.initialize()
        import_sample_images(args.sample_images_dir, repository)
        return 0

    if args.command == "showcase-db-backup":
        destination = backup_showcase(args.database, args.storage_dir, args.sample_images_dir, args.backup_dir)
        print(str(destination))
        return 0

    if args.command == "showcase-db-restore":
        print(str(restore_showcase(args.snapshot, args.destination)))
        return 0

    if args.command == "ccd-pipeline":
        from moments_inventory.ccd_pipeline import PipelineError, PipelineRunner
        from moments_inventory.ccd_pipeline_commands import PipelinePreflightError
        from moments_inventory.ccd_pipeline_state import PipelineStateError

        project_root = Path.cwd().resolve()
        try:
            if args.pipeline_command == "status":
                runner = PipelineRunner(
                    project_root=project_root,
                    cloud_repo=project_root,
                )
                state = runner.status(args.run_id)
            else:
                runner = PipelineRunner(
                    project_root=project_root,
                    cloud_repo=args.cloud_repo,
                    config_path=args.showcase_config,
                    cloud_config_path=args.cloud_config,
                )
                if args.pipeline_command == "run":
                    state = runner.run()
                    if args.apply:
                        state["apply_requested"] = True
                        runner.state_store.save_run(state)
                else:
                    state = runner.resume(args.run_id, apply=args.apply)
        except (PipelineError, PipelinePreflightError, PipelineStateError, OSError, ValueError) as exc:
            print(f"CCD 流程未继续：{exc}", file=sys.stderr)
            return 2
        print(json.dumps({
            "run_id": state.get("run_id"),
            "status": state.get("status"),
            "current_stage": state.get("current_stage"),
            "stages": {name: value.get("status") for name, value in state.get("stages", {}).items()},
            "next_action": runner.next_action(state),
        }, ensure_ascii=False, indent=2))
        if state.get("status") == "paused" and state.get("current_stage") == "import_review":
            review_output = state["stages"]["import_review"]["output"]
            print(f"请在管理页逐条完成复核后续跑：{review_output.get('admin_url', '本机 CCD 管理页面')}\n复核批次：{review_output['batch_id']}")
        return 0

    if args.command == "import-knowledge":
        _import_knowledge(
            file_path=args.file,
            category=args.category,
            tier=args.tier,
            tags=_parse_knowledge_tags(args.tags),
            ai_kefu_config=args.ai_kefu_config,
        )
        return 0

    settings = load_settings(args.config)

    if args.command == "sync":
        service = SyncService(settings)
        service.sync()
        if args.export:
            _run_export(service, settings)
        return 0

    if args.command == "export":
        service = SyncService(settings)
        _run_export(service, settings)
        return 0

    if args.command == "warmup":
        if not settings.warmup.enabled:
            parser.error("warmup is disabled; set warmup.enabled first")

        controller = PywinautoWechatController()
        adapter = WeChatWarmupAdapter(settings=settings.warmup, controller=controller)
        runner = WarmupRunner(
            settings=settings.warmup,
            targets=settings.targets,
            adapter=adapter,
            output_dir=settings.task.output_dir,
        )
        warmup_result = runner.run()

        if args.export and warmup_result.should_export:
            service = SyncService(settings)
            service.sync()
            _run_export(service, settings)
        return 0

    if args.command == "batch-run":
        if not settings.batch_run.enabled:
            parser.error("batch_run is disabled; set batch_run.enabled first")

        service = BatchRunService(
            settings,
            warmup_runner=_build_batch_warmup_runner(settings),
        )
        records = service.run()
        if args.export:
            _export_loaded_records(records, settings)
            _print_lifecycle_export_stats(records)
        return 0

    if args.command == "orchestrated-run":
        if not settings.orchestrator.enabled:
            parser.error("orchestrator is disabled; set orchestrator.enabled first")

        service = OrchestratedRunService(
            settings,
            warmup_runner=_build_batch_warmup_runner(settings),
        )
        service.run(mode=args.mode, resume=args.resume)
        return 0

    return 1


if __name__ == "__main__":
    raise SystemExit(main())
