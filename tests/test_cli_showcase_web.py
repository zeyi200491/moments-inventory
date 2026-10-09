from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import moments_inventory.cli as cli_module
from moments_inventory.showcase_web.auth import verify_password
from moments_inventory.showcase_web.repository import SQLiteShowcaseRepository
from moments_inventory.showcase_web.models import ShowcaseProduct


def test_cli_showcase_db_init_creates_database_without_changing_admin_password(tmp_path: Path) -> None:
    database_path = tmp_path / "showcase.db"
    repo = SQLiteShowcaseRepository(database_path)
    repo.initialize()
    original_hash = repo.get_setting("admin_password_hash")

    result = cli_module.main(
        [
            "showcase-db-init",
            "--database",
            str(database_path),
        ]
    )

    assert result == 0
    assert "showcase_products" in repo.list_table_names()
    assert repo.get_setting("admin_password_hash") == original_hash


def test_cli_admin_password_reset_reads_hidden_password_and_revokes_sessions(monkeypatch, tmp_path: Path) -> None:
    database_path = tmp_path / "showcase.db"
    repo = SQLiteShowcaseRepository(database_path)
    repo.initialize()
    repo.save_admin_session("old-session", "2099-01-01T00:00:00+00:00")
    answers = iter(("new-secret", "new-secret"))
    monkeypatch.setattr(cli_module.getpass, "getpass", lambda prompt: next(answers))

    result = cli_module.main(["showcase-admin-password-reset", "--database", str(database_path)])

    assert result == 0
    assert verify_password("new-secret", repo.get_setting("admin_password_hash") or "")
    assert repo.get_admin_session_expires_at("old-session") is None


def test_admin_password_and_session_revocation_roll_back_together(tmp_path: Path) -> None:
    database_path = tmp_path / "showcase.db"
    repo = SQLiteShowcaseRepository(database_path)
    repo.initialize()
    original_hash = repo.get_setting("admin_password_hash")
    repo.save_admin_session("old-session", "2099-01-01T00:00:00+00:00")
    with repo._get_connection() as conn:
        conn.execute("CREATE TRIGGER reject_admin_session_revoke BEFORE DELETE ON showcase_admin_sessions BEGIN SELECT RAISE(ABORT, 'blocked'); END")

    import pytest
    with pytest.raises(Exception, match="blocked"):
        repo.rotate_admin_password("new-hash")

    assert repo.get_setting("admin_password_hash") == original_hash
    assert repo.get_admin_session_expires_at("old-session") is not None


def test_cli_showcase_db_import_calls_importer(monkeypatch, tmp_path: Path) -> None:
    captured: dict[str, object] = {}
    workbook_path = tmp_path / "客户展示库存.xlsx"
    workbook_path.write_bytes(b"xlsx")
    database_path = tmp_path / "showcase.db"

    def fake_import(workbook: str, repository: SQLiteShowcaseRepository, **kwargs):
        captured["workbook"] = workbook
        captured["database"] = repository._database_path
        from moments_inventory.showcase_web.models import ShowcaseImportResult
        return ShowcaseImportResult("test", 1, 2, 3)

    monkeypatch.setattr(cli_module, "import_showcase_workbook", fake_import)

    result = cli_module.main(
        [
            "showcase-db-import",
            "--yes",
            "--manual-xlsx",
            str(workbook_path),
            "--database",
            str(database_path),
        ]
    )

    assert result == 0
    assert captured == {"workbook": str(workbook_path), "database": str(database_path)}


def test_cli_showcase_server_runs_uvicorn(monkeypatch, tmp_path: Path) -> None:
    captured: dict[str, object] = {}
    app_instance = object()

    def fake_create_showcase_app(**kwargs: object):
        captured["app_kwargs"] = kwargs
        return app_instance

    def fake_run(app: object, *, host: str, port: int, reload: bool) -> None:
        captured["app"] = app
        captured["host"] = host
        captured["port"] = port
        captured["reload"] = reload

    monkeypatch.setattr(cli_module, "create_showcase_app", fake_create_showcase_app)
    monkeypatch.setattr(cli_module, "uvicorn", SimpleNamespace(run=fake_run))

    result = cli_module.main(
        [
            "showcase-server",
            "--database",
            str(tmp_path / "showcase.db"),
            "--storage-dir",
            str(tmp_path / "images"),
            "--sample-images-dir",
            str(tmp_path / "ccdcpt"),
            "--host",
            "127.0.0.1",
            "--port",
            "8899",
        ]
    )

    assert result == 0
    assert captured == {
        "app_kwargs": {
            "database_path": str(tmp_path / "showcase.db"),
            "storage_dir": str(tmp_path / "images"),
            "sample_images_dir": str(tmp_path / "ccdcpt"),
            "admin_login_path": "/admin-xingxing",
            "customer_access_cookie_days": 7,
        },
        "app": app_instance,
        "host": "127.0.0.1",
        "port": 8899,
        "reload": False,
    }


