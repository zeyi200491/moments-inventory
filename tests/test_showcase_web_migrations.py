from uuid import UUID
import sqlite3

import pytest

from moments_inventory.showcase_web.repository import SQLiteShowcaseRepository
from moments_inventory.showcase_web.models import ShowcaseProduct, ShowcaseProductImage


def product(key="p1"):
    return ShowcaseProduct(key, "佳能", "佳能", 100, 200, True, False, "", "", "", "", "", "", "")


def test_reads_and_reinitialize_do_not_reseed_or_write(tmp_path):
    path = tmp_path / "showcase.db"
    repo = SQLiteShowcaseRepository(path)
    repo.initialize()
    repo.delete_purchase_step("choose-model")
    repo.delete_gallery_album("camera-real")
    statements = []
    repo._get_connection().set_trace_callback(statements.append)
    repo.list_products()
    repo.list_purchase_steps()
    repo.initialize()
    assert not any(s.lstrip().lower().startswith(("create", "insert", "alter")) for s in statements)
    repo.close()
    repo = SQLiteShowcaseRepository(path)
    assert repo.get_purchase_step("choose-model") is None
    assert repo.get_gallery_album("camera-real") is None


def test_public_id_and_versions_survive_upsert_and_import():
    repo = SQLiteShowcaseRepository(":memory:")
    item = product()
    repo.upsert_product(item)
    saved = repo.get_product("p1")
    UUID(saved.public_id)
    assert repo.get_product(saved.public_id).product_id == "p1"
    version = saved.row_version
    repo.upsert_product(product())
    saved2 = repo.get_product("p1")
    assert saved2.public_id == saved.public_id
    assert saved2.row_version == version + 1
    repo.bulk_upsert_products_with_body_images([product()], {})
    saved3 = repo.get_product("p1")
    assert saved3.public_id == saved.public_id
    assert saved3.row_version == version + 2
    repo.update_product_price("p1", 300)
    repo.set_product_visibility("p1", False)
    assert repo.get_product("p1").row_version == version + 4
    assert int(repo.get_setting("catalog_revision")) >= 5


def test_scoped_auto_images_preserve_manual_and_unknown():
    repo = SQLiteShowcaseRepository(":memory:")
    for key in ("p1", "p2"):
        repo.upsert_product(product(key))
        repo.add_product_image(key+"-auto", key, "old.jpg", "sample", 0, False, source="auto_match")
    repo.add_product_image("manual", "p1", "manual.jpg", "sample", 1, False)
    repo.add_product_image("legacy", "p1", "legacy.jpg", "sample", 2, False, source="legacy_unknown")
    repo.replace_product_images_by_type("sample", [], product_ids=["p1"])
    assert {i.image_id for i in repo.list_product_images("p1")} == {"manual", "legacy"}
    assert repo.get_product_image("p2-auto").source == "auto_match"


def test_deleting_cover_repairs_product_and_version():
    repo = SQLiteShowcaseRepository(":memory:")
    repo.upsert_product(product())
    repo.add_product_image("cover", "p1", "cover.jpg", "body", 0, True)
    repo.set_product_cover_image("p1", "cover")
    before = repo.get_product("p1").row_version
    assert repo.delete_product_image("p1", "cover")
    assert repo.get_product("p1").cover_image_path == ""
    assert repo.get_product("p1").row_version > before


def test_deleting_product_cleans_live_relations_but_keeps_audit_snapshot():
    repo = SQLiteShowcaseRepository(":memory:")
    repo.upsert_product(product())
    with repo._get_connection() as conn:
        conn.execute("insert into showcase_sections values ('s','S','',1,0,'','')")
        conn.execute("insert into showcase_section_items values ('i','s','p1',0,'','','')")
        conn.execute(
            "insert into showcase_admin_operation_logs values ('op','price','summary','',1,'','', '')"
        )
        conn.execute(
            """insert into showcase_admin_operation_items
            (item_id,operation_id,product_id) values ('item','op','p1')"""
        )

    assert repo.delete_product("p1") is True
    assert repo.get_product("p1") is None
    with repo._get_connection() as conn:
        assert conn.execute("select count(*) from showcase_section_items").fetchone()[0] == 0
        assert conn.execute(
            "select product_id from showcase_admin_operation_items where item_id='item'"
        ).fetchone()[0] == "p1"


