from dataclasses import replace
from fastapi.testclient import TestClient

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
