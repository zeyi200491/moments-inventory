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
    row = conn.execute(
        """SELECT import_id, inserted_count, updated_count, missing_count, source_fingerprint
        FROM showcase_import_logs
        WHERE scope=? AND mode=? AND status=?
        ORDER BY rowid DESC LIMIT 1""",
        (scope, mode, 'committed'),
    ).fetchone()
    return ShowcaseImportResult(*row[:4]) if row and row[4] == fingerprint else None


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
    existing_by_source_key = {}
    source_key_owners = {}
    for product_id, row in existing.items():
        source_key = str(row.get('source_product_key') or '')
        if not source_key:
            continue
        key = (row['source_scope'], source_key)
        if key in existing_by_source_key:
            raise ValueError('数据库中存在重复稳定商品身份，需要先复核')
        existing_by_source_key[key] = product_id
        source_key_owners[source_key] = row['source_scope']

    normalized_records = []
    seen_source_keys = set()
    seen_product_ids = set()
    for record in records:
        normalized = dict(record)
        source_key = str(normalized.get('source_product_key') or '')
        if source_key:
            if source_key in seen_source_keys:
                raise ValueError(f'导入文件中的稳定商品身份重复：{source_key}')
            seen_source_keys.add(source_key)
            other_scope_owner = source_key_owners.get(source_key)
            if other_scope_owner is not None and other_scope_owner != scope:
                raise ValueError('稳定商品身份已属于其他来源范围，拒绝跨来源合并')
            existing_id = existing_by_source_key.get((scope, source_key))
            if existing_id is not None:
                normalized['product_id'] = existing_id
        product_id = normalized['product_id']
        if product_id in seen_product_ids:
            raise ValueError(f'多个导入行对应同一商品身份：{product_id}')
        seen_product_ids.add(product_id)
        normalized_records.append(normalized)

    records = normalized_records
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
                values.update({
                    name: value
                    for name, value in record.items()
                    if name == 'source_product_key' and value
                    or name not in ('source_product_key', 'body_image_paths')
                })
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
                image_paths = record.get('body_image_paths') or []
                if image_paths:
                    conn.execute(
                        """delete from showcase_product_images
                        where product_id=? and image_type='body'
                          and (source='inventory_import'
                            or (image_id=? and source='legacy_unknown'))""",
                        (product_id, f'{product_id}|body|0'),
                    )
                    conn.executemany(
                        """insert into showcase_product_images
                        (image_id,product_id,image_path,image_type,sort_order,is_cover,source)
                        values (?,?,?,'body',?,?, 'inventory_import')
                        on conflict(image_id) do update set
                          image_path=excluded.image_path,image_type=excluded.image_type,
                          sort_order=excluded.sort_order,is_cover=excluded.is_cover,
                          source=excluded.source
                        where showcase_product_images.product_id=excluded.product_id
                          and showcase_product_images.source in ('inventory_import','legacy_unknown')""",
                        [
                            (f'{product_id}|body|{index}', product_id, image_path, index, int(index == 0))
                            for index, image_path in enumerate(image_paths)
                        ],
                    )
            for product_id in preview.missing_ids:
                conn.execute(
                    """UPDATE showcase_products
                       SET source_available=0,
                           review_state=CASE WHEN review_state='missing_reviewed'
                                             THEN review_state ELSE 'missing' END,
                           updated_at=?, row_version=row_version+1
                       WHERE product_id=?""",
                    (now, product_id),
                )
            result = ShowcaseImportResult(import_id, preview.inserted_count, preview.updated_count, preview.missing_count)
            conn.execute('INSERT INTO showcase_import_logs (import_id,source_path,imported_at,inserted_count,updated_count,missing_count,mode,scope,status,started_at,committed_at,source_fingerprint) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)', (import_id, preview.source_path, now, result.inserted_count, result.updated_count, result.missing_count, preview.mode, preview.scope, 'committed', now, now, preview.fingerprint))
            conn.execute("INSERT INTO showcase_settings(setting_key,setting_value) VALUES ('inventory_updated_at',?) ON CONFLICT(setting_key) DO UPDATE SET setting_value=excluded.setting_value", (now,))
            conn.execute("INSERT INTO showcase_settings(setting_key,setting_value) VALUES ('catalog_revision','1') ON CONFLICT(setting_key) DO UPDATE SET setting_value=CAST(setting_value AS INTEGER)+1")
            return result