def test_old_database_migrates_without_seeding_and_classifies_known_images(tmp_path):
    import sqlite3
    path = tmp_path / "legacy.db"
    with sqlite3.connect(path) as conn:
        conn.execute("""create table showcase_products (
          product_id text primary key,model text not null,brand text not null,
          cost_price integer not null,display_price integer not null,visible integer not null,
          sold integer not null,published_at text not null,raw_copy text not null,
          display_copy text not null,cover_image_path text not null,created_at text not null,
          updated_at text not null,last_seen_import_id text not null)""")
        conn.execute("insert into showcase_products values ('old','model','brand',1,2,1,0,'','','','','','','')")
        conn.execute("""create table showcase_product_images (
            image_id text primary key, product_id text,image_path text,image_type text,
            sort_order integer,is_cover integer)""")
        conn.execute("insert into showcase_product_images values ('known','old','sample-images/a.jpg','sample',0,0)")
        conn.execute("insert into showcase_product_images values ('unknown','old','other/a.jpg','sample',1,0)")
    repo = SQLiteShowcaseRepository(path)
    first = repo.get_product("old")
    UUID(first.public_id)
    assert repo.get_product_image("known").source == "auto_match"
    assert repo.get_product_image("unknown").source == "legacy_unknown"
    assert repo.list_purchase_steps() == []
    repo.close()
    repo = SQLiteShowcaseRepository(path)
    assert repo.get_product("old").public_id == first.public_id


def test_stable_product_key_migration_is_optional_and_unique_per_scope(tmp_path):
    repo = SQLiteShowcaseRepository(tmp_path / "identity.db")
    repo.upsert_product(product("p1"))
    with repo._get_connection() as conn:
        columns = {row[1] for row in conn.execute("pragma table_info(showcase_products)")}
        conn.execute("update showcase_products set source_product_key='media:key-1' where product_id='p1'")
        if "source_product_key" in columns:
            with pytest.raises(sqlite3.IntegrityError):
                conn.execute("insert into showcase_products (product_id,model,brand,cost_price,display_price,visible,sold,published_at,raw_copy,display_copy,cover_image_path,created_at,updated_at,last_seen_import_id,source_scope,source_product_key) values ('p2','m','b',1,1,1,0,'','','','','','','','default','media:key-1')")
    assert "source_product_key" in columns
    assert repo.list_product_ids() == {"p1"}  # 迁移本身不擅自回填或删除旧记录。


