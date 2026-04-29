"""moments_inventory 包初始化。"""

__version__ = "0.1.0"


def main(argv: list[str] | None = None) -> int:
    """包级命令行入口，转发到 CLI 模块。"""
    import sys

    if argv is None:
        argv = sys.argv[1:]
    if not argv:
        return 0

    from moments_inventory.cli import main as cli_main

    return cli_main(argv)
