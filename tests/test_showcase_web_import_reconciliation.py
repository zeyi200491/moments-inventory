from pathlib import Path
import pytest
from moments_inventory.exporter import _write_workbook
from moments_inventory.showcase import SHOWCASE_HEADERS
from moments_inventory.showcase_web.importer import import_showcase_workbook
from moments_inventory.showcase_web.repository import SQLiteShowcaseRepository


def workbook(path, items):
    rows = [SHOWCASE_HEADERS]
    for product_id, price, visible in items:
        row = dict.fromkeys(SHOWCASE_HEADERS, '')
        row.update({'商品ID': product_id, '型号': 'ixus80', '品牌': '佳能', '成本价': 100, '展示价': price, '是否展示': visible, '原文文案': str(price), '展示文案': str(price)})
        rows.append([row[key] for key in SHOWCASE_HEADERS])
    _write_workbook(path, rows)
    return path


@pytest.mark.parametrize('items', [[('p1', 'bad', '是')], [('p1', -1, '是')], [('p1', 1.5, '是')], [('p1', 1, '是'), ('p1', 2, '否')]])
def test_invalid_rows_do_not_write(tmp_path, items):
    repo = SQLiteShowcaseRepository(tmp_path / 'test.db')
    repo.initialize()
    with pytest.raises(ValueError):
        import_showcase_workbook(workbook(tmp_path / 'a.xlsx', items), repo)
    assert repo.list_product_ids() == set()
    assert repo.list_import_logs() == []


def test_missing_header_is_rejected(tmp_path):
    repo = SQLiteShowcaseRepository(tmp_path / 'test.db')
    repo.initialize()
    path = tmp_path / 'bad.xlsx'
    _write_workbook(path, [['商品ID'], ['p1']])
    with pytest.raises(ValueError):
        import_showcase_workbook(path, repo)


def test_follow_source_and_full_missing_keeps_visibility(tmp_path):
    repo = SQLiteShowcaseRepository(tmp_path / 'test.db')
    repo.initialize()
    path = workbook(tmp_path / 'a.xlsx', [('p1', 100, '是'), ('p2', 200, '是')])
    import_showcase_workbook(path, repo, mode='full', complete=True)
    workbook(path, [('p1', 300, '否')])
    result = import_showcase_workbook(path, repo, mode='full', complete=True, max_missing_fraction=1)
    assert result.missing_count == 1
    assert repo.get_product('p1').display_price == 300
    assert repo.get_product('p1').visible is False
    assert repo.get_product('p2').visible is True
    assert repo.get_product('p2').review_state == 'missing'


def test_same_fingerprint_reuses_result(tmp_path):
    repo = SQLiteShowcaseRepository(tmp_path / 'test.db')
    repo.initialize()
    path = workbook(tmp_path / 'a.xlsx', [('p1', 100, '是')])
    first = import_showcase_workbook(path, repo)
    second = import_showcase_workbook(path, repo)
    assert first == second
    assert len(repo.list_import_logs()) == 1


def test_a_b_a_full_import_reapplies_returned_source_snapshot(tmp_path):
    repo = SQLiteShowcaseRepository(tmp_path / 'test.db')
    repo.initialize()
    path = workbook(tmp_path / 'a.xlsx', [('p1', 100, '是'), ('p2', 200, '是')])
    a_content = path.read_bytes()
    first_a = import_showcase_workbook(path, repo, mode='full', complete=True)

    workbook(path, [('p1', 150, '是')])
    import_showcase_workbook(path, repo, mode='full', complete=True, max_missing_fraction=1)
    assert repo.get_product('p2').review_state == 'missing'

    path.write_bytes(a_content)
    returned_a = import_showcase_workbook(path, repo, mode='full', complete=True)

    assert returned_a.import_id != first_a.import_id
    assert repo.get_product('p2').review_state == ''
    assert repo.get_product('p2').source_available is True
    assert repo.get_product('p2').visible is True
    assert len(repo.list_import_logs()) == 3