def test_import_review_migration_adds_constrained_tables_and_is_repeatable(tmp_path):
    repo = SQLiteShowcaseRepository(tmp_path / "import-review.db")
    repo.initialize()
    conn = repo._get_connection()
    tables = {
        row[0]
        for row in conn.execute(
            "select name from sqlite_master where type='table'"
        )
    }
    assert {
        "showcase_import_review_batches",
        "showcase_import_review_rows",
        "showcase_source_identity_aliases",
    } <= tables
    assert conn.execute(
        "select version from showcase_schema_migrations order by version desc limit 1"
    ).fetchone()[0] == 14
    batch_columns = {
        row[1] for row in conn.execute("pragma table_info(showcase_import_review_batches)")
    }
    assert {
        "mode",
        "complete",
        "source_path",
        "parsed_row_count",
        "missing_count",
        "idempotency_key",
        "result_json",
    } <= batch_columns
    row_columns = {
        row[1] for row in conn.execute("pragma table_info(showcase_import_review_rows)")
    }
    assert "row_number" in row_columns
    assert "target_row_version" in row_columns

    conn.execute(
        """insert into showcase_import_review_batches
        (batch_id, source_scope, mode, complete, source_path, parsed_row_count,
         missing_count, idempotency_key, result_json, status, created_at)
        values ('batch-1','scope-a','full',1,'input.xlsx',3,1,'idem-1','{"ok":true}','pending','now')"""
    )
    conn.execute(
        """insert into showcase_import_review_batches
        (batch_id, source_scope, mode, idempotency_key, status, created_at)
        values ('batch-2','scope-a','full','idem-1','pending','now')"""
    )
    repo.upsert_product(product("p1"))
    conn.execute(
        """insert into showcase_import_review_rows
        (review_row_id, batch_id, row_number, source_key, status, decision,
         product_id, target_row_version, snapshot_json, created_at)
        values ('row-1','batch-1',1,'item-1','pending','link','p1',7,'{}','now')"""
    )
    assert conn.execute(
        "select target_row_version from showcase_import_review_rows where review_row_id='row-1'"
    ).fetchone()[0] == 7
    conn.execute(
        """insert into showcase_import_review_rows
        (review_row_id, batch_id, row_number, source_key, status, snapshot_json, created_at)
        values ('row-duplicate-source','batch-1',2,'item-1','pending','{}','now')"""
    )
    assert conn.execute(
        "select count(*) from showcase_import_review_rows where batch_id='batch-1' and source_key='item-1'"
    ).fetchone()[0] == 2
    conn.execute(
        """insert into showcase_import_review_rows
        (review_row_id, batch_id, row_number, source_key, status, decision,
         product_id, target_row_version, snapshot_json, created_at)
        values ('row-committed','batch-1',3,'item-3','committed','link','p1',8,'{}','now')"""
    )
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            """insert into showcase_import_review_rows
            (review_row_id, batch_id, row_number, source_key, status, snapshot_json, created_at)
            values ('row-duplicate','batch-1',1,'other-item','pending','{}','now')"""
        )
    conn.execute(
        """insert into showcase_source_identity_aliases
        (alias_id, source_scope, source_key, product_id, created_at)
        values ('alias-1','scope-a','item-1','p1','now')"""
    )
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            """insert into showcase_source_identity_aliases
            (alias_id, source_scope, source_key, product_id, created_at)
            values ('alias-2','scope-a','item-1','p1','now')"""
        )
    conn.execute(
        """insert into showcase_source_identity_aliases
        (alias_id, source_scope, source_key, product_id, created_at)
        values ('alias-3','scope-b','item-1','p1','now')"""
    )
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            """insert into showcase_import_review_rows
            (review_row_id, batch_id, row_number, source_key, status, decision, snapshot_json, created_at)
            values ('row-2','batch-1',4,'item-2','waiting','skip','{}','now')"""
        )
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            """insert into showcase_import_review_rows
            (review_row_id, batch_id, row_number, source_key, status, decision, snapshot_json, created_at)
            values ('row-3','batch-1',5,'item-3','pending','merge','{}','now')"""
        )
    before = {
        table: conn.execute(f"select * from {table} order by 1").fetchall()
        for table in (
            "showcase_import_review_batches",
            "showcase_import_review_rows",
            "showcase_source_identity_aliases",
        )
    }
    from moments_inventory.showcase_web.migrations import migrate

    migrate(conn)
    after = {
        table: conn.execute(f"select * from {table} order by 1").fetchall()
        for table in before
    }
    assert after == before
    assert conn.execute(
        "select version from showcase_schema_migrations order by version desc limit 1"
    ).fetchone()[0] == 14

    conn.execute("delete from showcase_products where product_id='p1'")
    deleted_target = conn.execute(
        "select product_id,target_row_version,decision from showcase_import_review_rows where review_row_id='row-1'"
    ).fetchone()
    assert tuple(deleted_target) == (None, None, None)
    committed_audit = conn.execute(
        "select product_id,target_row_version,decision from showcase_import_review_rows where review_row_id='row-committed'"
    ).fetchone()
    assert tuple(committed_audit) == (None, 8, "link")


def test_migration_13_moves_legacy_bulk_preview_and_idempotency_to_shared_admin(tmp_path):
    repo = SQLiteShowcaseRepository(tmp_path / "bulk-owner-migration.db")
    repo.initialize()
    conn = repo._get_connection()
    conn.execute(
        """insert into showcase_bulk_previews
        (preview_id,owner,request_json,items_json,expires_at,operation_id)
        values ('legacy-preview','old-session','{}','[]','2099-01-01T00:00:00+00:00','')"""
    )
    conn.execute(
        "insert into showcase_idempotency (idempotency_key,owner,request_hash,response_json) values ('legacy-key','old-session','fingerprint','{}')"
    )
    conn.execute("delete from showcase_schema_migrations where version=13")

    from moments_inventory.showcase_web.migrations import migrate
    migrate(conn)

    assert conn.execute("select owner from showcase_bulk_previews where preview_id='legacy-preview'").fetchone()[0] == "shared-admin"
    assert conn.execute("select owner from showcase_idempotency where idempotency_key='legacy-key'").fetchone()[0] == "shared-admin"


