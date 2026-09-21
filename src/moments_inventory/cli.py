from __future__ import annotations

import argparse
from dataclasses import asdict
import json
import os
from pathlib import Path

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
from moments_inventory.exporter import export_records
from moments_inventory.logging_utils import configure_logging
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
    showcase_db_init_parser.add_argument(
        "--admin-password",
        default=None,
        help="set or reset admin password",
    )

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
        showcase_db_init_parser, showcase_db_import_parser, showcase_server_parser,
        showcase_sample_images_import_parser, showcase_backup_parser,
    ):
        showcase_parser.add_argument("--showcase-config", help="展示系统配置文件路径")

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
        if settings.batch_run.stop_on_batch_failure and result.failure_count > 0:
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


def _initialize_showcase_database(database_path: str, admin_password: str | None) -> None:
    repository = SQLiteShowcaseRepository(database_path)
    repository.initialize()
    if admin_password:
        repository.set_setting("admin_password_hash", hash_password(admin_password))


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

    if hasattr(args, "showcase_config"):
        settings = load_showcase_settings(
            args.showcase_config,
            **{key: getattr(args, key, None) for key in ("database", "storage_dir", "sample_images_dir", "manual_xlsx", "backup_dir", "host", "port")},
        )
        for key, value in vars(settings).items():
            setattr(args, key, value)

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
        _initialize_showcase_database(args.database, args.admin_password)
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
