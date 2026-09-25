from dataclasses import replace

import pytest
from fastapi.testclient import TestClient

from moments_inventory.showcase_web import api as showcase_api
from test_showcase_web_api_admin import repo, authenticated_client, _product


def test_bulk_applies_entire_snapshot_and_retries_once(repo, authenticated_client):
    for index in range(201):
        repo.upsert_product(_product(str(index), visible=True, display_price=500))
    preview = authenticated_client.post('/api/admin/products/bulk-preview', json={
        'scope': 'all', 'operation': 'price', 'amount': 10,
    }).json()
    assert preview['total'] == 201
    assert len(preview['items']) == 200
    assert preview['displayedCount'] == 200
    assert preview['truncated'] is True
    request = {'previewId': preview['previewId'], 'idempotencyKey': 'retry-one'}
    first = authenticated_client.post('/api/admin/products/bulk-apply', json=request)
    assert first.status_code == 200, first.text
    assert first.json()['updatedCount'] == 201
    assert authenticated_client.post('/api/admin/products/bulk-apply', json=request).json() == first.json()
    assert all(repo.get_product(str(i)).display_price == 510 for i in range(201))


def test_bulk_conflict_changes_nothing(repo, authenticated_client):
    for key in ('a', 'b'):
        repo.upsert_product(_product(key, visible=True, display_price=500))
    preview = authenticated_client.post('/api/admin/products/bulk-preview', json={
        'scope': 'all', 'operation': 'price', 'amount': 10,
    }).json()
    repo.upsert_product(replace(repo.get_product('b'), display_price=999))
    result = authenticated_client.post('/api/admin/products/bulk-apply', json={
        'previewId': preview['previewId'], 'idempotencyKey': 'conflict',
    })
    assert result.status_code == 409
    assert repo.get_product('a').display_price == 500
    assert repo.get_product('b').display_price == 999


def test_undo_refuses_overwriting_later_edit(repo, authenticated_client):
    repo.upsert_product(_product('a', visible=True, display_price=500))
    preview = authenticated_client.post('/api/admin/products/bulk-preview', json={
        'scope': 'all', 'operation': 'price', 'amount': 10,
    }).json()
    result = authenticated_client.post('/api/admin/products/bulk-apply', json={
        'previewId': preview['previewId'], 'idempotencyKey': 'apply',
    }).json()
    repo.upsert_product(replace(repo.get_product('a'), display_price=999))
    response = authenticated_client.post('/api/admin/operations/' + result['operationId'] + '/undo',
                                         json={'idempotencyKey': 'undo'})
    assert response.status_code == 409
    assert repo.get_product('a').display_price == 999


def test_public_id_patch_returns_new_version_and_detects_conflict(repo, authenticated_client):
    repo.upsert_product(_product('old/unsafe/id', visible=True, display_price=500))
    product = repo.get_product('old/unsafe/id')
    url = '/api/admin/products/' + product.public_id
    response = authenticated_client.patch(url, json={'displayPrice': 510, 'expectedVersion': product.row_version})
    assert response.status_code == 200
    assert response.json()['publicId'] == product.public_id
    assert response.json()['rowVersion'] > product.row_version
    assert repo.get_product(product.product_id).price_override == 510
    assert authenticated_client.patch(url, json={'displayPrice': 999, 'expectedVersion': product.row_version}).status_code == 409
    assert authenticated_client.get('/api/public/product-lookup', params={'id': product.product_id}).status_code == 200


def test_bulk_undo_restores_import_override_semantics(repo, authenticated_client):
    original = replace(_product('a', visible=True, display_price=500),
                       source_display_price=500, price_override=None,
                       visibility_override=None, override_origin='')
    repo.upsert_product(original)
    preview = authenticated_client.post('/api/admin/products/bulk-preview', json={
        'scope': 'all', 'operation': 'price', 'amount': 10,
    }).json()
    applied = authenticated_client.post('/api/admin/products/bulk-apply', json={
        'previewId': preview['previewId'], 'idempotencyKey': 'apply-override',
    }).json()
    assert repo.get_product('a').price_override == 510
    response = authenticated_client.post('/api/admin/operations/' + applied['operationId'] + '/undo',
                                         json={'idempotencyKey': 'undo-override'})
    assert response.status_code == 200
    restored = repo.get_product('a')
    assert restored.display_price == 500
    assert restored.price_override is None
    assert restored.override_origin == ''