def test_migration_14_adds_idempotency_created_at_for_existing_cache_rows(tmp_path):
    from moments_inventory.showcase_web.migrations import migrate

    conn = sqlite3.connect(tmp_path / "idempotency-retention.db")
    conn.execute("create table showcase_schema_migrations (version integer primary key, applied_at text not null default '')")
    conn.executemany("insert into showcase_schema_migrations(version) values (?)", [(version,) for version in range(1, 14)])
    conn.execute("create table showcase_admin_operation_logs (operation_id text primary key, created_at text not null, parent_operation_id text not null default '')")
    conn.execute("create table showcase_idempotency (idempotency_key text primary key, owner text not null, request_hash text not null, response_json text not null)")
    conn.execute("insert into showcase_idempotency values ('legacy-key','shared-admin','fingerprint','{}')")

    migrate(conn)

    columns = {row[1] for row in conn.execute("pragma table_info(showcase_idempotency)")}
    created_at = conn.execute(
        "select created_at from showcase_idempotency where idempotency_key='legacy-key'"
    ).fetchone()[0]
    assert "created_at" in columns
    assert created_at
    indexes = {
        row[0] for row in conn.execute(
            "select name from sqlite_master where type='index'"
        )
    }
    assert {
        "idx_showcase_admin_operation_logs_created",
        "idx_showcase_admin_operation_logs_parent",
        "idx_showcase_idempotency_created",
    } <= indexes
    assert conn.execute("select max(version) from showcase_schema_migrations").fetchone()[0] == 14
    conn.close()


def test_public_ids_work_for_image_and_product_changes():
    repo = SQLiteShowcaseRepository(":memory:")
    repo.upsert_product(product())
    public_id = repo.get_product("p1").public_id
    repo.add_product_image("one", public_id, "one.jpg", "sample", 1, False)
    repo.add_product_image("two", public_id, "two.jpg", "sample", 2, False)
    assert len(repo.list_product_images(public_id)) == 2
    repo.reorder_product_images(public_id, ["two", "one"])
    assert repo.list_product_images(public_id)[0].image_id == "two"
    assert repo.set_product_cover_image(public_id, "two")
    assert repo.delete_product_image(public_id, "two")
    assert repo.get_product(public_id).cover_image_path == "one.jpg"
    assert repo.list_product_images(public_id)[0].is_cover
    repo.update_product_price(public_id, 400)
    repo.set_product_visibility(public_id, False)
    assert repo.get_product(public_id).display_price == 400
    assert not repo.get_product(public_id).visible
    assert repo.delete_product(public_id)


def test_explicit_version_increment_is_not_doubled():
    repo = SQLiteShowcaseRepository(":memory:")
    repo.upsert_product(product())
    with repo._get_connection() as conn:
        conn.execute("update showcase_products set row_version=row_version+1, display_price=300 where product_id='p1'")
    assert repo.get_product("p1").row_version == 1


def test_import_source_fields_are_loaded_and_legacy_values_preserved(tmp_path):
    repo = SQLiteShowcaseRepository(tmp_path / "db")
    repo.upsert_product(product())
    with repo._get_connection() as conn:
        conn.execute("update showcase_products set source_scope='scope-a',source_display_price=123,price_override=250,override_origin='manual' where product_id='p1'")
    saved = repo.get_product("p1")
    assert saved.source_scope == "scope-a"
    assert saved.source_display_price == 123
    assert saved.price_override == 250
    assert saved.override_origin == "manual"
    assert repo.search_admin_products().products[0].product.source_scope == "scope-a"


def test_tag_search_pages_in_sql_and_counts_exact_tags():
    from moments_inventory.showcase_web.models import ShowcaseProductSearch
    repo = SQLiteShowcaseRepository(":memory:")
    for index in range(12):
        item = product(str(index))
        item.recommend_tags = "custom-tag" if index < 10 else "custom-tag-extra"
        repo.upsert_product(item)
    statements = []
    repo._get_connection().set_trace_callback(statements.append)
    result = repo.search_products(ShowcaseProductSearch(tags=("custom-tag",),limit=2,offset=2))
    assert result.total == 10
    assert len(result.products) == 2
    product_selects = [s.lower() for s in statements if "select product_id," in s.lower()]
    assert product_selects and all(" limit " in s for s in product_selects)


def test_image_lookup_chunks_large_selection():
    repo = SQLiteShowcaseRepository(":memory:")
    repo.upsert_product(product())
    repo.add_product_image("i", "p1", "first.jpg", "sample", 0, False)
    import sqlite3
    repo._get_connection().setlimit(sqlite3.SQLITE_LIMIT_VARIABLE_NUMBER, 999)
    ids = ["p1"] + ["missing"+str(i) for i in range(1200)]
    assert repo.list_first_image_paths_by_type_for_products("sample", ids) == {"p1": "first.jpg"}


