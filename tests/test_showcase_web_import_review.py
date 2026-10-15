from __future__ import annotations

from contextlib import contextmanager
import inspect
import pytest

from moments_inventory.exporter import _write_workbook
from moments_inventory.showcase import SHOWCASE_HEADERS
from moments_inventory.showcase_web.import_review_service import (
    commit_import_review_batch,
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
    staged = _row(repo, batch['batch_id'], 2)
    assert staged['decision'] is None
    assert 'snapshot_json' not in staged
    assert batch['idempotency_key'] == ''


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


def test_alias_to_product_in_another_scope_is_conflict_not_recommendation(tmp_path):
    repo = SQLiteShowcaseRepository(tmp_path / 'showcase.db')
    _seed_product(repo, 'foreign-product', source_key='different-key', scope='source-b')
    with repo._get_connection() as conn:
        conn.execute("insert into showcase_source_identity_aliases values ('bad-alias','source-a','alias-key','foreign-product','now')")
    payload = _workbook_bytes(tmp_path, [{'商品ID': 'row-a', '型号': 'ixus80', '品牌': '佳能', '成本价': 10, '展示价': 20, '是否展示': '是', '来源商品键': 'alias-key'}])

    batch = create_import_review_batch(repo, payload, source_scope='source-a')
    staged = _row(repo, batch['batch_id'], 2)

    assert staged['recommendation'] is None
    assert any('其他来源范围' in error for error in staged['errors'])
    assert staged['decision'] is None


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


def test_model_candidates_are_limited_to_the_current_source_scope(tmp_path):
    repo = SQLiteShowcaseRepository(tmp_path / 'showcase.db')
    _seed_product(repo, 'same-scope', source_key='key-a', scope='source-a')
    _seed_product(repo, 'other-scope', source_key='key-b', scope='source-b')
    payload = _workbook_bytes(tmp_path, [{'商品ID': 'new-product', '型号': 'ixus80', '品牌': '佳能', '成本价': 10, '展示价': 20, '是否展示': '是'}])

    batch = create_import_review_batch(repo, payload, source_scope='source-a')
    staged = _row(repo, batch['batch_id'], 2)

    assert [item['product_id'] for item in staged['candidates']] == ['same-scope']


def test_upload_batches_do_not_accept_commit_idempotency_key(tmp_path):
    repo = SQLiteShowcaseRepository(tmp_path / 'showcase.db')
    payload = _workbook_bytes(tmp_path, [{'商品ID': 'new-product', '型号': 'ixus80', '品牌': '佳能', '成本价': 10, '展示价': 20, '是否展示': '是'}])

    assert 'idempotency_key' not in inspect.signature(create_import_review_batch).parameters
    with pytest.raises(TypeError):
        create_import_review_batch(repo, payload, source_scope='source-a', idempotency_key='client-key')


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


def test_duplicate_product_ids_keep_rows_for_manual_resolution(tmp_path):
    repo = SQLiteShowcaseRepository(tmp_path / 'showcase.db')
    payload = _workbook_bytes(tmp_path, [
        {'商品ID': 'same-id', '型号': 'ixus80', '品牌': '佳能', '成本价': 10, '展示价': 20, '是否展示': '是'},
        {'商品ID': 'same-id', '型号': 'ixus80', '品牌': '佳能', '成本价': 11, '展示价': 21, '是否展示': '是'},
    ])

    batch = create_import_review_batch(repo, payload, source_scope='source-a')
    rows = list_import_review_rows(repo, batch['batch_id'])

    assert [item['row_number'] for item in rows] == [2, 3]
    assert all('商品ID重复' in ' '.join(item['errors']) for item in rows)
    assert all(item['decision'] is None and item['product_id'] is None for item in rows)


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


def test_invalid_source_key_format_rejects_batch(tmp_path):
    repo = SQLiteShowcaseRepository(tmp_path / 'showcase.db')
    payload = _workbook_bytes(tmp_path, [{
        '商品ID': 'bad-key', '型号': 'ixus80', '品牌': '佳能', '成本价': 10,
        '展示价': 20, '是否展示': '是', '来源商品键': 'k' * 257,
    }])

    with pytest.raises(ValueError, match='第 2 行'):
        create_import_review_batch(repo, payload, source_scope='source-a')
    with repo._get_connection() as conn:
        assert conn.execute('select count(*) from showcase_import_review_batches').fetchone()[0] == 0


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


def test_full_batch_persists_missing_product_details(tmp_path):
    repo = SQLiteShowcaseRepository(tmp_path / 'showcase.db')
    _seed_product(repo, 'missing-product', source_key='old-key')
    payload = _workbook_bytes(tmp_path, [{'商品ID': 'new-product', '型号': 'powershot', '品牌': '佳能', '成本价': 10, '展示价': 20, '是否展示': '是', '来源商品键': 'new-key'}])

    batch = create_import_review_batch(repo, payload, source_scope='source-a', mode='full', complete=True)

    assert batch['missing_count'] == 1
    assert batch['result']['missing_items'] == [{
        'product_id': 'missing-product',
        'model': 'ixus80',
        'brand': '佳能',
        'source_product_key': 'old-key',
        'row_version': 0,
    }]


def test_full_source_presence_includes_same_scope_product_id_without_auto_link(tmp_path):
    repo = SQLiteShowcaseRepository(tmp_path / 'showcase.db')
    _seed_product(repo, 'present-by-id', source_key='old-key')
    payload = _workbook_bytes(tmp_path, [{'商品ID': 'present-by-id', '型号': 'ixus80', '品牌': '佳能', '成本价': 10, '展示价': 20, '是否展示': '是'}])

    batch = create_import_review_batch(repo, payload, source_scope='source-a', mode='full', complete=True)
    staged = _row(repo, batch['batch_id'], 2)

    assert batch['missing_count'] == 0
    assert batch['result']['missing_items'] == []
    assert staged['recommendation'] is None
    assert staged['decision'] is None


def test_full_product_id_from_other_scope_is_error_and_does_not_count_present(tmp_path):
    repo = SQLiteShowcaseRepository(tmp_path / 'showcase.db')
    _seed_product(repo, 'current-product', source_key='current-key', scope='source-a')
    _seed_product(repo, 'foreign-product', source_key='foreign-key', scope='source-b')
    payload = _workbook_bytes(tmp_path, [{'商品ID': 'foreign-product', '型号': 'ixus80', '品牌': '佳能', '成本价': 10, '展示价': 20, '是否展示': '是'}])

    batch = create_import_review_batch(repo, payload, source_scope='source-a', mode='full', complete=True)
    staged = _row(repo, batch['batch_id'], 2)

    assert batch['missing_count'] == 1
    assert batch['result']['missing_items'][0]['product_id'] == 'current-product'
    assert any('其他来源范围' in error for error in staged['errors'])
    assert staged['recommendation'] is None


def test_full_missing_summary_uses_one_read_snapshot_during_product_deletion(tmp_path):
    repo = SQLiteShowcaseRepository(tmp_path / 'showcase.db')
    _seed_product(repo, 'snapshot-product', source_key='snapshot-key')
    payload = _workbook_bytes(tmp_path, [{'商品ID': 'new-product', '型号': 'powershot', '品牌': '佳能', '成本价': 10, '展示价': 20, '是否展示': '是', '来源商品键': 'new-key'}])
    original_read_connection = repo._read_connection
    read_count = 0

    @contextmanager
    def delete_after_first_snapshot():
        nonlocal read_count
        read_count += 1
        with original_read_connection() as conn:
            yield conn
        if read_count == 1:
            with repo._get_connection() as write_conn:
                write_conn.execute("delete from showcase_products where product_id='snapshot-product'")

    repo._read_connection = delete_after_first_snapshot

    batch = create_import_review_batch(repo, payload, source_scope='source-a', mode='full', complete=True)

    assert batch['missing_count'] == 1
    assert batch['result']['missing_items'] == [{
        'product_id': 'snapshot-product',
        'model': 'ixus80',
        'brand': '佳能',
        'source_product_key': 'snapshot-key',
        'row_version': 0,
    }]


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


def test_commit_creates_products_and_retries_same_idempotency_key(tmp_path):
    repo = SQLiteShowcaseRepository(tmp_path / 'showcase.db')
    payload = _workbook_bytes(tmp_path, [
        {'商品ID': 'new-1', '型号': 'ixus80', '品牌': '佳能', '成本价': 10, '展示价': 20, '是否展示': '是', '来源商品键': 'key-new'},
    ])
    batch = create_import_review_batch(repo, payload, source_scope='source-a', source_path='fake.xlsx')
    row = _row(repo, batch['batch_id'], 2)
    save_import_review_decision(repo, batch['batch_id'], row['review_row_id'], decision='create')

    result = commit_import_review_batch(repo, batch['batch_id'], 'client-key')
    retried = commit_import_review_batch(repo, batch['batch_id'], 'client-key')

    assert retried == result
    assert repo.list_product_ids() == {'new-1'}
    assert result['inserted_count'] == 1
    assert result['updated_count'] == 0
    assert result['missing_count'] == 0
    assert len(repo.list_import_logs()) == 1
    assert repo.get_setting('catalog_revision') == '1'
    assert get_import_review_batch(repo, batch['batch_id'])['status'] == 'committed'


def test_link_commit_preserves_identity_overrides_and_relationships_then_adds_alias(tmp_path):
    repo = SQLiteShowcaseRepository(tmp_path / 'showcase.db')
    _seed_product(repo)
    with repo._get_connection() as conn:
        conn.execute("update showcase_products set price_override=333,copy_override='manual',visibility_override=1,sold=1 where product_id='old-1'")
        conn.execute("insert into showcase_product_images values ('gallery-body','old-1','gallery.jpg','body',8,0,'gallery')")
        conn.execute("insert into showcase_sections values ('section-1','title','subtitle',1,0,'now','now')")
        conn.execute("insert into showcase_section_items values ('section-item','section-1','old-1',0,'note','now','now')")
    payload = _workbook_bytes(tmp_path, [
        {'商品ID': 'workbook-id', '型号': 'ixus80-new', '品牌': '佳能', '成本价': 12, '展示价': 88,
         '是否展示': '是', '来源商品键': 'new-alias', '机身图路径': 'new-body.jpg'},
    ])
    batch = create_import_review_batch(repo, payload, source_scope='source-a')
    staged = _row(repo, batch['batch_id'], 2)
    save_import_review_decision(repo, batch['batch_id'], staged['review_row_id'], decision='link', product_id='old-1')

    result = commit_import_review_batch(repo, batch['batch_id'], 'link-key')
    product = repo.get_product('old-1')
    with repo._get_connection() as conn:
        alias = conn.execute("select product_id from showcase_source_identity_aliases where source_scope='source-a' and source_key='new-alias'").fetchone()
        images = conn.execute("select image_id,image_path,source from showcase_product_images where product_id='old-1' order by image_id").fetchall()
        section_link = conn.execute("select product_id from showcase_section_items where item_id='section-item'").fetchone()

    assert result['updated_count'] == 1 and result['inserted_count'] == 0
    assert product.product_id == 'old-1' and product.public_id == 'old-1'
    assert product.price_override == 333 and product.copy_override == 'manual'
    assert product.sold is True and product.display_price == 333 and product.display_copy == 'manual'
    assert alias == ('old-1',)
    assert ('gallery-body', 'gallery.jpg', 'gallery') in images
    assert ('old-1|body|0', 'new-body.jpg', 'inventory_import') in images
    assert section_link == ('old-1',)

    next_batch = create_import_review_batch(repo, payload, source_scope='source-a')
    assert _row(repo, next_batch['batch_id'], 2)['recommendation']['product_id'] == 'old-1'


def test_duplicate_source_key_requires_skipping_conflicting_row(tmp_path):
    repo = SQLiteShowcaseRepository(tmp_path / 'showcase.db')
    payload = _workbook_bytes(tmp_path, [
        {'商品ID': 'new-1', '型号': 'ixus80', '品牌': '佳能', '成本价': 10, '展示价': 20, '是否展示': '是', '来源商品键': 'dup'},
        {'商品ID': 'new-2', '型号': 'powershot', '品牌': '佳能', '成本价': 11, '展示价': 21, '是否展示': '是', '来源商品键': 'dup'},
    ])
    batch = create_import_review_batch(repo, payload, source_scope='source-a')
    rows = list_import_review_rows(repo, batch['batch_id'])
    save_import_review_decision(repo, batch['batch_id'], rows[0]['review_row_id'], decision='create')
    save_import_review_decision(repo, batch['batch_id'], rows[1]['review_row_id'], decision='create')
    before_revision = repo.get_setting('catalog_revision')

    with pytest.raises(ValueError, match='多个写入行'):
        commit_import_review_batch(repo, batch['batch_id'], 'dupe-key')

    assert repo.list_product_ids() == set()
    assert repo.list_import_logs() == []
    assert repo.get_setting('catalog_revision') == before_revision
    assert get_import_review_batch(repo, batch['batch_id'])['status'] == 'pending'

    save_import_review_decision(repo, batch['batch_id'], rows[1]['review_row_id'], decision='skip')
    assert commit_import_review_batch(repo, batch['batch_id'], 'dupe-key')['inserted_count'] == 1


def test_full_commit_rejects_scope_changes_and_leaves_batch_pending(tmp_path):
    repo = SQLiteShowcaseRepository(tmp_path / 'showcase.db')
    _seed_product(repo, 'old-item', source_key='old-key')
    payload = _workbook_bytes(tmp_path, [
        {'商品ID': 'new-item', '型号': 'powershot', '品牌': '佳能', '成本价': 10, '展示价': 20, '是否展示': '是', '来源商品键': 'new-key'},
    ])
    batch = create_import_review_batch(repo, payload, source_scope='source-a', mode='full', complete=True)
    row = _row(repo, batch['batch_id'], 2)
    save_import_review_decision(repo, batch['batch_id'], row['review_row_id'], decision='create')
    _seed_product(repo, 'added-after-stage', source_key='another-key')
    before_products = repo.list_product_ids()
    before_revision = repo.get_setting('catalog_revision')

    with pytest.raises(ValueError, match='增删'):
        commit_import_review_batch(repo, batch['batch_id'], 'full-key')

    assert repo.list_product_ids() == before_products
    assert repo.get_setting('catalog_revision') == before_revision
    assert repo.list_import_logs() == []
    assert get_import_review_batch(repo, batch['batch_id'])['status'] == 'pending'


def test_database_error_rolls_back_products_aliases_logs_and_batch_state(tmp_path):
    repo = SQLiteShowcaseRepository(tmp_path / 'showcase.db')
    _seed_product(repo)
    payload = _workbook_bytes(tmp_path, [
        {'商品ID': 'workbook-id', '型号': 'ixus80-new', '品牌': '佳能', '成本价': 12, '展示价': 88,
         '是否展示': '是', '来源商品键': 'new-alias'},
    ])
    batch = create_import_review_batch(repo, payload, source_scope='source-a')
    staged = _row(repo, batch['batch_id'], 2)
    save_import_review_decision(repo, batch['batch_id'], staged['review_row_id'], decision='link', product_id='old-1')
    before = repo.get_product('old-1')
    before_revision = repo.get_setting('catalog_revision')
    with repo._get_connection() as conn:
        conn.execute("create trigger fail_import_log before insert on showcase_import_logs begin select raise(abort,'injected failure'); end")

    with pytest.raises(Exception, match='injected failure'):
        commit_import_review_batch(repo, batch['batch_id'], 'rollback-key')

    assert repo.get_product('old-1') == before
    assert repo.get_setting('catalog_revision') == before_revision
    assert repo.list_import_logs() == []
    assert get_import_review_batch(repo, batch['batch_id'])['status'] == 'pending'
    with repo._get_connection() as conn:
        assert conn.execute("select count(*) from showcase_source_identity_aliases where source_key='new-alias'").fetchone()[0] == 0


def test_commit_rejects_stale_link_target_version_without_partial_writes(tmp_path):
    repo = SQLiteShowcaseRepository(tmp_path / 'showcase.db')
    _seed_product(repo)
    payload = _workbook_bytes(tmp_path, [
        {'商品ID': 'workbook-id', '型号': 'ixus80', '品牌': '佳能', '成本价': 12, '展示价': 88, '是否展示': '是'},
    ])
    batch = create_import_review_batch(repo, payload, source_scope='source-a')
    row = _row(repo, batch['batch_id'], 2)
    save_import_review_decision(repo, batch['batch_id'], row['review_row_id'], decision='link', product_id='old-1')
    with repo._get_connection() as conn:
        conn.execute("update showcase_products set raw_copy='changed' where product_id='old-1'")
    before = repo.get_product('old-1')
    before_revision = repo.get_setting('catalog_revision')

    with pytest.raises(ValueError, match='版本已变化'):
        commit_import_review_batch(repo, batch['batch_id'], 'stale-key')

    assert repo.get_product('old-1') == before
    assert repo.get_setting('catalog_revision') == before_revision
    assert repo.list_import_logs() == []


def test_commit_rejects_existing_alias_claimed_by_another_product(tmp_path):
    repo = SQLiteShowcaseRepository(tmp_path / 'showcase.db')
    _seed_product(repo)
    _seed_product(repo, 'other', source_key='other-key', model='powershot')
    with repo._get_connection() as conn:
        conn.execute("insert into showcase_source_identity_aliases values ('alias-1','source-a','taken-key','other','now')")
    payload = _workbook_bytes(tmp_path, [
        {'商品ID': 'workbook-id', '型号': 'ixus80-new', '品牌': '佳能', '成本价': 12, '展示价': 88, '是否展示': '是', '来源商品键': 'taken-key'},
    ])
    batch = create_import_review_batch(repo, payload, source_scope='source-a')
    row = _row(repo, batch['batch_id'], 2)
    save_import_review_decision(repo, batch['batch_id'], row['review_row_id'], decision='link', product_id='old-1')

    with pytest.raises(ValueError, match='其他商品'):
        commit_import_review_batch(repo, batch['batch_id'], 'alias-conflict')

    assert repo.list_import_logs() == []
    assert get_import_review_batch(repo, batch['batch_id'])['status'] == 'pending'


def test_commit_rechecks_duplicate_target_claims_inside_transaction(tmp_path):
    repo = SQLiteShowcaseRepository(tmp_path / 'showcase.db')
    _seed_product(repo)
    payload = _workbook_bytes(tmp_path, [
        {'商品ID': 'row-a', '型号': 'ixus80', '品牌': '佳能', '成本价': 10, '展示价': 20, '是否展示': '是'},
        {'商品ID': 'row-b', '型号': 'powershot', '品牌': '佳能', '成本价': 11, '展示价': 21, '是否展示': '是'},
    ])
    batch = create_import_review_batch(repo, payload, source_scope='source-a')
    rows = list_import_review_rows(repo, batch['batch_id'])
    save_import_review_decision(repo, batch['batch_id'], rows[0]['review_row_id'], decision='link', product_id='old-1')
    with repo._get_connection() as conn:
        conn.execute("update showcase_import_review_rows set product_id='old-1' where review_row_id=?", (rows[1]['review_row_id'],))
        conn.execute("update showcase_import_review_rows set decision='link',target_row_version=? where review_row_id=?",
                     (repo.get_product('old-1').row_version, rows[1]['review_row_id']))

    with pytest.raises(ValueError, match='多个导入行'):
        commit_import_review_batch(repo, batch['batch_id'], 'target-conflict')

    assert repo.get_product('old-1').row_version == 0
    assert repo.list_import_logs() == []


def test_full_commit_skip_keeps_skipped_product_visible_and_counts_it_missing(tmp_path):
    repo = SQLiteShowcaseRepository(tmp_path / 'showcase.db')
    _seed_product(repo, 'skipped-item', source_key='old-key')
    payload = _workbook_bytes(tmp_path, [
        {'商品ID': 'skipped-item', '型号': 'ixus80', '品牌': '佳能', '成本价': 10, '展示价': 20, '是否展示': '是', '来源商品键': 'old-key'},
        {'商品ID': 'new-item', '型号': 'powershot', '品牌': '佳能', '成本价': 11, '展示价': 21, '是否展示': '是', '来源商品键': 'new-key'},
    ])
    batch = create_import_review_batch(repo, payload, source_scope='source-a', mode='full', complete=True)
    rows = list_import_review_rows(repo, batch['batch_id'])
    save_import_review_decision(repo, batch['batch_id'], rows[0]['review_row_id'], decision='skip')
    save_import_review_decision(repo, batch['batch_id'], rows[1]['review_row_id'], decision='create')

    result = commit_import_review_batch(repo, batch['batch_id'], 'full-skip')
    skipped = repo.get_product('skipped-item')

    assert result['missing_count'] == 1
    assert skipped.source_available is False
    assert skipped.review_state == 'missing'
    assert skipped.visible is True


def test_same_idempotency_key_is_allowed_for_different_batches(tmp_path):
    repo = SQLiteShowcaseRepository(tmp_path / 'showcase.db')
    payload_a = _workbook_bytes(tmp_path, [
        {'商品ID': 'new-a', '型号': 'ixus80', '品牌': '佳能', '成本价': 10, '展示价': 20, '是否展示': '是'},
    ])
    batch_a = create_import_review_batch(repo, payload_a, source_scope='source-a')
    row_a = _row(repo, batch_a['batch_id'], 2)
    save_import_review_decision(repo, batch_a['batch_id'], row_a['review_row_id'], decision='create')
    payload_b = _workbook_bytes(tmp_path, [
        {'商品ID': 'new-b', '型号': 'powershot', '品牌': '佳能', '成本价': 11, '展示价': 21, '是否展示': '是'},
    ])
    batch_b = create_import_review_batch(repo, payload_b, source_scope='source-b')
    row_b = _row(repo, batch_b['batch_id'], 2)
    save_import_review_decision(repo, batch_b['batch_id'], row_b['review_row_id'], decision='create')

    commit_import_review_batch(repo, batch_a['batch_id'], 'shared-key')
    commit_import_review_batch(repo, batch_b['batch_id'], 'shared-key')

    assert repo.list_product_ids() == {'new-a', 'new-b'}
    assert len(repo.list_import_logs()) == 2


def test_committed_batch_rejects_a_different_idempotency_key(tmp_path):
    repo = SQLiteShowcaseRepository(tmp_path / 'showcase.db')
    payload = _workbook_bytes(tmp_path, [
        {'商品ID': 'new-id', '型号': 'ixus80', '品牌': '佳能', '成本价': 10, '展示价': 20, '是否展示': '是'},
    ])
    batch = create_import_review_batch(repo, payload, source_scope='source-a')
    row = _row(repo, batch['batch_id'], 2)
    save_import_review_decision(repo, batch['batch_id'], row['review_row_id'], decision='create')
    result = commit_import_review_batch(repo, batch['batch_id'], 'first-key')

    with pytest.raises(ValueError, match='其他幂等键'):
        commit_import_review_batch(repo, batch['batch_id'], 'second-key')

    assert commit_import_review_batch(repo, batch['batch_id'], 'first-key') == result
    assert len(repo.list_import_logs()) == 1
    assert repo.get_setting('catalog_revision') == '1'


def test_commit_rejects_any_undecided_row_without_writing(tmp_path):
    repo = SQLiteShowcaseRepository(tmp_path / 'showcase.db')
    payload = _workbook_bytes(tmp_path, [
        {'商品ID': 'new-a', '型号': 'ixus80', '品牌': '佳能', '成本价': 10, '展示价': 20, '是否展示': '是'},
        {'商品ID': 'new-b', '型号': 'powershot', '品牌': '佳能', '成本价': 11, '展示价': 21, '是否展示': '是'},
    ])
    batch = create_import_review_batch(repo, payload, source_scope='source-a')
    rows = list_import_review_rows(repo, batch['batch_id'])
    save_import_review_decision(repo, batch['batch_id'], rows[0]['review_row_id'], decision='create')

    with pytest.raises(ValueError, match='所有复核行'):
        commit_import_review_batch(repo, batch['batch_id'], 'partial')

    assert repo.list_product_ids() == set()
    assert repo.list_import_logs() == []


@pytest.mark.parametrize('change', ['delete', 'update'])
def test_full_commit_rejects_deleted_or_changed_scope_products(tmp_path, change):
    repo = SQLiteShowcaseRepository(tmp_path / 'showcase.db')
    _seed_product(repo, 'scope-item', source_key='scope-key')
    payload = _workbook_bytes(tmp_path, [
        {'商品ID': 'new-item', '型号': 'powershot', '品牌': '佳能', '成本价': 10, '展示价': 20, '是否展示': '是'},
    ])
    batch = create_import_review_batch(repo, payload, source_scope='source-a', mode='full', complete=True)
    row = _row(repo, batch['batch_id'], 2)
    save_import_review_decision(repo, batch['batch_id'], row['review_row_id'], decision='create')
    with repo._get_connection() as conn:
        if change == 'delete':
            conn.execute("delete from showcase_products where product_id='scope-item'")
        else:
            conn.execute("update showcase_products set raw_copy='changed' where product_id='scope-item'")
    before_products = repo.list_product_ids()
    before_revision = repo.get_setting('catalog_revision')

    with pytest.raises(ValueError, match='来源范围|版本已变化'):
        commit_import_review_batch(repo, batch['batch_id'], 'scope-race')

    assert repo.list_product_ids() == before_products
    assert repo.get_setting('catalog_revision') == before_revision
    assert repo.list_import_logs() == []




