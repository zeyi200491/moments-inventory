from __future__ import annotations

import sqlite3
import threading
from pathlib import Path

from moments_inventory.showcase_web.models import ShowcaseProduct, ShowcaseProductImage


class SQLiteShowcaseRepository:
    def __init__(self, database_path: str | Path) -> None:
        self._database_path = str(database_path)
        self._connection: sqlite3.Connection | None = None
        self._lock = threading.RLock()

    def _get_connection(self) -> sqlite3.Connection:
        with self._lock:
            if self._connection is None:
                if self._database_path != ":memory:":
                    Path(self._database_path).parent.mkdir(parents=True, exist_ok=True)
                self._connection = sqlite3.connect(
                    self._database_path,
                    check_same_thread=False,
                )
            return self._connection

    def close(self) -> None:
        with self._lock:
            if self._connection is not None:
                self._connection.close()
                self._connection = None

    def initialize(self) -> None:
        with self._lock:
            with self._get_connection() as conn:
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
                      last_seen_import_id text not null
                    )
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

    def list_table_names(self) -> set[str]:
        self.initialize()
        with self._lock:
            rows = self._get_connection().execute(
                """
                select name
                from sqlite_master
                where type = 'table'
                """
            ).fetchall()
        return {str(row[0]) for row in rows}

    def upsert_product(self, product: ShowcaseProduct) -> None:
        self.initialize()
        with self._lock:
            with self._get_connection() as conn:
                conn.execute(
                    """
                    insert into showcase_products (
                      product_id,
                      model,
                      brand,
                      cost_price,
                      display_price,
                      visible,
                      sold,
                      published_at,
                      raw_copy,
                      display_copy,
                      cover_image_path,
                      created_at,
                      updated_at,
                      last_seen_import_id
                    )
                    values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    on conflict(product_id) do update set
                      model = excluded.model,
                      brand = excluded.brand,
                      cost_price = excluded.cost_price,
                      display_price = excluded.display_price,
                      visible = excluded.visible,
                      sold = excluded.sold,
                      published_at = excluded.published_at,
                      raw_copy = excluded.raw_copy,
                      display_copy = excluded.display_copy,
                      cover_image_path = excluded.cover_image_path,
                      created_at = excluded.created_at,
                      updated_at = excluded.updated_at,
                      last_seen_import_id = excluded.last_seen_import_id
                    """,
                    _product_to_row(product),
                )

    def get_product(self, product_id: str) -> ShowcaseProduct | None:
        self.initialize()
        with self._lock:
            row = self._get_connection().execute(
                """
                select product_id,
                       model,
                       brand,
                       cost_price,
                       display_price,
                       visible,
                       sold,
                       published_at,
                       raw_copy,
                       display_copy,
                       cover_image_path,
                       created_at,
                       updated_at,
                       last_seen_import_id
                from showcase_products
                where product_id = ?
                """,
                (product_id,),
            ).fetchone()
        return _product_from_row(row) if row is not None else None

    def list_products(self, *, include_hidden: bool = False) -> list[ShowcaseProduct]:
        self.initialize()
        where_clause = "" if include_hidden else "where visible = 1"
        with self._lock:
            rows = self._get_connection().execute(
                f"""
                select product_id,
                       model,
                       brand,
                       cost_price,
                       display_price,
                       visible,
                       sold,
                       published_at,
                       raw_copy,
                       display_copy,
                       cover_image_path,
                       created_at,
                       updated_at,
                       last_seen_import_id
                from showcase_products
                {where_clause}
                order by published_at desc, product_id asc
                """
            ).fetchall()
        return [_product_from_row(row) for row in rows]

    def update_product_price(self, product_id: str, display_price: int) -> bool:
        self.initialize()
        with self._lock:
            with self._get_connection() as conn:
                cursor = conn.execute(
                    """
                    update showcase_products
                    set display_price = ?
                    where product_id = ?
                    """,
                    (display_price, product_id),
                )
                return cursor.rowcount > 0

    def set_product_visibility(self, product_id: str, visible: bool) -> bool:
        self.initialize()
        with self._lock:
            with self._get_connection() as conn:
                cursor = conn.execute(
                    """
                    update showcase_products
                    set visible = ?
                    where product_id = ?
                    """,
                    (int(visible), product_id),
                )
                return cursor.rowcount > 0

    def add_product_image(
        self,
        image_id: str,
        product_id: str,
        image_path: str,
        image_type: str,
        sort_order: int,
        is_cover: bool,
    ) -> None:
        self.initialize()
        with self._lock:
            with self._get_connection() as conn:
                conn.execute(
                    """
                    insert into showcase_product_images (
                      image_id,
                      product_id,
                      image_path,
                      image_type,
                      sort_order,
                      is_cover
                    )
                    values (?, ?, ?, ?, ?, ?)
                    on conflict(image_id) do update set
                      product_id = excluded.product_id,
                      image_path = excluded.image_path,
                      image_type = excluded.image_type,
                      sort_order = excluded.sort_order,
                      is_cover = excluded.is_cover
                    """,
                    (image_id, product_id, image_path, image_type, sort_order, int(is_cover)),
                )

    def list_product_images(self, product_id: str) -> list[ShowcaseProductImage]:
        self.initialize()
        with self._lock:
            rows = self._get_connection().execute(
                """
                select image_id,
                       product_id,
                       image_path,
                       image_type,
                       sort_order,
                       is_cover
                from showcase_product_images
                where product_id = ?
                order by sort_order asc, image_id asc
                """,
                (product_id,),
            ).fetchall()
        return [
            ShowcaseProductImage(
                image_id=str(row[0]),
                product_id=str(row[1]),
                image_path=str(row[2]),
                image_type=str(row[3]),
                sort_order=int(row[4]),
                is_cover=bool(row[5]),
            )
            for row in rows
        ]

    def save_import_log(
        self,
        *,
        import_id: str,
        source_path: str,
        imported_at: str,
        inserted_count: int,
        updated_count: int,
        missing_count: int,
    ) -> None:
        self.initialize()
        with self._lock:
            with self._get_connection() as conn:
                conn.execute(
                    """
                    insert into showcase_import_logs (
                      import_id,
                      source_path,
                      imported_at,
                      inserted_count,
                      updated_count,
                      missing_count
                    )
                    values (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        import_id,
                        source_path,
                        imported_at,
                        inserted_count,
                        updated_count,
                        missing_count,
                    ),
                )

    def list_product_ids(self) -> set[str]:
        self.initialize()
        with self._lock:
            rows = self._get_connection().execute(
                "select product_id from showcase_products"
            ).fetchall()
        return {str(row[0]) for row in rows}

    def set_setting(self, key: str, value: str) -> None:
        self.initialize()
        with self._lock:
            with self._get_connection() as conn:
                conn.execute(
                    """
                    insert into showcase_settings (setting_key, setting_value)
                    values (?, ?)
                    on conflict(setting_key) do update set
                      setting_value = excluded.setting_value
                    """,
                    (key, value),
                )

    def get_setting(self, key: str) -> str | None:
        self.initialize()
        with self._lock:
            row = self._get_connection().execute(
                """
                select setting_value
                from showcase_settings
                where setting_key = ?
                """,
                (key,),
            ).fetchone()
        return str(row[0]) if row is not None else None

    def save_admin_session(self, session_id: str, expires_at: str) -> None:
        self.initialize()
        with self._lock:
            with self._get_connection() as conn:
                conn.execute(
                    """
                    insert into showcase_admin_sessions (session_id, expires_at)
                    values (?, ?)
                    """,
                    (session_id, expires_at),
                )

    def get_admin_session_expires_at(self, session_id: str) -> str | None:
        self.initialize()
        with self._lock:
            row = self._get_connection().execute(
                """
                select expires_at
                from showcase_admin_sessions
                where session_id = ?
                """,
                (session_id,),
            ).fetchone()
        return str(row[0]) if row is not None else None

    def delete_product(self, product_id: str) -> bool:
        self.initialize()
        with self._lock:
            with self._get_connection() as conn:
                conn.execute(
                    "delete from showcase_product_images where product_id = ?",
                    (product_id,),
                )
                cursor = conn.execute(
                    "delete from showcase_products where product_id = ?",
                    (product_id,),
                )
                return cursor.rowcount > 0


def _product_to_row(product: ShowcaseProduct) -> tuple[object, ...]:
    return (
        product.product_id,
        product.model,
        product.brand,
        product.cost_price,
        product.display_price,
        int(product.visible),
        int(product.sold),
        product.published_at,
        product.raw_copy,
        product.display_copy,
        product.cover_image_path,
        product.created_at,
        product.updated_at,
        product.last_seen_import_id,
    )


def _product_from_row(row: tuple[object, ...]) -> ShowcaseProduct:
    return ShowcaseProduct(
        product_id=str(row[0]),
        model=str(row[1]),
        brand=str(row[2]),
        cost_price=int(row[3]),
        display_price=int(row[4]),
        visible=bool(row[5]),
        sold=bool(row[6]),
        published_at=str(row[7]),
        raw_copy=str(row[8]),
        display_copy=str(row[9]),
        cover_image_path=str(row[10]),
        created_at=str(row[11]),
        updated_at=str(row[12]),
        last_seen_import_id=str(row[13]),
    )
