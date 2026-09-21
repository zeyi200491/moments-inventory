from __future__ import annotations

import sqlite3
from uuid import uuid4


def _ensure_column(conn, table_name, column_name, declaration):
    if column_name not in {row[1] for row in conn.execute(f"pragma table_info({table_name})")}:
        conn.execute(f"alter table {table_name} add column {column_name} {declaration}")


def migrate(conn: sqlite3.Connection) -> bool:
    """事务内迁移；返回是否为首次创建数据库，默认内容仅在首次创建时播种。"""
    fresh = conn.execute("select 1 from sqlite_master where name='showcase_products'").fetchone() is None
    conn.execute("create table if not exists showcase_schema_migrations (version integer primary key, applied_at text not null default (datetime('now')))")
    applied = {row[0] for row in conn.execute("select version from showcase_schema_migrations")}
    if 1 not in applied:
        conn.execute(
            """
            create table if not exists showcase_products (
              product_id text primary key,
              model text not null,
              brand text not null,
              cost_price integer not null,
              display_price integer not null,
              visible integer not null,
              sold integer not null,
              published_at text not null,
              raw_copy text not null,
              display_copy text not null,
              cover_image_path text not null,
              created_at text not null,
              updated_at text not null,
              last_seen_import_id text not null,
              short_selling_point text not null default '',
              recommend_tags text not null default ''
            )
            """
        )
        _ensure_column(conn, "showcase_products", "short_selling_point", "text not null default ''")
        _ensure_column(conn, "showcase_products", "recommend_tags", "text not null default ''")
        conn.execute(
            """
            create index if not exists idx_showcase_products_public
            on showcase_products(visible, sold, published_at)
            """
        )
        conn.execute(
            """
            create index if not exists idx_showcase_products_brand_price
            on showcase_products(brand, display_price)
            """
        )
        conn.execute(
            """
            create table if not exists showcase_product_images (
              image_id text primary key,
              product_id text not null,
              image_path text not null,
              image_type text not null,
              sort_order integer not null,
              is_cover integer not null,
              foreign key(product_id) references showcase_products(product_id)
            )
            """
        )
        conn.execute(
            """
            create index if not exists idx_showcase_product_images_product_type
            on showcase_product_images(product_id, image_type)
            """
        )
        conn.execute(
            """
            create table if not exists showcase_sections (
              section_id text primary key,
              title text not null,
              subtitle text not null,
              active integer not null,
              sort_order integer not null,
              created_at text not null,
              updated_at text not null
            )
            """
        )
        conn.execute(
            """
            create table if not exists showcase_section_items (
              item_id text primary key,
              section_id text not null,
              product_id text not null,
              sort_order integer not null,
              recommend_note text not null,
              created_at text not null,
              updated_at text not null,
              foreign key(section_id) references showcase_sections(section_id),
              foreign key(product_id) references showcase_products(product_id)
            )
            """
        )
        conn.execute(
            """
            create table if not exists showcase_settings (
              setting_key text primary key,
              setting_value text not null
            )
            """
        )
        conn.execute(
            """
            create table if not exists showcase_authorized_partners (
              partner_id text primary key,
              name text not null,
              note text not null,
              sort_order integer not null,
              active integer not null
            )
            """
        )
        conn.execute(
            """
            create table if not exists showcase_import_logs (
              import_id text primary key,
              source_path text not null,
              imported_at text not null,
              inserted_count integer not null,
              updated_count integer not null,
              missing_count integer not null
            )
            """
        )
        conn.execute(
            """
            create table if not exists showcase_admin_sessions (
              session_id text primary key,
              expires_at text not null
            )
            """
        )
        conn.execute(
            """
            create table if not exists showcase_customer_sessions (
              session_id text primary key,
              expires_at text not null
            )
            """
        )
        conn.execute(
            """
            create table if not exists showcase_admin_operation_logs (
              operation_id text primary key,
              operation_type text not null,
              summary text not null,
              filter_text text not null,
              updated_count integer not null,
              created_at text not null,
              undone_at text not null default ''
            )
            """
        )
        conn.execute(
            """
            create table if not exists showcase_admin_operation_items (
              item_id text primary key,
              operation_id text not null,
              product_id text not null,
              old_price integer,
              new_price integer,
              old_visible integer,
              new_visible integer,
              foreign key(operation_id) references showcase_admin_operation_logs(operation_id),
              foreign key(product_id) references showcase_products(product_id)
            )
            """
        )
        conn.execute(
            """
            create table if not exists showcase_sample_folder_bindings (
              binding_key text primary key,
              product_id text not null default '',
              model_key text not null default '',
              brand text not null default '',
              folder_path text not null,
              created_at text not null,
              updated_at text not null
            )
            """
        )
        conn.execute(
            """
            create table if not exists showcase_gallery_albums (
              album_id text primary key,
              title text not null,
              description text not null,
              sort_order integer not null,
              is_visible integer not null,
              created_at text not null,
              updated_at text not null
            )
            """
        )
        conn.execute(
            """
            create table if not exists showcase_gallery_images (
              image_id text primary key,
              album_id text not null,
              image_path text not null,
              caption text not null,
              sort_order integer not null,
              is_visible integer not null,
              created_at text not null,
              updated_at text not null,
              foreign key(album_id) references showcase_gallery_albums(album_id)
            )
            """
        )
        conn.execute(
            """
            create index if not exists idx_showcase_gallery_images_album
            on showcase_gallery_images(album_id, is_visible, sort_order)
            """
        )
        conn.execute(
            """
            create table if not exists showcase_purchase_steps (
              step_id text primary key,
              title text not null,
              description text not null,
              sort_order integer not null,
              is_visible integer not null,
              created_at text not null,
              updated_at text not null
            )
            """
        )
        conn.execute(
            """
            create index if not exists idx_showcase_purchase_steps_public
            on showcase_purchase_steps(is_visible, sort_order)
            """
        )
        conn.execute("insert into showcase_schema_migrations(version) values (1)")
    if 2 not in applied:
        _ensure_column(conn, "showcase_products", "public_id", "text not null default ''")
        _ensure_column(conn, "showcase_products", "row_version", "integer not null default 0")
        for (key,) in conn.execute("select product_id from showcase_products where public_id = ''").fetchall():
            conn.execute("update showcase_products set public_id=? where product_id=?", (str(uuid4()), key))
        conn.execute("create unique index if not exists idx_showcase_products_public_id on showcase_products(public_id)")
        _ensure_column(conn, "showcase_product_images", "source", "text not null default 'legacy_unknown'")
        conn.execute("update showcase_product_images set source='auto_match' where replace(image_path, char(92), '/') like 'sample-images/%' or replace(image_path, char(92), '/') like '%/sample-images/%'")
        conn.execute("insert or ignore into showcase_settings values ('catalog_revision', '0')")
        conn.execute("""create trigger if not exists showcase_product_version after update on showcase_products
            when new.row_version = old.row_version
            begin update showcase_products set row_version=old.row_version+1 where product_id=new.product_id; end""")
        for event in ("insert", "update", "delete"):
            conn.execute(f"""create trigger if not exists showcase_revision_{event} after {event} on showcase_products
                begin update showcase_settings set setting_value=cast(setting_value as integer)+1 where setting_key='catalog_revision'; end""")
        conn.execute("create table if not exists showcase_bulk_previews (preview_id text primary key, owner text not null, request_json text not null, items_json text not null, expires_at text not null, operation_id text not null default '')")
        conn.execute("create table if not exists showcase_idempotency (idempotency_key text primary key, owner text not null, request_hash text not null, response_json text not null)")
        _ensure_column(conn, "showcase_admin_operation_items", "old_version", "integer")
        _ensure_column(conn, "showcase_admin_operation_items", "new_version", "integer")
        _ensure_column(conn, "showcase_admin_operation_logs", "parent_operation_id", "text not null default ''")
        conn.execute("insert into showcase_schema_migrations(version) values (2)")
    if 3 not in applied:
        _ensure_column(conn, "showcase_products", "source_scope", "text not null default 'default'")
        _ensure_column(conn, "showcase_products", "source_available", 'integer not null default 1')
        _ensure_column(conn, "showcase_products", "source_display_price", 'integer not null default 0')
        _ensure_column(conn, "showcase_products", "source_display_copy", "text not null default ''")
        _ensure_column(conn, "showcase_products", "source_visible", 'integer not null default 1')
        _ensure_column(conn, "showcase_products", "last_seen_at", "text not null default ''")
        _ensure_column(conn, "showcase_products", "price_override", 'integer')
        _ensure_column(conn, "showcase_products", "copy_override", 'text')
        _ensure_column(conn, "showcase_products", "visibility_override", 'integer')
        _ensure_column(conn, "showcase_products", "override_origin", "text not null default ''")
        _ensure_column(conn, "showcase_products", "review_state", "text not null default ''")
        _ensure_column(conn, "showcase_products", "last_verified_at", "text not null default ''")
        conn.execute("""update showcase_products set source_display_price=display_price,
            source_display_copy=display_copy,source_visible=visible,price_override=display_price,
            copy_override=display_copy,visibility_override=visible,override_origin='legacy_preserved'""")
        _ensure_column(conn, "showcase_import_logs", "mode", "text not null default 'incremental'")
        _ensure_column(conn, "showcase_import_logs", "scope", "text not null default 'default'")
        _ensure_column(conn, "showcase_import_logs", "status", "text not null default 'committed'")
        _ensure_column(conn, "showcase_import_logs", "started_at", "text not null default ''")
        _ensure_column(conn, "showcase_import_logs", "committed_at", "text not null default ''")
        _ensure_column(conn, "showcase_import_logs", "source_fingerprint", "text not null default ''")
        conn.execute("create unique index if not exists idx_showcase_import_fingerprint on showcase_import_logs(source_fingerprint,scope,mode) where source_fingerprint<>'' and status='committed'")
        conn.execute("insert into showcase_schema_migrations(version) values (3)")
    if 4 not in applied:
        conn.execute("create index if not exists idx_showcase_products_public_latest on showcase_products(visible,sold,published_at desc,created_at desc,product_id)")
        conn.execute("create index if not exists idx_showcase_products_public_price on showcase_products(visible,sold,display_price,published_at desc,created_at desc,product_id)")
        conn.execute("create index if not exists idx_showcase_product_images_first on showcase_product_images(image_type,product_id,sort_order,image_id)")
        conn.execute("create index if not exists idx_showcase_section_items_product on showcase_section_items(product_id,section_id)")
        conn.execute("insert into showcase_schema_migrations(version) values (4)")
    if 5 not in applied:
        conn.execute("create table if not exists showcase_sample_groups (group_key text primary key)")
        conn.execute("""create table if not exists showcase_sample_group_images (
            image_id text primary key, group_key text not null, image_path text not null,
            sort_order integer not null, unique(group_key,image_path))""")
        conn.execute("""create table if not exists showcase_product_sample_groups (
            product_id text primary key, group_key text not null)""")
        conn.execute("create index if not exists idx_showcase_sample_group_images_order on showcase_sample_group_images(group_key,sort_order,image_id)")
        conn.execute("create index if not exists idx_showcase_product_sample_group on showcase_product_sample_groups(group_key,product_id)")
        conn.execute("""create view if not exists showcase_all_product_images as
            select image_id, product_id, image_path, image_type, sort_order, is_cover, source from showcase_product_images
            union all
            select 'shared:' || links.product_id || ':' || images.image_id,
                links.product_id, images.image_path, 'sample', images.sort_order, 0, 'auto_match'
            from showcase_product_sample_groups links
            join showcase_sample_group_images images on images.group_key=links.group_key""")
        conn.execute("insert into showcase_schema_migrations(version) values (5)")
    if 6 not in applied:
        conn.execute("""create table if not exists showcase_sample_image_overrides (
            product_id text not null, image_id text not null, hidden integer not null default 0,
            sort_order integer, primary key(product_id,image_id))""")
        conn.execute("drop view if exists showcase_all_product_images")
        conn.execute("""create view showcase_all_product_images as
            select image_id, product_id, image_path, image_type, sort_order, is_cover, source from showcase_product_images
            union all
            select 'shared:' || links.product_id || ':' || images.image_id,
                links.product_id, images.image_path, 'sample',
                coalesce(overrides.sort_order,images.sort_order),
                products.cover_image_path=images.image_path, 'auto_match'
            from showcase_product_sample_groups links
            join showcase_products products on products.product_id=links.product_id
            join showcase_sample_group_images images on images.group_key=links.group_key
            left join showcase_sample_image_overrides overrides on overrides.product_id=links.product_id and overrides.image_id=images.image_id
            where coalesce(overrides.hidden,0)=0""")
        conn.execute("insert into showcase_schema_migrations(version) values (6)")
    if 7 not in applied:
        conn.execute("create table if not exists showcase_product_tags (product_id text not null, tag text not null, primary key(product_id,tag))")
        conn.execute("create index if not exists idx_showcase_product_tags_tag on showcase_product_tags(tag,product_id)")
        conn.execute("""insert or ignore into showcase_product_tags
            select product_id, tags.value from showcase_products,
            json_each(showcase_sales_tags(model,brand,raw_copy,display_copy,short_selling_point,recommend_tags)) tags""")
        for event in ("insert", "update of model,brand,raw_copy,display_copy,short_selling_point,recommend_tags"):
            name = event.split()[0]
            conn.execute(f"""create trigger if not exists showcase_tags_{name} after {event} on showcase_products
                begin
                    delete from showcase_product_tags where product_id=new.product_id;
                    insert into showcase_product_tags
                    select new.product_id, value from json_each(showcase_sales_tags(new.model,new.brand,new.raw_copy,new.display_copy,new.short_selling_point,new.recommend_tags));
                end""")
        conn.execute("""create trigger if not exists showcase_tags_delete after delete on showcase_products
            begin delete from showcase_product_tags where product_id=old.product_id; end""")
        conn.execute("insert into showcase_schema_migrations(version) values (7)")
    if 8 not in applied:
        # 撤销时不仅恢复展示值，还要恢复导入覆盖语义，避免后续导入被错误冻结。
        _ensure_column(conn, "showcase_admin_operation_items", "old_price_override", "integer")
        _ensure_column(conn, "showcase_admin_operation_items", "new_price_override", "integer")
        _ensure_column(conn, "showcase_admin_operation_items", "old_visibility_override", "integer")
        _ensure_column(conn, "showcase_admin_operation_items", "new_visibility_override", "integer")
        _ensure_column(conn, "showcase_admin_operation_items", "old_override_origin", "text")
        _ensure_column(conn, "showcase_admin_operation_items", "new_override_origin", "text")
        conn.execute("insert into showcase_schema_migrations(version) values (8)")
    if 9 not in applied:
        # 操作项保存的是审计快照。商品被删除后，历史仍应可查且不应阻止删除。
        operation_columns = {
            row[1] for row in conn.execute("pragma table_info(showcase_admin_operation_items)")
        }
        conn.execute("alter table showcase_admin_operation_items rename to showcase_admin_operation_items_v8")
        conn.execute(
            """
            create table showcase_admin_operation_items (
              item_id text primary key,
              operation_id text not null,
              product_id text not null,
              old_price integer,
              new_price integer,
              old_visible integer,
              new_visible integer,
              old_version integer,
              new_version integer,
              old_price_override integer,
              new_price_override integer,
              old_visibility_override integer,
              new_visibility_override integer,
              old_override_origin text,
              new_override_origin text,
              foreign key(operation_id) references showcase_admin_operation_logs(operation_id)
            )
            """
        )
        target_columns = [
            "item_id", "operation_id", "product_id", "old_price", "new_price",
            "old_visible", "new_visible", "old_version", "new_version",
            "old_price_override", "new_price_override", "old_visibility_override",
            "new_visibility_override", "old_override_origin", "new_override_origin",
        ]
        copy_columns = [column for column in target_columns if column in operation_columns]
        joined = ",".join(copy_columns)
        conn.execute(
            f"insert into showcase_admin_operation_items ({joined}) select {joined} from showcase_admin_operation_items_v8"
        )
        conn.execute("drop table showcase_admin_operation_items_v8")
        conn.execute(
            "create index if not exists idx_showcase_admin_operation_items_operation "
            "on showcase_admin_operation_items(operation_id)"
        )
        conn.execute("insert into showcase_schema_migrations(version) values (9)")
    return fresh
