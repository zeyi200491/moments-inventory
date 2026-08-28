from __future__ import annotations

import argparse
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
from moments_inventory.exporter import export_records, summarize_export_records
from moments_inventory.logging_utils import configure_logging
from moments_inventory.model_catalog import build_model_catalog_index, save_model_catalog_index
from moments_inventory.models import InventoryRecord
from moments_inventory.orchestrator import OrchestratedRunService
from moments_inventory.service import SyncService
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


def main(argv: list[str] | None = None) -> int:
    configure_logging()
    parser = build_parser()
    args = parser.parse_args(argv)

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