def test_cli_showcase_db_backup_copies_database_and_images(tmp_path: Path) -> None:
    database_path = tmp_path / "showcase.db"
    repo = SQLiteShowcaseRepository(database_path)
    repo.initialize()
    repo.upsert_product(ShowcaseProduct('p', 'model', 'brand', 1, 2, True, False, '', '', '', '', '', '', ''))
    with repo._get_connection() as conn:
        conn.execute("INSERT INTO showcase_product_images(image_id,product_id,image_path,image_type,sort_order,is_cover) VALUES ('i','p','storage/showcase_images/a.jpg','body',0,1)")
    storage_dir = tmp_path / "storage" / "showcase_images"
    storage_dir.mkdir(parents=True)
    (storage_dir / "a.jpg").write_bytes(b"image")
    backup_dir = tmp_path / "backup"

    result = cli_module.main(
        [
            "showcase-db-backup",
            "--database",
            str(database_path),
            "--storage-dir",
            str(storage_dir),
            "--backup-dir",
            str(backup_dir),
        ]
    )

    backups = list(backup_dir.iterdir())
    assert result == 0
    assert len(backups) == 1
    import json
    manifest = json.loads((backups[0] / "manifest.json").read_text(encoding="utf-8"))
    assert (backups[0] / "showcase.db").is_file()
    assert (backups[0] / manifest["media"][0]["file"]).read_bytes() == b"image"


def test_cli_showcase_sample_images_import_calls_importer(monkeypatch, tmp_path: Path) -> None:
    captured: dict[str, object] = {}

    def fake_import(sample_images_dir: str, repository: SQLiteShowcaseRepository):
        captured["sample_images_dir"] = sample_images_dir
        captured["database"] = repository._database_path
        return SimpleNamespace(matched_product_count=2, inserted_image_count=14)

    monkeypatch.setattr(cli_module, "import_sample_images", fake_import)

    result = cli_module.main(
        [
            "showcase-sample-images-import",
            "--sample-images-dir",
            str(tmp_path / "ccdcpt"),
            "--database",
            str(tmp_path / "showcase.db"),
        ]
    )

    assert result == 0
    assert captured == {
        "sample_images_dir": str(tmp_path / "ccdcpt"),
        "database": str(tmp_path / "showcase.db"),
    }


def test_cli_server_uses_config_from_another_cwd(monkeypatch, tmp_path):
    config_dir = tmp_path / 'config'
    config_dir.mkdir()
    config_path = config_dir / 'showcase.yaml'
    config_path.write_text('database: ../data/custom.db\nstorage_dir: ../uploads\nsample_images_dir: ../samples\nserver:\n  host: 127.0.0.2\n  port: 9001\n', encoding='utf-8')
    captured = {}
    monkeypatch.setattr(cli_module, 'create_showcase_app', lambda **kwargs: captured.update(kwargs))
    monkeypatch.setattr(cli_module, 'uvicorn', SimpleNamespace(run=lambda app, **kwargs: captured.update(kwargs)))
    monkeypatch.chdir(tmp_path)
    assert cli_module.main(['showcase-server', '--showcase-config', str(config_path), '--port', '9002']) == 0
    assert captured['database_path'] == str(tmp_path / 'data/custom.db')
    assert captured['sample_images_dir'] == str(tmp_path / 'samples')
    assert captured['host'] == '127.0.0.2'
    assert captured['port'] == 9002


def test_cli_import_preview_then_commit(tmp_path, capsys):
    from moments_inventory.exporter import _write_workbook
    from moments_inventory.showcase import SHOWCASE_HEADERS
    workbook = tmp_path / 'a.xlsx'
    row = dict.fromkeys(SHOWCASE_HEADERS, '')
    row.update({'商品ID': 'p1', '型号': 'ixus80', '成本价': 100, '展示价': 200, '是否展示': '是'})
    _write_workbook(workbook, [SHOWCASE_HEADERS, [row[key] for key in SHOWCASE_HEADERS]])
    db = tmp_path / 'showcase.db'
    preview = tmp_path / 'preview.json'
    assert cli_module.main(['showcase-db-import', '--database', str(db), '--manual-xlsx', str(workbook), '--preview-file', str(preview)]) == 0
    repo = SQLiteShowcaseRepository(db)
    assert repo.list_product_ids() == set()
    assert preview.is_file()
    assert cli_module.main(['showcase-db-import', '--database', str(db), '--commit-preview', str(preview)]) == 0
    assert repo.get_product('p1').display_price == 200
