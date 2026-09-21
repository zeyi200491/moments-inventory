"""通过 SQLite backup 保存一致快照，并校验引用媒体后恢复到全新目录。"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil
import sqlite3
from uuid import uuid4


_REFERENCES = (('showcase_products', 'cover_image_path'), ('showcase_product_images', 'image_path'), ('showcase_gallery_images', 'image_path'), ('showcase_sample_group_images', 'image_path'))


def _hash(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def _references(conn):
    paths = set()
    tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    for table, column in _REFERENCES:
        if table in tables:
            paths.update(row[0] for row in conn.execute(f'SELECT DISTINCT {column} FROM {table} WHERE {column} IS NOT NULL AND {column}<>?', ('',)))
    return paths


def _inside(root, relative):
    path = (root / relative).resolve()
    if not path.is_relative_to(root.resolve()):
        raise ValueError(f'媒体路径超出目录：{relative}')
    return path


def _source_media(value, database, storage, samples):
    normalized = value.replace('\\', '/')
    if normalized.startswith('/storage/showcase_images/'):
        normalized = normalized[1:]
    if normalized.startswith('/sample-images/'):
        normalized = normalized[1:]
    if normalized.startswith('storage/showcase_images/'):
        return _inside(storage, normalized[len('storage/showcase_images/'):])
    if normalized.startswith('sample-images/'):
        return _inside(samples, normalized[len('sample-images/'):])
    candidate = Path(value)
    if candidate.is_absolute():
        return candidate
    return _inside(database.parent.parent, normalized)


def backup_showcase(database_path, storage_dir, sample_images_dir, backup_dir):
    database = Path(database_path).resolve()
    if not database.is_file():
        raise FileNotFoundError(database)
    destination = Path(backup_dir) / (datetime.now().strftime('%Y%m%d-%H%M%S') + '-' + uuid4().hex[:8])
    destination.mkdir(parents=True, exist_ok=False)
    snapshot = destination / 'showcase.db'
    with sqlite3.connect(database.as_uri() + '?mode=ro', uri=True) as source:
        with sqlite3.connect(snapshot) as target:
            source.backup(target)
            if target.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
                raise ValueError('数据库完整性校验失败')
            references = _references(target)
            tables = {row[0] for row in target.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            counts = {table: target.execute(f'SELECT count(*) FROM {table}').fetchone()[0] for table, _ in _REFERENCES if table in tables}
    media = []
    for index, reference in enumerate(sorted(references)):
        original = _source_media(reference, database, Path(storage_dir), Path(sample_images_dir))
        if not original.is_file():
            raise FileNotFoundError(f'数据库引用媒体不存在：{reference}')
        relative = f'media/{index:08d}{original.suffix}'
        copied = destination / relative
        copied.parent.mkdir(exist_ok=True)
        before = original.stat()
        shutil.copy2(original, copied)
        checksum = _hash(copied)
        after = original.stat()
        if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns) or _hash(original) != checksum:
            raise ValueError(f'备份期间媒体发生改变：{reference}')
        media.append(dict(reference=reference, file=relative, sha256=checksum, size=copied.stat().st_size))
    manifest = dict(version=1, created_at=datetime.now(timezone.utc).isoformat(), database_sha256=_hash(snapshot), counts=counts, media=media)
    (destination / 'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
    return destination


def restore_showcase(snapshot_dir, destination_dir):
    source = Path(snapshot_dir).resolve()
    destination = Path(destination_dir).resolve()
    if destination.exists():
        raise FileExistsError('恢复目标必须是不存在的新目录')
    manifest = json.loads((source / 'manifest.json').read_text(encoding='utf-8'))
    if manifest.get('version') != 1 or _hash(source / 'showcase.db') != manifest['database_sha256']:
        raise ValueError('备份数据库哈希或清单版本无效')
    for item in manifest['media']:
        path = _inside(source, item['file'])
        if not path.is_file() or path.stat().st_size != item['size'] or _hash(path) != item['sha256']:
            raise ValueError(f'媒体校验失败：{item["reference"]}')
    with sqlite3.connect((source / 'showcase.db').as_uri() + '?mode=ro', uri=True) as conn:
        if conn.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
            raise ValueError('备份数据库完整性校验失败')
        if _references(conn) != {item['reference'] for item in manifest['media']}:
            raise ValueError('备份媒体引用清单不完整')
        for table, count in manifest['counts'].items():
            if table not in {value[0] for value in _REFERENCES} or conn.execute(f'SELECT count(*) FROM {table}').fetchone()[0] != count:
                raise ValueError('备份记录数量不一致')
    (destination / 'data').mkdir(parents=True, exist_ok=False)
    restored_database = destination / 'data/showcase.db'
    shutil.copy2(source / 'showcase.db', restored_database)
    with sqlite3.connect(restored_database) as conn:
        for item in manifest['media']:
            original = item['reference'].replace('\\', '/').lstrip('/')
            relative = original if original.startswith(('storage/showcase_images/', 'sample-images/')) else 'storage/showcase_images/restored/' + Path(item['file']).name
            target = _inside(destination, relative)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(_inside(source, item['file']), target)
            if _hash(target) != item['sha256']:
                raise ValueError('恢复媒体哈希校验失败')
            for table, column in _REFERENCES:
                if table not in manifest['counts'] or relative == item['reference']:
                    continue
                conn.execute(f'UPDATE {table} SET {column}=? WHERE {column}=?', (relative, item['reference']))
        if conn.execute('PRAGMA integrity_check').fetchone()[0] != 'ok' or any(not _inside(destination, value).is_file() for value in _references(conn)):
            raise ValueError('恢复后的数据库或媒体引用校验失败')
    (destination / 'sample-images').mkdir(exist_ok=True)
    (destination / 'config').mkdir(exist_ok=True)
    (destination / 'config/showcase.yaml').write_text('database: ../data/showcase.db\nstorage_dir: ../storage/showcase_images\nsample_images_dir: ../sample-images\nserver:\n  host: 127.0.0.1\n  port: 8899\n', encoding='utf-8')
    (destination / 'restore-report.json').write_text(json.dumps(dict(integrity='ok', media_count=len(manifest['media']), counts=manifest['counts']), indent=2), encoding='utf-8')
    return destination
