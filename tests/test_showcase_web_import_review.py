from __future__ import annotations

import pytest

from moments_inventory.exporter import _write_workbook
from moments_inventory.showcase import SHOWCASE_HEADERS
from moments_inventory.showcase_web.import_review_service import (
    create_import_review_batch,
    discard_import_review_batch,
    get_import_review_batch,
    list_import_review_rows,
    save_import_review_decision,
)
from moments_inventory.showcase_web.repository import SQLiteShowcaseRepository


def _workbook_bytes(tmp_path, rows):
    path = tmp_path / 'review.xlsx'
    sheet = [SHOWCASE_HEADERS]
    for values in rows:
        row = dict.fromkeys(SHOWCASE_HEADERS, '')
        row.update(values)
        sheet.append([row[name] for name in SHOWCASE_HEADERS])
    _write_workbook(path, sheet)
    return path.read_bytes()


def _seed_product(repo, product_id='old-1', *, source_key='key-1', model='ixus80', brand='佳能', scope='source-a'):
    with repo._get_connection() as conn:
        conn.execute(
            """insert into showcase_products
            (product_id,model,brand,cost_price,display_price,visible,sold,published_at,
             raw_copy,display_copy,cover_image_path,created_at,updated_at,last_seen_import_id,
             source_product_key,source_scope,source_display_price,source_display_copy,source_visible,public_id)
            values (?,?,?,?,?,1,0,'','raw','copy','', 'now','now','seed',?,?,100,'copy',1,?)""",
            (product_id, model, brand, 50, 100, source_key, scope, product_id),
        )


def _row(repo, batch_id, row_number):
    return next(item for item in list_import_review_rows(repo, batch_id) if item['row_number'] == row_number)


def test_create_review_batch_stages_rows_without_changing_products_or_import_logs(tmp_path):
    repo = SQLiteShowcaseRepository(tmp_path / 'showcase.db')
    payload = _workbook_bytes(tmp_path, [{'商品ID': 'new-1', '型号': 'ixus80', '品牌': '佳能', '成本价': 100, '展示价': 200, '是否展示': '是', '来源商品键': 'key-new'}])
    before_products = repo.list_product_ids()
    before_logs = repo.list_import_logs()

    batch = create_import_review_batch(repo, payload, source_scope='source-a', mode='incremental')

    assert batch['status'] == 'pending'
    assert batch['parsed_row_count'] == 1
    assert batch['source_fingerprint']
    assert repo.list_product_ids() == before_products
    assert repo.list_import_logs() == before_logs
    assert _row(repo, batch['batch_id'], 2)['decision'] is None


def test_exact_source_key_and_confirmed_alias_are_suggestions_only(tmp_path):
    repo = SQLiteShowcaseRepository(tmp_path / 'showcase.db')
    _seed_product(repo)
    _seed_product(repo, 'alias-target', source_key='old-key', model='powershot', brand='佳能')
    with repo._get_connection() as conn:
        conn.execute("insert into showcase_source_identity_aliases values ('alias-1','source-a','alias-key','alias-target','now')")
    payload = _workbook_bytes(tmp_path, [
        {'商品ID': 'row-a', '型号': 'ixus80', '品牌': '佳能', '成本价': 10, '展示价': 20, '是否展示': '是', '来源商品键': 'key-1'},
        {'商品ID': 'row-b', '型号': 'powershot', '品牌': '佳能', '成本价': 10, '展示价': 20, '是否展示': '是', '来源商品键': 'alias-key'},
    ])

    batch = create_import_review_batch(repo, payload, source_scope='source-a')

    exact, alias = list_import_review_rows(repo, batch['batch_id'])
    assert exact['recommendation']['product_id'] == 'old-1'
    assert alias['recommendation']['product_id'] == 'alias-target'
    assert exact['decision'] is alias['decision'] is None
    assert exact['product_id'] is alias['product_id'] is None


def test_same_model_is_only_a_candidate_and_missing_source_key_can_be_manually_linked(tmp_path):
    repo = SQLiteShowcaseRepository(tmp_path / 'showcase.db')
    _seed_product(repo)
    payload = _workbook_bytes(tmp_path, [{'商品ID': 'new-1', '型号': 'IXUS 80', '品牌': '佳能', '成本价': 100, '展示价': 200, '是否展示': '是'}])

    batch = create_import_review_batch(repo, payload, source_scope='source-a')
    staged = _row(repo, batch['batch_id'], 2)

    assert staged['source_key'] == ''
    assert staged['recommendation'] is None
    assert staged['candidates'][0]['product_id'] == 'old-1'
    assert staged['decision'] is None
    saved = save_import_review_decision(repo, batch['batch_id'], staged['review_row_id'], decision='link', product_id='old-1')
    assert saved['decision'] == 'link'
    assert saved['product_id'] == 'old-1'
    assert saved['target_row_version'] == repo.get_product('old-1').row_version


def test_duplicate_source_keys_keep_both_rows_and_mark_conflict(tmp_path):
    repo = SQLiteShowcaseRepository(tmp_path / 'showcase.db')
    payload = _workbook_bytes(tmp_path, [
        {'商品ID': 'new-1', '型号': 'ixus80', '品牌': '佳能', '成本价': 10, '展示价': 20, '是否展示': '是', '来源商品键': 'dup'},
        {'商品ID': 'new-2', '型号': 'ixus80', '品牌': '佳能', '成本价': 10, '展示价': 20, '是否展示': '是', '来源商品键': 'dup'},
    ])

    batch = create_import_review_batch(repo, payload, source_scope='source-a')
    rows = list_import_review_rows(repo, batch['batch_id'])

    assert [item['row_number'] for item in rows] == [2, 3]
    assert all('重复' in ' '.join(item['errors']) for item in rows)
    assert all(item['decision'] is None for item in rows)


