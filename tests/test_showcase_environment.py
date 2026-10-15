from pathlib import Path

import pytest

from scripts.verify_showcase_environment import verify_showcase_config


def _authority_tree(tmp_path: Path) -> tuple[Path, Path]:
    repository = tmp_path / "AIkefu"
    common_git_dir = repository / ".git"
    authority = repository / ".worktrees" / "ccd-inventory-showcase"
    config_dir = authority / "config"
    config_dir.mkdir(parents=True)
    (authority / "data").mkdir()
    (authority / "storage").mkdir()
    (repository / "output" / "ccdcpt").mkdir(parents=True)
    config = config_dir / "showcase.local.yaml"
    config.write_text(
        "database: ../data/showcase.db\n"
        "storage_dir: ../storage/showcase_images\n"
        f"sample_images_dir: {repository / 'output' / 'ccdcpt'}\n",
        encoding="utf-8",
    )
    return common_git_dir, config


def test_authority_check_accepts_canonical_worktree_and_reports_resolved_paths(tmp_path: Path) -> None:
    common_git_dir, config = _authority_tree(tmp_path)

    result = verify_showcase_config(
        config,
        common_git_dir=common_git_dir,
        entrypoint_root=config.parents[1],
    )

    assert result["environment_id"] == "ccd-inventory-showcase"
    assert result["database_path"] == str(config.parents[1] / "data" / "showcase.db")
    assert result["sample_images_dir"] == str(common_git_dir.parent / "output" / "ccdcpt")


def test_authority_check_rejects_root_checkout_config_even_when_paths_look_valid(tmp_path: Path) -> None:
    common_git_dir, canonical_config = _authority_tree(tmp_path)
    root_config = common_git_dir.parent / "config" / "showcase.yaml"
    root_config.parent.mkdir()
    root_config.write_text(canonical_config.read_text(encoding="utf-8"), encoding="utf-8")

    with pytest.raises(ValueError, match="正式工作树"):
        verify_showcase_config(
            root_config,
            common_git_dir=common_git_dir,
            entrypoint_root=canonical_config.parents[1],
        )


def test_authority_check_rejects_config_that_points_at_another_database(tmp_path: Path) -> None:
    common_git_dir, config = _authority_tree(tmp_path)
    config.write_text("database: ../data/development.db\n", encoding="utf-8")

    with pytest.raises(ValueError, match="权威数据库"):
        verify_showcase_config(
            config,
            common_git_dir=common_git_dir,
            entrypoint_root=config.parents[1],
        )


def test_authority_check_rejects_development_code_pointed_at_authority_config(tmp_path: Path) -> None:
    common_git_dir, config = _authority_tree(tmp_path)
    development_root = common_git_dir.parent / ".worktrees" / "ccd-phase1-correctness"
    development_root.mkdir(parents=True)

    with pytest.raises(ValueError, match="正式工作树代码"):
        verify_showcase_config(
            config,
            common_git_dir=common_git_dir,
            entrypoint_root=development_root,
        )


def test_authority_check_rejects_a_different_sample_media_root(tmp_path: Path) -> None:
    common_git_dir, config = _authority_tree(tmp_path)
    config.write_text(
        "database: ../data/showcase.db\n"
        "storage_dir: ../storage/showcase_images\n"
        "sample_images_dir: ../sample-images\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="样片根目录"):
        verify_showcase_config(
            config,
            common_git_dir=common_git_dir,
            entrypoint_root=config.parents[1],
        )


def test_authority_check_rejects_a_different_manual_workbook(tmp_path: Path) -> None:
    common_git_dir, config = _authority_tree(tmp_path)
    config.write_text(
        "database: ../data/showcase.db\n"
        "storage_dir: ../storage/showcase_images\n"
        f"sample_images_dir: {common_git_dir.parent / 'output' / 'ccdcpt'}\n"
        "manual_xlsx: ../manual/development.xlsx\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="人工库存表"):
        verify_showcase_config(
            config,
            common_git_dir=common_git_dir,
            entrypoint_root=config.parents[1],
        )


def test_authority_check_rejects_nonstandard_local_server_binding(tmp_path: Path) -> None:
    common_git_dir, config = _authority_tree(tmp_path)
    config.write_text(
        "database: ../data/showcase.db\n"
        "storage_dir: ../storage/showcase_images\n"
        f"sample_images_dir: {common_git_dir.parent / 'output' / 'ccdcpt'}\n"
        "server:\n  host: 0.0.0.0\n  port: 8900\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="127.0.0.1:8899"):
        verify_showcase_config(
            config,
            common_git_dir=common_git_dir,
            entrypoint_root=config.parents[1],
        )
