"""验证本地管理入口只连接 CCD 正式工作树与权威数据路径。"""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

from moments_inventory.showcase_web.config import load_showcase_settings


ENVIRONMENT_ID = "ccd-inventory-showcase"
ALLOWED_CONFIG_NAMES = {"showcase.yaml", "showcase.local.yaml"}


def _common_git_directory() -> Path:
    repository = Path(__file__).resolve().parents[1]
    result = subprocess.run(
        ["git", "-C", str(repository), "rev-parse", "--path-format=absolute", "--git-common-dir"],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    return Path(result.stdout.strip()).resolve()


def _same_path(actual: str | Path, expected: str | Path) -> bool:
    return Path(actual).expanduser().resolve() == Path(expected).expanduser().resolve()


def verify_showcase_config(
    config_path: str | Path,
    *,
    common_git_dir: str | Path | None = None,
    entrypoint_root: str | Path | None = None,
) -> dict[str, str]:
    """仅允许正式工作树入口，并核对权威数据、媒体、库存表与监听路径。"""
    common = Path(common_git_dir).resolve() if common_git_dir is not None else _common_git_directory()
    repository_root = common.parent
    authority_worktree = repository_root / ".worktrees" / ENVIRONMENT_ID
    source_root = Path(entrypoint_root).resolve() if entrypoint_root is not None else Path(__file__).resolve().parents[1]
    if source_root != authority_worktree.resolve():
        raise ValueError(f"CCD 正式入口必须来自正式工作树代码：{authority_worktree}")
    config = Path(config_path).expanduser().resolve()
    if config.parent != (authority_worktree / "config").resolve() or config.name not in ALLOWED_CONFIG_NAMES:
        raise ValueError(f"CCD 正式服务只能使用正式工作树配置：{authority_worktree / 'config' / 'showcase.local.yaml'}")

    settings = load_showcase_settings(config)
    expected_database = authority_worktree / "data" / "showcase.db"
    if not _same_path(settings.database, expected_database):
        raise ValueError(f"配置数据库不是 CCD 权威数据库：{expected_database}")

    expected_storage = authority_worktree / "storage" / "showcase_images"
    if not _same_path(settings.storage_dir, expected_storage):
        raise ValueError(f"配置机身图片目录不是正式目录：{expected_storage}")

    expected_samples = repository_root / "output" / "ccdcpt"
    if not _same_path(settings.sample_images_dir, expected_samples):
        raise ValueError(f"配置样片根目录不是正式目录：{expected_samples}")
    if not Path(settings.sample_images_dir).is_dir():
        raise ValueError(f"正式样片根目录不存在：{settings.sample_images_dir}")

    expected_workbook = authority_worktree / "manual" / "客户展示库存.xlsx"
    if not _same_path(settings.manual_xlsx, expected_workbook):
        raise ValueError(f"配置人工库存表不是正式文件：{expected_workbook}")

    expected_backup = authority_worktree / "backup" / "showcase"
    if not _same_path(settings.backup_dir, expected_backup):
        raise ValueError(f"配置备份目录不是正式目录：{expected_backup}")
    if settings.host != "127.0.0.1" or settings.port != 8899:
        raise ValueError("正式 CCD 服务必须仅监听 127.0.0.1:8899")

    return {
        "environment_id": ENVIRONMENT_ID,
        "config_path": str(config),
        "database_path": str(Path(settings.database).resolve()),
        "storage_dir": str(Path(settings.storage_dir).resolve()),
        "sample_images_dir": str(Path(settings.sample_images_dir).resolve()),
        "manual_xlsx": str(Path(settings.manual_xlsx).resolve()),
        "backup_dir": str(Path(settings.backup_dir).resolve()),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="验证 CCD 正式服务配置和权威数据路径")
    parser.add_argument("--config", required=True, help="CCD showcase 配置路径")
    args = parser.parse_args(argv)
    try:
        result = verify_showcase_config(args.config)
    except Exception as error:
        print(f"[拒绝] CCD 环境校验失败：{error}", file=sys.stderr)
        return 1
    print(
        "[通过] CCD 环境校验："
        f"环境={result['environment_id']}；数据库={result['database_path']}；"
        f"机身图片={result['storage_dir']}；样片={result['sample_images_dir']}；"
        f"库存表={result['manual_xlsx']}；备份目录={result['backup_dir']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
