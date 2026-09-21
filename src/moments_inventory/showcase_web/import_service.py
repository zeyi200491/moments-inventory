"""库存导入的校验快照与原子提交。"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
from uuid import uuid4

from moments_inventory.showcase_web.models import ShowcaseImportResult


@dataclass(frozen=True)
class ImportPreview:
    records: tuple[dict, ...]
    versions: dict[str, int]
    missing_ids: tuple[str, ...]
    source_path: str
    fingerprint: str
    mode: str
    scope: str
    existing_result: ShowcaseImportResult | None = None

    @property
    def inserted_count(self):
        return sum(record['product_id'] not in self.versions for record in self.records)

    @property
    def updated_count(self):
        return len(self.records) - self.inserted_count

    @property
    def missing_count(self):
        return len(self.missing_ids)


def _find_result(conn, fingerprint, scope, mode):
    row = conn.execute('SELECT import_id, inserted_count, updated_count, missing_count FROM showcase_import_logs WHERE source_fingerprint=? AND scope=? AND mode=? AND status=?', (fingerprint, scope, mode, 'committed')).fetchone()
    return ShowcaseImportResult(*row) if row else None


def _rows(conn):
    cursor = conn.execute('SELECT * FROM showcase_products')
    keys = [description[0] for description in cursor.description]
    return {row[0]: dict(zip(keys, row)) for row in cursor.fetchall()}


def prepare_import(repository, records, *, content, source_path, mode, scope, complete, max_missing_fraction):
    if mode not in ('incremental', 'full') or not scope.strip():
        raise ValueError('导入模式或来源范围无效')
    if not 0 <= max_missing_fraction <= 1:
        raise ValueError('缺失复核阈值必须介于0和1')
    if mode == 'full' and (not complete or not records):
        raise ValueError('全量导入需要完整性声明且不能是空表')
    fingerprint = hashlib.sha256(content).hexdigest()
    with repository._lock:
        conn = repository._get_connection()
        existing_result = _find_result(conn, fingerprint, scope, mode)
        existing = _rows(conn)
    seen = {record['product_id'] for record in records}
    if any(existing[key]['source_scope'] != scope for key in seen & existing.keys()):
        raise ValueError('商品ID已属于其他来源范围')
    scoped = {key for key, value in existing.items() if value['source_scope'] == scope}
    missing = scoped - seen if mode == 'full' else set()
    if missing and len(missing) / len(scoped) > max_missing_fraction and existing_result is None:
        raise ValueError('全量来源减少超过阈值，需要复核后明确调整阈值')
    targets = (seen & existing.keys()) | missing
    return ImportPreview(tuple(records), {key: existing[key]['row_version'] for key in targets}, tuple(sorted(missing)), source_path, fingerprint, mode, scope, existing_result)


def commit_import(repository, preview: ImportPreview):
    now = datetime.now(timezone.utc).isoformat()
    with repository._lock:
        with repository._get_connection() as conn:
            conn.execute('BEGIN IMMEDIATE')
            reused = _find_result(conn, preview.fingerprint, preview.scope, preview.mode)
            if reused:
                return reused
            current = _rows(conn)
            seen = {record['product_id'] for record in preview.records}
            if preview.mode == 'full':
                current_scope = {key for key, value in current.items() if value['source_scope'] == preview.scope}
                if current_scope != (set(preview.versions) | (seen & current.keys())):
                    raise ValueError('导入预览已过期：来源范围内商品发生变化')
            for product_id in seen | set(preview.missing_ids):
                expected = preview.versions.get(product_id)
                actual = current.get(product_id)
                if (actual is None) != (expected is None) or (actual is not None and actual['row_version'] != expected):
                    raise ValueError(f'导入版本冲突：{product_id}')
            import_id = uuid4().hex
            for record in preview.records:
                product_id = record['product_id']
                previous = current.get(product_id)
                if previous:
                    values = dict(previous)
                else:
                    values = dict(public_id=uuid4().hex, row_version=0, created_at=now, sold=False, short_selling_point='', recommend_tags='', price_override=None, copy_override=None, visibility_override=None, override_origin='', last_verified_at='')
                values.update(record)
                if previous and not record['cover_image_path']:
                    values['cover_image_path'] = previous['cover_image_path']
                values.update(source_scope=preview.scope, source_available=True, last_seen_at=now, review_state='', updated_at=now, last_seen_import_id=import_id)
                values['display_price'] = values['price_override'] if values['price_override'] is not None else values['source_display_price']
                values['display_copy'] = values['copy_override'] if values['copy_override'] is not None else values['source_display_copy']
                values['visible'] = bool(values['visibility_override'] if values['visibility_override'] is not None else values['source_visible']) and not values['sold']
                columns = tuple(values)
                if previous:
                    updates = [name for name in columns if name not in ('product_id', 'row_version')]
                    conn.execute('UPDATE showcase_products SET ' + ','.join(f'{name}=?' for name in updates) + ', row_version=row_version+1 WHERE product_id=?', [values[name] for name in updates] + [product_id])
                else:
                    conn.execute('INSERT INTO showcase_products (' + ','.join(columns) + ') VALUES (' + ','.join('?' for _ in columns) + ')', [values[name] for name in columns])
                if record['cover_image_path']:
                    conn.execute("INSERT INTO showcase_product_images (image_id,product_id,image_path,image_type,sort_order,is_cover) VALUES (?,?,?,'body',0,1) ON CONFLICT(image_id) DO UPDATE SET image_path=excluded.image_path", (f'{product_id}|body|0', product_id, record['cover_image_path']))
            for product_id in preview.missing_ids:
                conn.execute("UPDATE showcase_products SET source_available=0, review_state='missing', updated_at=?, row_version=row_version+1 WHERE product_id=?", (now, product_id))
            result = ShowcaseImportResult(import_id, preview.inserted_count, preview.updated_count, preview.missing_count)
            conn.execute('INSERT INTO showcase_import_logs (import_id,source_path,imported_at,inserted_count,updated_count,missing_count,mode,scope,status,started_at,committed_at,source_fingerprint) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)', (import_id, preview.source_path, now, result.inserted_count, result.updated_count, result.missing_count, preview.mode, preview.scope, 'committed', now, now, preview.fingerprint))
            conn.execute("INSERT INTO showcase_settings(setting_key,setting_value) VALUES ('inventory_updated_at',?) ON CONFLICT(setting_key) DO UPDATE SET setting_value=excluded.setting_value", (now,))
            conn.execute("INSERT INTO showcase_settings(setting_key,setting_value) VALUES ('catalog_revision','1') ON CONFLICT(setting_key) DO UPDATE SET setting_value=CAST(setting_value AS INTEGER)+1")
            return result
