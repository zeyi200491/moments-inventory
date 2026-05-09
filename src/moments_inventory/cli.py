from __future__ import annotations

import argparse
from pathlib import Path

import uvicorn

from moments_inventory.ai_kefu.app import create_app
from moments_inventory.ai_kefu.indexing import split_document_to_chunks
from moments_inventory.ai_kefu.loaders import load_text_document
from moments_inventory.ai_kefu.models import KnowledgeTier
from moments_inventory.ai_kefu.products import import_products_from_xlsx
from moments_inventory.ai_kefu.settings import load_ai_kefu_settings
from moments_inventory.ai_kefu.storage import SQLiteKefuRepository
from moments_inventory.config import Settings, load_settings
from moments_inventory.exporter import export_records
from moments_inventory.logging_utils import configure_logging
from moments_inventory.service import SyncService
from moments_inventory.wechat_ui_adapter import (
    PywinautoKeyboardController,
    WeChatWarmupAdapter,
)
from moments_inventory.wechat_warmup import WarmupRunner


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="微信朋友圈 CCD 商品库工具")
    parser.add_argument("--config", default="config/config.yaml", help="配置文件路径")
    subparsers = parser.add_subparsers(dest="command", required=True)

    sync_parser = subparsers.add_parser("sync", help="抓取朋友圈并更新数据库")
    sync_parser.add_argument("--export", action="store_true", help="同步后直接导出 Excel")

    subparsers.add_parser("export", help="从数据库导出 Excel")

    warmup_parser = subparsers.add_parser("warmup", help="执行微信预热流程")
    warmup_parser.add_argument(
        "--export",
        action="store_true",
        help="预热达到导出条件后继续同步并导出 Excel",
    )

    kefu_parser = subparsers.add_parser("kefu-dev", help="启动 AI 客服本地开发后端")
    kefu_parser.add_argument("--host", default="127.0.0.1", help="本地绑定地址")
    kefu_parser.add_argument("--port", type=int, default=8787, help="本地端口")
    kefu_parser.add_argument(
        "--ai-kefu-config",
        default="config/ai_kefu.yaml",
        help="AI 客服配置文件路径",
    )

    import_products_parser = subparsers.add_parser(
        "import-products",
        help="导入当前在售 Excel 到 AI 客服商品库",
    )
    import_products_parser.add_argument("--xlsx", required=True, help="当前在售 Excel 路径")
    import_products_parser.add_argument(
        "--ai-kefu-config",
        default="config/ai_kefu.yaml",
        help="AI 客服配置文件路径",
    )

    import_knowledge_parser = subparsers.add_parser(
        "import-knowledge",
        help="导入文本知识到 AI 客服知识库",
    )
    import_knowledge_parser.add_argument("--file", required=True, help="知识文件路径")
    import_knowledge_parser.add_argument("--category", required=True, help="知识分类")
    import_knowledge_parser.add_argument("--tier", required=True, help="知识层级")
    import_knowledge_parser.add_argument("--tags", default="", help="逗号分隔标签")
    import_knowledge_parser.add_argument(
        "--ai-kefu-config",
        default="config/ai_kefu.yaml",
        help="AI 客服配置文件路径",
    )
    return parser


def _run_export(service: SyncService, settings: Settings) -> None:
    export_records(
        service.load_records(),
        settings.task.output_dir,
        base_url=settings.weflow.base_url,
        access_token=settings.weflow.access_token,
    )


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

    if args.command == "kefu-dev":
        uvicorn.run(create_app(args.ai_kefu_config), host=args.host, port=args.port)
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
            parser.error("warmup 未启用，请先在配置中启用 warmup.enabled")

        controller = PywinautoKeyboardController()
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

    return 1


if __name__ == "__main__":
    raise SystemExit(main())