def test_bulk_database_failure_rolls_back_products_and_log(repo, authenticated_client):
    for key in ('a', 'b'):
        repo.upsert_product(_product(key, visible=True, display_price=500))
    client = TestClient(authenticated_client.app, raise_server_exceptions=False)
    assert client.post('/api/admin/login', json={'password': 'admin-pass'}).status_code == 200
    preview = client.post('/api/admin/products/bulk-preview', json={
        'scope': 'all', 'operation': 'price', 'amount': 10,
    }).json()
    with repo._get_connection() as conn:
        conn.execute("""create trigger reject_second_product before update on showcase_products
            when new.product_id='b' begin select raise(abort, 'injected failure'); end""")
    response = client.post('/api/admin/products/bulk-apply', json={
        'previewId': preview['previewId'], 'idempotencyKey': 'rollback',
    })
    assert response.status_code == 500
    assert repo.get_product('a').display_price == 500
    assert repo.get_product('b').display_price == 500
    assert repo.list_admin_operations() == []


def test_bulk_executes_only_changed_items_and_records_human_readable_summary(
    repo, authenticated_client,
):
    repo.upsert_product(_product('changed', visible=True, display_price=200))
    repo.upsert_product(_product('same', visible=True, display_price=230))
    repo.upsert_product(replace(
        _product('sold', visible=True, display_price=200), sold=True,
    ))

    preview = authenticated_client.post('/api/admin/products/bulk-preview', json={
        'scope': 'all',
        'operation': 'price',
        'priceMode': 'fixed_final',
        'amount': 230,
        'filters': {'priceMax': 300, 'visible': True, 'sold': False},
    })

    assert preview.status_code == 200
    assert preview.json()['matchedCount'] == 3
    assert preview.json()['changedCount'] == 1

    applied = authenticated_client.post('/api/admin/products/bulk-apply', json={
        'previewId': preview.json()['previewId'],
        'idempotencyKey': 'changed-only',
    })

    assert applied.status_code == 200, applied.text
    assert applied.json()['updatedCount'] == 1
    operations = authenticated_client.get('/api/admin/operations').json()['operations']
    assert operations[0]['summary'] == '全部库存 · 300元以内 · 固定为230元 · 修改 1 台'
    assert 'scope=all' in operations[0]['filterText']
    assert 'priceMax=300' in operations[0]['filterText']
    assert 'visible=true' in operations[0]['filterText']
    assert 'sold=false' in operations[0]['filterText']


def test_bulk_show_skips_sold_item_but_applies_unsold_item(repo, authenticated_client):
    repo.upsert_product(_product('unsold', visible=False, display_price=200))
    repo.upsert_product(replace(
        _product('sold', visible=False, display_price=200), sold=True,
    ))

    preview = authenticated_client.post('/api/admin/products/bulk-preview', json={
        'scope': 'all',
        'operation': 'show',
        'filters': {'visible': False},
    })

    assert preview.status_code == 200
    assert preview.json()['changedCount'] == 1
    assert preview.json()['skippedCount'] == 1
    assert preview.json()['skipReasons'] == {'已售商品不能直接显示': 1}

    applied = authenticated_client.post('/api/admin/products/bulk-apply', json={
        'previewId': preview.json()['previewId'],
        'idempotencyKey': 'show-unsold-only',
    })

    assert applied.status_code == 200, applied.text
    assert applied.json()['updatedCount'] == 1
    assert repo.get_product('unsold').visible is True
    assert repo.get_product('sold').visible is False


def test_bulk_hide_can_be_undone_and_restores_visibility(repo, authenticated_client):
    repo.upsert_product(_product('visible', visible=True, display_price=200))
    preview = authenticated_client.post('/api/admin/products/bulk-preview', json={
        'scope': 'selected',
        'operation': 'hide',
        'productIds': ['visible'],
    }).json()
    applied = authenticated_client.post('/api/admin/products/bulk-apply', json={
        'previewId': preview['previewId'],
        'idempotencyKey': 'hide-visible',
    })
    assert applied.status_code == 200
    assert repo.get_product('visible').visible is False

    undone = authenticated_client.post(
        '/api/admin/operations/' + applied.json()['operationId'] + '/undo',
        json={'idempotencyKey': 'undo-hide-visible'},
    )

    assert undone.status_code == 200, undone.text
    assert undone.json()['updatedCount'] == 1
    assert repo.get_product('visible').visible is True
    with repo._get_connection() as conn:
        original_log = conn.execute(
            '''SELECT summary, filter_text, undone_at
               FROM showcase_admin_operation_logs WHERE operation_id=?''',
            (applied.json()['operationId'],),
        ).fetchone()
        undo_log = conn.execute(
            '''SELECT summary, filter_text, parent_operation_id
               FROM showcase_admin_operation_logs WHERE operation_id=?''',
            (undone.json()['operationId'],),
        ).fetchone()
    assert original_log[2]
    assert undo_log[0] == f"撤销：{original_log[0]}"
    assert undo_log[1] == original_log[1]
    assert undo_log[2] == applied.json()['operationId']


