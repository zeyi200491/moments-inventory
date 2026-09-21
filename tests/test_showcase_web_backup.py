import json
import sqlite3
from pathlib import Path
import pytest
from moments_inventory.showcase_web.repository import SQLiteShowcaseRepository
from moments_inventory.showcase_web.models import ShowcaseProduct
from moments_inventory.showcase_web.backup_service import backup_showcase, restore_showcase


def test_backup_captures_wal_and_referenced_media_then_restores(tmp_path):
    database = tmp_path / 'data/showcase.db'
    repo = SQLiteShowcaseRepository(database)
    repo.initialize()
    repo.upsert_product(ShowcaseProduct('p', 'model', 'brand', 1, 2, True, False, '', '', '', '', '', '', ''))
    storage = tmp_path / 'uploads'
    storage.mkdir()
    (storage / 'a.jpg').write_bytes(b'image')
    with repo._get_connection() as conn:
        conn.execute('PRAGMA journal_mode=WAL')
        conn.execute("INSERT INTO showcase_product_images(image_id,product_id,image_path,image_type,sort_order,is_cover) VALUES ('i','p','storage/showcase_images/a.jpg','body',0,1)")
    snapshot = backup_showcase(database, storage, tmp_path / 'samples', tmp_path / 'backups')
    manifest = json.loads((snapshot / 'manifest.json').read_text(encoding='utf-8'))
    assert len(manifest['media']) == 1
    restored = restore_showcase(snapshot, tmp_path / 'restored')
    with sqlite3.connect(restored / 'data/showcase.db') as conn:
        image_path = conn.execute('SELECT image_path FROM showcase_product_images').fetchone()[0]
        assert conn.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'
    assert (restored / image_path).read_bytes() == b'image'
    with pytest.raises(FileExistsError):
        restore_showcase(snapshot, restored)


def test_restore_rejects_corrupt_media_before_creating_destination(tmp_path):
    database = tmp_path / 'data/showcase.db'
    repo = SQLiteShowcaseRepository(database)
    repo.initialize()
    repo.upsert_product(ShowcaseProduct('p', 'model', 'brand', 1, 2, True, False, '', '', '', '', '', '', ''))
    storage = tmp_path / 'uploads'
    storage.mkdir()
    (storage / 'a.jpg').write_bytes(b'image')
    with repo._get_connection() as conn:
        conn.execute("INSERT INTO showcase_product_images(image_id,product_id,image_path,image_type,sort_order,is_cover) VALUES ('i','p','storage/showcase_images/a.jpg','body',0,1)")
    snapshot = backup_showcase(database, storage, tmp_path / 'samples', tmp_path / 'backups')
    media = json.loads((snapshot / 'manifest.json').read_text(encoding='utf-8'))['media'][0]
    (snapshot / media['file']).write_bytes(b'corrupt')
    with pytest.raises(ValueError):
        restore_showcase(snapshot, tmp_path / 'restored')
    assert not (tmp_path / 'restored').exists()


def test_backup_includes_shared_sample_groups_and_missing_media_fails(tmp_path):
    database = tmp_path / 'data/showcase.db'
    repo = SQLiteShowcaseRepository(database)
    repo.initialize()
    samples = tmp_path / 'samples'
    samples.mkdir()
    with repo._get_connection() as conn:
        conn.execute("INSERT INTO showcase_sample_groups(group_key) VALUES ('canon')")
        conn.execute("INSERT INTO showcase_sample_group_images(image_id,group_key,image_path,sort_order) VALUES ('sample','canon','sample-images/a.jpg',0)")
    with pytest.raises(FileNotFoundError):
        backup_showcase(database, tmp_path / 'uploads', samples, tmp_path / 'backups')
    assert not list((tmp_path / 'backups').glob('*/manifest.json'))
    (samples / 'a.jpg').write_bytes(b'sample')
    snapshot = backup_showcase(database, tmp_path / 'uploads', samples, tmp_path / 'backups')
    restored = restore_showcase(snapshot, tmp_path / 'restored')
    assert (restored / 'sample-images/a.jpg').read_bytes() == b'sample'
    with sqlite3.connect(restored / 'data/showcase.db') as conn:
        assert conn.execute('SELECT image_path FROM showcase_sample_group_images').fetchone()[0] == 'sample-images/a.jpg'
