from __future__ import annotations

import argparse

from moments_inventory.config import load_settings
from moments_inventory.exporter import export_records
from moments_inventory.logging_utils import configure_logging
from moments_inventory.service import SyncService


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="微信朋友圈 CCD 商品库工具")
    parser.add_argument("--config", default="config/config.yaml", help="配置文件路径")
    subparsers = parser.add_subparsers(dest="command", required=True)

    sync_parser = subparsers.add_parser("sync", help="抓取朋友圈并更新数据库")
    sync_parser.add_argument("--export", action="store_true", help="同步后直接导出 Excel")

    subparsers.add_parser("export", help="从数据库导出 Excel")
    return parser


def main(argv: list[str] | None = None) -> int:
    configure_logging()
    parser = build_parser()
    args = parser.parse_args(argv)
    settings = load_settings(args.config)
    service = SyncService(settings)

    if args.command == "sync":
        service.sync()
        if args.export:
            export_records(
                service.load_records(),
                settings.task.output_dir,
                base_url=settings.weflow.base_url,
                access_token=settings.weflow.access_token,
            )
        return 0

    if args.command == "export":
        export_records(
            service.load_records(),
            settings.task.output_dir,
            base_url=settings.weflow.base_url,
            access_token=settings.weflow.access_token,
        )
        return 0

    return 1


if __name__ == "__main__":
    raise SystemExit(main())