def test_invalid_row_rejects_batch_with_real_excel_row_number(tmp_path):
    repo = SQLiteShowcaseRepository(tmp_path / 'showcase.db')
    path = tmp_path / 'review.xlsx'
    bad = dict.fromkeys(SHOWCASE_HEADERS, '')
    bad.update({'商品ID': 'bad', '型号': 'ixus80', '品牌': '佳能', '成本价': 'bad', '展示价': 20, '是否展示': '是'})
    good = dict.fromkeys(SHOWCASE_HEADERS, '')
    good.update({'商品ID': 'good', '型号': 'ixus80', '品牌': '佳能', '成本价': 10, '展示价': 20, '是否展示': '是'})
    _write_workbook(path, [SHOWCASE_HEADERS, [good[name] for name in SHOWCASE_HEADERS], [bad[name] for name in SHOWCASE_HEADERS]])

    with pytest.raises(ValueError, match='第 3 行'):
        create_import_review_batch(repo, path.read_bytes(), source_scope='source-a')

    with repo._get_connection() as conn:
        assert conn.execute('select count(*) from showcase_import_review_batches').fetchone()[0] == 0
        assert conn.execute('select count(*) from showcase_import_review_rows').fetchone()[0] == 0


def test_full_batch_requires_complete_and_nonempty_scope(tmp_path):
    repo = SQLiteShowcaseRepository(tmp_path / 'showcase.db')
    payload = _workbook_bytes(tmp_path, [{'商品ID': 'new-1', '型号': 'ixus80', '品牌': '佳能', '成本价': 10, '展示价': 20, '是否展示': '是'}])
    with pytest.raises(ValueError, match='完整'):
        create_import_review_batch(repo, payload, source_scope='source-a', mode='full')
    with pytest.raises(ValueError, match='来源范围'):
        create_import_review_batch(repo, payload, source_scope=' ')
    empty_payload = _workbook_bytes(tmp_path, [])
    with pytest.raises(ValueError, match='完整性声明'):
        create_import_review_batch(repo, empty_payload, source_scope='source-a', mode='full', complete=True)
    with repo._get_connection() as conn:
        assert conn.execute('select count(*) from showcase_import_review_batches').fetchone()[0] == 0


def test_missing_threshold_must_be_between_zero_and_one(tmp_path):
    repo = SQLiteShowcaseRepository(tmp_path / 'showcase.db')
    payload = _workbook_bytes(tmp_path, [{'商品ID': 'new-1', '型号': 'ixus80', '品牌': '佳能', '成本价': 10, '展示价': 20, '是否展示': '是'}])
    for threshold in (-0.01, 1.01):
        with pytest.raises(ValueError, match='阈值'):
            create_import_review_batch(repo, payload, source_scope='source-a', max_missing_fraction=threshold)
    with repo._get_connection() as conn:
        assert conn.execute('select count(*) from showcase_import_review_batches').fetchone()[0] == 0


def test_decisions_persist_and_terminal_batches_reject_updates(tmp_path):
    repo = SQLiteShowcaseRepository(tmp_path / 'showcase.db')
    payload = _workbook_bytes(tmp_path, [{'商品ID': 'new-1', '型号': 'ixus80', '品牌': '佳能', '成本价': 10, '展示价': 20, '是否展示': '是'}])
    batch = create_import_review_batch(repo, payload, source_scope='source-a')
    staged = _row(repo, batch['batch_id'], 2)
    save_import_review_decision(repo, batch['batch_id'], staged['review_row_id'], decision='create')

    reopened = get_import_review_batch(repo, batch['batch_id'])
    persisted = _row(repo, batch['batch_id'], 2)
    assert reopened['batch_id'] == batch['batch_id']
    assert persisted['decision'] == 'create'
    assert persisted['product_id'] is None
    assert persisted['target_row_version'] is None
    with pytest.raises(ValueError, match='无效'):
        save_import_review_decision(repo, batch['batch_id'], staged['review_row_id'], decision='automatic')
    with pytest.raises(ValueError, match='pending'):
        save_import_review_decision(repo, 'missing-batch', staged['review_row_id'], decision='skip')
    with repo._get_connection() as conn:
        conn.execute("update showcase_import_review_batches set status='committed' where batch_id=?", (batch['batch_id'],))
    with pytest.raises(ValueError, match='pending'):
        save_import_review_decision(repo, batch['batch_id'], staged['review_row_id'], decision='skip')


def test_discard_only_changes_review_records(tmp_path):
    repo = SQLiteShowcaseRepository(tmp_path / 'showcase.db')
    payload = _workbook_bytes(tmp_path, [{'商品ID': 'new-1', '型号': 'ixus80', '品牌': '佳能', '成本价': 10, '展示价': 20, '是否展示': '是'}])
    batch = create_import_review_batch(repo, payload, source_scope='source-a')
    before_products = repo.list_product_ids()
    before_logs = repo.list_import_logs()

    discarded = discard_import_review_batch(repo, batch['batch_id'])

    assert discarded['status'] == 'discarded'
    assert repo.list_product_ids() == before_products
    assert repo.list_import_logs() == before_logs
    assert all(row['status'] == 'discarded' for row in list_import_review_rows(repo, batch['batch_id']))
    with pytest.raises(ValueError, match='pending'):
        save_import_review_decision(repo, batch['batch_id'], _row(repo, batch['batch_id'], 2)['review_row_id'], decision='skip')