def test_full_source_can_return_to_an_earlier_fingerprint(tmp_path):
    repo = SQLiteShowcaseRepository(tmp_path / 'test.db')
    repo.initialize()
    path = workbook(tmp_path / 'a.xlsx', [('p1', 100, '是'), ('p2', 200, '是')])
    first = import_showcase_workbook(path, repo, mode='full', complete=True, max_missing_fraction=1)
    repeated = import_showcase_workbook(path, repo, mode='full', complete=True, max_missing_fraction=1)
    assert repeated.import_id == first.import_id
    workbook(path, [('p1', 300, '是')])
    import_showcase_workbook(path, repo, mode='full', complete=True, max_missing_fraction=1)
    assert repo.get_product('p2').source_available is False

    workbook(path, [('p1', 100, '是'), ('p2', 200, '是')])
    returned = import_showcase_workbook(path, repo, mode='full', complete=True, max_missing_fraction=1)

    assert returned.import_id != first.import_id
    assert repo.get_product('p2').source_available is True
    assert repo.get_product('p2').review_state == ''
    assert len(repo.list_import_logs()) == 3


def test_full_import_requires_complete_nonempty_and_guarded_size(tmp_path):
    repo = SQLiteShowcaseRepository(tmp_path / 'test.db')
    repo.initialize()
    path = workbook(tmp_path / 'a.xlsx', [('p1', 100, '是'), ('p2', 200, '是')])
    with pytest.raises(ValueError):
        import_showcase_workbook(path, repo, mode='full')
    import_showcase_workbook(path, repo, mode='full', complete=True)
    workbook(path, [('p1', 100, '是')])
    with pytest.raises(ValueError, match='阈值'):
        import_showcase_workbook(path, repo, mode='full', complete=True)
    workbook(path, [])
    with pytest.raises(ValueError):
        import_showcase_workbook(path, repo, mode='full', complete=True)
    assert repo.get_product('p2').review_state == ''


def test_incremental_and_other_scope_do_not_mark_missing(tmp_path):
    repo = SQLiteShowcaseRepository(tmp_path / 'test.db')
    repo.initialize()
    path = workbook(tmp_path / 'a.xlsx', [('p1', 100, '是')])
    import_showcase_workbook(path, repo, scope='a')
    workbook(path, [('p2', 200, '是')])
    import_showcase_workbook(path, repo, mode='full', scope='b', complete=True)
    workbook(path, [('p3', 300, '是')])
    import_showcase_workbook(path, repo, scope='a')
    assert repo.get_product('p1').review_state == ''
    assert repo.get_product('p2').review_state == ''


def test_preview_conflict_and_database_failure_are_atomic(tmp_path):
    from moments_inventory.showcase_web.importer import preview_showcase_workbook
    from moments_inventory.showcase_web.import_service import commit_import
    import sqlite3
    repo = SQLiteShowcaseRepository(tmp_path / 'test.db')
    repo.initialize()
    path = workbook(tmp_path / 'a.xlsx', [('p1', 100, '是')])
    import_showcase_workbook(path, repo)
    previous_time = repo.get_setting('inventory_updated_at')
    workbook(path, [('p1', 200, '是'), ('p2', 300, '是')])
    preview = preview_showcase_workbook(path, repo)
    repo.update_product_price('p1', 999)
    with pytest.raises(ValueError, match='冲突'):
        commit_import(repo, preview)
    assert repo.get_product('p2') is None
    assert repo.get_product('p1').display_price == 999
    with repo._get_connection() as conn:
        conn.execute("CREATE TRIGGER reject_import BEFORE INSERT ON showcase_import_logs BEGIN SELECT RAISE(ABORT, 'test failure'); END")
    with pytest.raises(sqlite3.IntegrityError):
        import_showcase_workbook(path, repo)
    assert repo.get_product('p2') is None
    assert repo.get_product('p1').display_price == 999
    assert repo.get_setting('inventory_updated_at') == previous_time
    assert len(repo.list_import_logs()) == 1


def test_override_preserved_and_sold_not_relisted(tmp_path):
    repo = SQLiteShowcaseRepository(tmp_path / 'test.db')
    repo.initialize()
    path = workbook(tmp_path / 'a.xlsx', [('p1', 100, '是')])
    import_showcase_workbook(path, repo)
    with repo._get_connection() as conn:
        conn.execute("UPDATE showcase_products SET price_override=999, copy_override='人工文案', visibility_override=1, sold=1 WHERE product_id='p1'")
    workbook(path, [('p1', 200, '是')])
    import_showcase_workbook(path, repo)
    product = repo.get_product('p1')
    assert product.display_price == 999
    assert product.display_copy == '人工文案'
    assert product.source_display_price == 200
    assert product.visible is False
