"""批量确认快照、幂等提交及带版本保护的撤销。"""
import hashlib
import json
import sqlite3
import uuid
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException


def save_preview(repo, owner, request, items):
    preview_id = uuid.uuid4().hex
    now = datetime.now(timezone.utc)
    expires = (now + timedelta(minutes=15)).isoformat()
    with repo._lock, repo._get_connection() as conn:
        conn.execute('DELETE FROM showcase_bulk_previews WHERE expires_at < ? AND operation_id = ?',
                     (now.isoformat(), ''))
        conn.execute('INSERT INTO showcase_bulk_previews VALUES (?,?,?,?,?,?)',
                     (preview_id, owner, json.dumps(request), json.dumps(items), expires, ''))
    return preview_id, expires


def _cached(conn, owner, key, fingerprint):
    row = conn.execute('SELECT * FROM showcase_idempotency WHERE idempotency_key=?', (key,)).fetchone()
    if row is None:
        return None
    if row['owner'] != owner or row['request_hash'] != fingerprint:
        raise HTTPException(409, '幂等键已经用于其他请求')
    return json.loads(row['response_json'])


def _write_operation(
    conn, operation_id, operation_type, items, now, summary, filter_text, parent,
):
    conn.execute('''INSERT INTO showcase_admin_operation_logs
        (operation_id,operation_type,summary,filter_text,updated_count,created_at,undone_at,parent_operation_id)
        VALUES (?,?,?,?,?,?,?,?)''',
        (operation_id, operation_type, summary, filter_text, len(items), now, '', parent))
    conn.executemany('''INSERT INTO showcase_admin_operation_items
            (item_id,operation_id,product_id,old_price,new_price,old_visible,new_visible,old_version,new_version,
             old_price_override,new_price_override,old_visibility_override,new_visibility_override,
             old_override_origin,new_override_origin)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''', [(uuid.uuid4().hex, operation_id, item['productId'],
            item['oldPrice'], item['newPrice'], item['oldVisible'], item['newVisible'],
            item['rowVersion'], item['rowVersion'] + 1,
            item.get('oldPriceOverride'), item.get('newPriceOverride'),
            item.get('oldVisibilityOverride'), item.get('newVisibilityOverride'),
            item.get('oldOverrideOrigin', ''), item.get('newOverrideOrigin', '')) for item in items])


def execute(repo, owner, key, reference, *, undo=False):
    fingerprint = hashlib.sha256(f'{undo}:{reference}'.encode()).hexdigest()
    now = datetime.now(timezone.utc).isoformat()
    with repo._lock, repo._get_connection() as connection:
        conn = connection.cursor()
        conn.row_factory = sqlite3.Row
        conn.execute('BEGIN IMMEDIATE')
        cached = _cached(conn, owner, key, fingerprint)
        if cached is not None:
            return cached
        if undo:
            operation = conn.execute('SELECT * FROM showcase_admin_operation_logs WHERE operation_id=?', (reference,)).fetchone()
            if operation is None or operation['undone_at'] or operation['operation_type'] == 'undo':
                raise HTTPException(409, '该操作无法撤销')
            rows = conn.execute('SELECT * FROM showcase_admin_operation_items WHERE operation_id=?', (reference,)).fetchall()
            items = [dict(productId=r['product_id'], rowVersion=r['new_version'],
                          oldPrice=r['new_price'], newPrice=r['old_price'],
                          oldVisible=r['new_visible'], newVisible=r['old_visible'],
                          oldPriceOverride=r['new_price_override'], newPriceOverride=r['old_price_override'],
                          oldVisibilityOverride=r['new_visibility_override'],
                          newVisibilityOverride=r['old_visibility_override'],
                          oldOverrideOrigin=r['new_override_origin'] or '',
                          newOverrideOrigin=r['old_override_origin'] or '') for r in rows]
            operation_type = 'undo'
            summary = f"撤销：{operation['summary']}"
            filter_text = operation['filter_text']
        else:
            preview = conn.execute('SELECT * FROM showcase_bulk_previews WHERE preview_id=?', (reference,)).fetchone()
            if preview is None or preview['owner'] != owner:
                raise HTTPException(404, '预览不存在')
            if preview['operation_id'] or preview['expires_at'] < now:
                raise HTTPException(409, '预览已使用或过期，请重新预览')
            request_data = json.loads(preview['request_json'])
            items = [
                item for item in json.loads(preview['items_json'])
                if item.get('changed') and not item.get('skippedReason')
            ]
            operation_type = request_data['operation']
            summary = request_data.get('operationSummary', '')
            filter_text = request_data.get('filterText', '')
        # 分块读取一次性完成全量校验；任何异常由连接上下文回滚所有商品与日志。
        product_ids = [item['productId'] for item in items]
        current_products = {}
        for start in range(0, len(product_ids), 500):
            chunk = product_ids[start : start + 500]
            placeholders = ','.join('?' for _ in chunk)
            rows = conn.execute(f'''SELECT product_id,row_version,sold,visible,price_override,
                visibility_override,override_origin FROM showcase_products
                WHERE product_id IN ({placeholders})''', chunk).fetchall()
            current_products.update({row['product_id']: row for row in rows})
        for item in items:
            product = current_products.get(item['productId'])
            if product is None or product['row_version'] != item['rowVersion']:
                raise HTTPException(409, '商品已被修改，请重新预览')
            if product['sold'] and not product['visible'] and item['newVisible']:
                raise HTTPException(409, '已售商品不能直接重新展示')
            if not undo:
                item['oldPriceOverride'] = product['price_override']
                item['oldVisibilityOverride'] = product['visibility_override']
                item['oldOverrideOrigin'] = product['override_origin']
                item['newPriceOverride'] = item['newPrice'] if item['oldPrice'] != item['newPrice'] else product['price_override']
                item['newVisibilityOverride'] = item['newVisible'] if item['oldVisible'] != item['newVisible'] else product['visibility_override']
                item['newOverrideOrigin'] = 'manual'
        changed = [i for i in items if i['oldPrice'] != i['newPrice'] or i['oldVisible'] != i['newVisible']]
        columns = {r[1] for r in conn.execute('PRAGMA table_info(showcase_products)')}
        if 'price_override' in columns:
            conn.executemany(
                '''UPDATE showcase_products SET display_price=?,visible=?,updated_at=?,
                   row_version=row_version+1,price_override=?,visibility_override=?,override_origin=?
                   WHERE product_id=?''',
                [(
                    item['newPrice'], item['newVisible'], now,
                    item.get('newPriceOverride'), item.get('newVisibilityOverride'),
                    item.get('newOverrideOrigin', 'manual'), item['productId'],
                ) for item in changed],
            )
        else:
            conn.executemany(
                '''UPDATE showcase_products SET display_price=?,visible=?,updated_at=?,
                   row_version=row_version+1 WHERE product_id=?''',
                [(item['newPrice'], item['newVisible'], now, item['productId']) for item in changed],
            )
        operation_id = uuid.uuid4().hex
        _write_operation(
            conn,
            operation_id,
            operation_type,
            changed,
            now,
            summary,
            filter_text,
            reference if undo else '',
        )
        if undo:
            conn.execute('UPDATE showcase_admin_operation_logs SET undone_at=? WHERE operation_id=?', (now, reference))
        else:
            conn.execute('UPDATE showcase_bulk_previews SET operation_id=? WHERE preview_id=?', (operation_id, reference))
        result = dict(ok=True, operationId=operation_id, updatedCount=len(changed))
        conn.execute('INSERT INTO showcase_idempotency VALUES (?,?,?,?)', (key, owner, fingerprint, json.dumps(result)))
        return result