def test_bulk_undo_rejects_showing_sold_product_without_partial_updates(
    repo, authenticated_client,
):
    repo.upsert_product(_product('a-unsold', visible=True, display_price=200))
    repo.upsert_product(replace(
        _product('z-sold', visible=True, display_price=200), sold=True,
    ))
    preview = authenticated_client.post('/api/admin/products/bulk-preview', json={
        'scope': 'selected',
        'operation': 'hide',
        'productIds': ['a-unsold', 'z-sold'],
    }).json()
    applied = authenticated_client.post('/api/admin/products/bulk-apply', json={
        'previewId': preview['previewId'],
        'idempotencyKey': 'hide-sold-and-unsold',
    })
    assert applied.status_code == 200
    assert applied.json()['updatedCount'] == 2
    assert repo.get_product('a-unsold').visible is False
    assert repo.get_product('z-sold').visible is False

    undone = authenticated_client.post(
        '/api/admin/operations/' + applied.json()['operationId'] + '/undo',
        json={'idempotencyKey': 'reject-undo-show-sold'},
    )

    assert undone.status_code == 409
    assert repo.get_product('a-unsold').visible is False
    assert repo.get_product('z-sold').visible is False
    operations = repo.list_admin_operations()
    assert len(operations) == 1
    assert operations[0].operation_id == applied.json()['operationId']
    assert operations[0].undone_at == ''


@pytest.mark.parametrize(
    ('price_min', 'price_max', 'expected'),
    [
        (None, 200, '200元以内'),
        (201, 300, '201～300 元'),
        (801, None, '801元以上'),
        (None, None, '全部价格'),
    ],
)
def test_bulk_price_range_text_is_human_readable(price_min, price_max, expected):
    filters = showcase_api.AdminBulkProductFilters(
        priceMin=price_min,
        priceMax=price_max,
    )

    assert hasattr(showcase_api, '_bulk_price_range_text')
    assert showcase_api._bulk_price_range_text(filters) == expected


@pytest.mark.parametrize(
    ('price_mode', 'amount', 'action_text'),
    [
        ('fixed_final', 230, '固定为230元'),
        ('decrement', 10, '减价10元'),
        ('increment', 10, '加价10元'),
    ],
)
def test_bulk_price_action_text_has_no_extra_spaces(price_mode, amount, action_text):
    request = showcase_api.AdminBulkOperationRequest(
        scope='all',
        operation='price',
        priceMode=price_mode,
        amount=amount,
    )

    assert showcase_api._bulk_operation_summary(request, 1) == (
        f'全部库存 · 全部价格 · {action_text} · 修改 1 台'
    )


def test_manual_override_can_reset_to_source_and_missing_items_are_filterable(repo, authenticated_client):
    product = replace(_product('a', visible=True, display_price=500),
                      source_display_price=450, review_state='missing', source_available=False)
    repo.upsert_product(product)
    current = repo.get_product('a')
    changed = authenticated_client.patch('/api/admin/products/' + current.public_id, json={
        'displayPrice': 510, 'expectedVersion': current.row_version,
    })
    assert changed.status_code == 200
    reset = authenticated_client.patch('/api/admin/products/' + current.public_id, json={
        'expectedVersion': changed.json()['rowVersion'], 'resetOverrides': ['price'],
    })
    assert reset.status_code == 200
    restored = repo.get_product('a')
    assert restored.display_price == 450
    assert restored.price_override is None
    filtered = authenticated_client.get('/api/admin/products', params={'reviewState': 'missing'})
    assert [item['productId'] for item in filtered.json()['products']] == ['a']
    assert filtered.json()['products'][0]['sourceAvailable'] is False