def test_shared_sample_groups_store_once_and_merge_with_manual_images():
    from moments_inventory.showcase_web.models import ShowcaseAdminProductSearch
    repo = SQLiteShowcaseRepository(":memory:")
    for key in ("p1", "p2"):
        repo.upsert_product(product(key))
    repo.add_product_image("manual", "p1", "manual.jpg", "sample", 0, False)
    repo.replace_sample_group_links({"folder": ["sample-images/1.jpg", "sample-images/2.jpg"]}, {"p1": "folder", "p2": "folder"})
    assert len(repo.list_product_images("p1")) == 3
    assert len(repo.list_product_images("p2")) == 2
    assert repo._get_connection().execute("select count(*) from showcase_sample_group_images").fetchone()[0] == 2
    assert repo.list_first_image_paths_by_type_for_products("sample", ["p2"]) == {"p2": "sample-images/1.jpg"}
    assert repo.search_admin_products(ShowcaseAdminProductSearch(has_sample_image=True)).total == 2
    virtual = repo.list_product_images("p2")[0]
    assert repo.get_product_image(virtual.image_id).image_path == virtual.image_path
    repo.replace_sample_group_links({}, {}, product_ids=["p1"])
    assert [i.image_id for i in repo.list_product_images("p1")] == ["manual"]
    assert len(repo.list_product_images("p2")) == 2


def test_shared_sample_rebuild_is_stable_and_removes_old_auto_only():
    repo = SQLiteShowcaseRepository(":memory:")
    repo.upsert_product(product())
    repo.add_product_image("old", "p1", "old.jpg", "sample", 0, False, source="auto_match")
    repo.replace_sample_group_links({"folder": ["sample-images/1.jpg"]}, {"p1": "folder"})
    first = repo.list_product_images("p1")
    repo.replace_sample_group_links({"folder": ["sample-images/1.jpg"]}, {"p1": "folder"})
    assert repo.list_product_images("p1") == first
    assert len(first) == 1


def test_partial_shared_refresh_does_not_change_other_product_images():
    repo = SQLiteShowcaseRepository(":memory:")
    for key in ("p1", "p2"):
        repo.upsert_product(product(key))
    repo.replace_sample_group_links({"folder": ["old.jpg"]}, {"p1": "folder", "p2": "folder"})
    repo.replace_sample_group_links({"folder": ["new.jpg"]}, {"p1": "folder"}, product_ids=["p1"])
    assert repo.list_product_images("p1")[0].image_path == "new.jpg"
    assert repo.list_product_images("p2")[0].image_path == "old.jpg"


def test_shared_image_delete_reorder_and_cover_are_product_scoped():
    repo = SQLiteShowcaseRepository(":memory:")
    for key in ("p1", "p2"):
        repo.upsert_product(product(key))
    repo.replace_sample_group_links({"folder": ["one.jpg", "two.jpg"]}, {"p1": "folder", "p2": "folder"})
    first, second = repo.list_product_images("p1")
    repo.reorder_product_images("p1", [second.image_id, first.image_id])
    assert repo.list_product_images("p1")[0].image_id == second.image_id
    assert repo.set_product_cover_image("p1", second.image_id)
    assert repo.get_product_image(second.image_id).is_cover
    assert not repo.delete_product_image("p2", second.image_id)
    assert repo.delete_product_image("p1", second.image_id)
    assert len(repo.list_product_images("p1")) == 1
    assert len(repo.list_product_images("p2")) == 2
    assert repo.get_product("p1").cover_image_path == "one.jpg"


def test_repository_concurrent_reads_and_price_updates_keep_versions():
    from concurrent.futures import ThreadPoolExecutor
    repo = SQLiteShowcaseRepository(":memory:")
    repo.upsert_product(product())
    def run(index):
        if index % 2:
            repo.update_product_price("p1", index)
        else:
            assert repo.get_product("p1") is not None
    with ThreadPoolExecutor(max_workers=8) as executor:
        list(executor.map(run, range(100)))
    assert repo.get_product("p1").row_version == 50


def test_materialized_tags_follow_text_changes_and_delete():
    from moments_inventory.showcase_web.models import ShowcaseProductSearch
    repo = SQLiteShowcaseRepository(":memory:")
    item = product()
    item.recommend_tags = "custom-tag"
    repo.upsert_product(item)
    assert repo._get_connection().execute("select tag from showcase_product_tags where product_id='p1'").fetchone()[0] == "custom-tag"
    with repo._get_connection() as conn:
        conn.execute("update showcase_products set recommend_tags='other' where product_id='p1'")
    assert repo.search_products(ShowcaseProductSearch(tags=("custom-tag",))).total == 0
    assert repo.search_products(ShowcaseProductSearch(tags=("other",))).total == 1
    repo.delete_product("p1")
    assert repo._get_connection().execute("select count(*) from showcase_product_tags").fetchone()[0] == 0
