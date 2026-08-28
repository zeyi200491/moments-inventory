from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path

from moments_inventory.logging_utils import get_logger
from moments_inventory.models import InventoryRecord


LOGGER = get_logger(__name__)
DEFAULT_ACTIVE_STATUS = "未售出"
DEFAULT_SOLD_STATUS = "已售"
_DETAIL_TABLE_COLUMNS: dict[str, frozenset[str]] = {
    "record_images": frozenset({"url"}),
    "record_videos": frozenset({"url"}),
    "record_source_moments": frozenset({"moment_id"}),
}
_LIFECYCLE_COLUMN_DEFINITIONS: tuple[tuple[str, str], ...] = (
    ("product_key", "text"),
    ("fingerprint_reason", "text not null default ''"),
    ("lifecycle_status", "text not null default 'current'"),
    ("risk_flags", "text not null default '[]'"),
    ("price_history", "text not null default '[]'"),
    ("last_seen_at", "text"),
)
_INVENTORY_RECORDS_SCHEMA = """
create table if not exists inventory_records (
  record_key text primary key,
  remark_name text,
  wxid text,
  published_at text not null,
  model text,
  price integer,
  serial_no text,
  status text not null,
  image_urls text not null,
  video_urls text not null,
  content_text text not null,
  note text not null,
  needs_manual integer not null,
  source_moment_ids text not null,
  product_key text,
  fingerprint_reason text not null default '',
  lifecycle_status text not null default 'current',
  risk_flags text not null default '[]',
  price_history text not null default '[]',
  first_seen_at text not null,
  last_seen_at text
)
"""


def _load_json_list(value: object) -> list[str]:
    if not value:
        return []
    try:
        loaded = json.loads(str(value))
    except (json.JSONDecodeError, TypeError):
        LOGGER.warning("invalid json list in storage row", extra={"value": value})
        return []
    return loaded if isinstance(loaded, list) else []


class InventoryStore:
    def __init__(self, db_path: str | Path) -> None:
        self._db_path = Path(db_path)

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path)
        conn.execute("pragma foreign_keys = on")
        return conn

    def initialize(self) -> None:
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.execute(_INVENTORY_RECORDS_SCHEMA)
            self._ensure_inventory_records_last_seen_nullable(conn)
            conn.execute(
                """
                create table if not exists record_images (
                  record_key text not null,
                  position integer not null,
                  url text not null,
                  primary key (record_key, position),
                  foreign key (record_key) references inventory_records(record_key) on delete cascade
                )
                """
            )
            conn.execute(
                "create index if not exists idx_record_images_url on record_images(url)"
            )
            conn.execute(
                """
                create table if not exists record_videos (
                  record_key text not null,
                  position integer not null,
                  url text not null,
                  primary key (record_key, position),
                  foreign key (record_key) references inventory_records(record_key) on delete cascade
                )
                """
            )
            conn.execute(
                "create index if not exists idx_record_videos_url on record_videos(url)"
            )
            conn.execute(
                """
                create table if not exists record_source_moments (
                  record_key text not null,
                  moment_id text not null,
                  primary key (record_key, moment_id),
                  foreign key (record_key) references inventory_records(record_key) on delete cascade
                )
                """
            )
            conn.execute(
                "create index if not exists idx_record_source_moments_moment_id on record_source_moments(moment_id)"
            )
            conn.execute(
                """
                create table if not exists inventory_staging_records (
                  run_id text not null,
                  batch_index integer not null,
                  record_key text not null,
                  remark_name text,
                  wxid text,
                  published_at text not null,
                  model text,
                  price integer,
                  serial_no text,
                  status text not null,
                  image_urls text not null,
                  video_urls text not null,
                  content_text text not null,
                  note text not null,
                  needs_manual integer not null,
                  source_moment_ids text not null,
                  product_key text,
                  fingerprint_reason text not null default '',
                  lifecycle_status text not null default 'current',
                  risk_flags text not null default '[]',
                  price_history text not null default '[]',
                  last_seen_at text,
                  primary key (run_id, record_key)
                )
                """
            )
            self._ensure_lifecycle_columns(conn, "inventory_records")
            self._ensure_lifecycle_columns(conn, "inventory_staging_records")
            conn.execute(
                "create index if not exists idx_inventory_staging_records_run_id_batch_index "
                "on inventory_staging_records(run_id, batch_index)"
            )

    def _ensure_lifecycle_columns(self, conn: sqlite3.Connection, table_name: str) -> None:
        existing_columns = {
            row[1] for row in conn.execute(f"pragma table_info({table_name})").fetchall()
        }
        for column_name, definition in _LIFECYCLE_COLUMN_DEFINITIONS:
            if column_name not in existing_columns:
                conn.execute(f"alter table {table_name} add column {column_name} {definition}")

    def _ensure_inventory_records_last_seen_nullable(self, conn: sqlite3.Connection) -> None:
        table_info = conn.execute("pragma table_info(inventory_records)").fetchall()
        last_seen_column = next((row for row in table_info if row[1] == "last_seen_at"), None)
        if last_seen_column is None or not last_seen_column[3]:
            return

        existing_columns = [row[1] for row in table_info]
        conn.commit()
        conn.execute("pragma foreign_keys = off")
        conn.execute("pragma legacy_alter_table = on")
        try:
            conn.execute("alter table inventory_records rename to inventory_records_legacy")
            conn.execute(_INVENTORY_RECORDS_SCHEMA)
            copied_columns = ", ".join(existing_columns)
            conn.execute(
                f"""
                insert into inventory_records ({copied_columns})
                select {copied_columns}
                from inventory_records_legacy
                """
            )
            conn.execute("drop table inventory_records_legacy")
            conn.commit()
        finally:
            conn.execute("pragma legacy_alter_table = off")
            conn.execute("pragma foreign_keys = on")

    def _record_to_row(self, record: InventoryRecord) -> tuple[object, ...]:
        return (
            record.record_key,
            record.remark_name,
            record.wxid,
            record.published_at.isoformat(),
            record.model,
            record.price,
            record.serial_no,
            record.status or DEFAULT_ACTIVE_STATUS,
            json.dumps(record.image_urls, ensure_ascii=False),
            json.dumps(record.video_urls, ensure_ascii=False),
            record.content_text,
            record.note,
            int(record.needs_manual),
            json.dumps(record.source_moment_ids, ensure_ascii=False),
            record.product_key,
            record.fingerprint_reason,
            record.lifecycle_status or "current",
            json.dumps(record.risk_flags, ensure_ascii=False),
            json.dumps(record.price_history, ensure_ascii=False),
            record.last_seen_at,
        )

    def _row_to_record(self, row: tuple[object, ...]) -> InventoryRecord:
        return InventoryRecord(
            record_key=row[0],
            remark_name=row[1],
            wxid=row[2],
            published_at=datetime.fromisoformat(row[3]),
            model=row[4],
            price=row[5],
            serial_no=row[6],
            status=row[7],
            image_urls=json.loads(row[8]),
            video_urls=json.loads(row[9]),
            content_text=row[10],
            note=row[11],
            needs_manual=bool(row[12]),
            source_moment_ids=_load_json_list(row[13]),
            product_key=row[14] if len(row) > 14 else None,
            fingerprint_reason=(row[15] if len(row) > 15 and row[15] is not None else ""),
            lifecycle_status=(row[16] if len(row) > 16 and row[16] else "current"),
            risk_flags=_load_json_list(row[17]) if len(row) > 17 else [],
            price_history=_load_json_list(row[18]) if len(row) > 18 else [],
            last_seen_at=row[19] if len(row) > 19 else None,
        )

    def _replace_detail_rows(
        self,
        conn: sqlite3.Connection,
        record: InventoryRecord,
    ) -> None:
        conn.execute("delete from record_images where record_key = ?", (record.record_key,))
        conn.execute("delete from record_videos where record_key = ?", (record.record_key,))
        conn.execute("delete from record_source_moments where record_key = ?", (record.record_key,))

        conn.executemany(
            "insert into record_images (record_key, position, url) values (?, ?, ?)",
            [
                (record.record_key, index, url)
                for index, url in enumerate(record.image_urls, start=1)
            ],
        )
        conn.executemany(
            "insert into record_videos (record_key, position, url) values (?, ?, ?)",
            [
                (record.record_key, index, url)
                for index, url in enumerate(record.video_urls, start=1)
            ],
        )
        conn.executemany(
            "insert into record_source_moments (record_key, moment_id) values (?, ?)",
            [(record.record_key, moment_id) for moment_id in record.source_moment_ids],
        )

    def upsert_records(
        self,
        records: list[InventoryRecord],
        fetched_moment_ids: set[str],
        sync_started_at: str,
        snapshot_complete: bool = True,
    ) -> None:
        self.initialize()
        deleted_by_merge = 0
        deleted_missing = 0
        with self._connect() as conn:
            for record in records:
                record_row = self._record_to_row(record)
                first_seen = conn.execute(
                    "select first_seen_at from inventory_records where record_key = ?",
                    (record.record_key,),
                ).fetchone()
                conn.execute(
                    """
                    insert into inventory_records (
                      record_key, remark_name, wxid, published_at, model, price, serial_no, status,
                      image_urls, video_urls, content_text, note, needs_manual, source_moment_ids,
                      product_key, fingerprint_reason, lifecycle_status, risk_flags, price_history,
                      last_seen_at, first_seen_at
                    ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    on conflict(record_key) do update set
                      remark_name = excluded.remark_name,
                      wxid = excluded.wxid,
                      published_at = excluded.published_at,
                      model = excluded.model,
                      price = excluded.price,
                      serial_no = excluded.serial_no,
                      status = excluded.status,
                      image_urls = excluded.image_urls,
                      video_urls = excluded.video_urls,
                      content_text = excluded.content_text,
                      note = excluded.note,
                      needs_manual = excluded.needs_manual,
                      source_moment_ids = excluded.source_moment_ids,
                      product_key = excluded.product_key,
                      fingerprint_reason = excluded.fingerprint_reason,
                      lifecycle_status = excluded.lifecycle_status,
                      risk_flags = excluded.risk_flags,
                      price_history = excluded.price_history,
                      last_seen_at = excluded.last_seen_at
                    """,
                    (
                        *record_row,
                        first_seen[0] if first_seen else sync_started_at,
                    ),
                )
                self._replace_detail_rows(conn, record)

            active_record_keys = {record.record_key for record in records}
            merged_source_sets = [set(record.source_moment_ids) for record in records if record.source_moment_ids]
            existing_rows = conn.execute(
                "select record_key, source_moment_ids from inventory_records"
            ).fetchall()
            for record_key, source_moment_ids_json in existing_rows:
                if record_key in active_record_keys:
                    continue
                source_ids = set(json.loads(source_moment_ids_json))
                if not source_ids:
                    continue
                if any(source_ids.issubset(merged_source_ids) for merged_source_ids in merged_source_sets):
                    conn.execute(
                        "delete from inventory_records where record_key = ?",
                        (record_key,),
                    )
                    deleted_by_merge += 1

            if snapshot_complete:
                all_rows = conn.execute(
                    "select record_key, source_moment_ids from inventory_records"
                ).fetchall()
                for record_key, source_moment_ids_json in all_rows:
                    source_ids = set(json.loads(source_moment_ids_json))
                    if source_ids and source_ids.isdisjoint(fetched_moment_ids):
                        conn.execute(
                            "delete from inventory_records where record_key = ?",
                            (record_key,),
                        )
                        deleted_missing += 1

            orphan_keys = []
            for record_key, risk_flags_json in conn.execute(
                """
                select record_key, risk_flags
                from inventory_records
                where model is null or trim(model) = ''
                """
            ).fetchall():
                if not _load_json_list(risk_flags_json):
                    orphan_keys.append(record_key)
            for record_key in orphan_keys:
                conn.execute("delete from inventory_records where record_key = ?", (record_key,))

        LOGGER.info(
            "storage upsert completed",
            extra={
                "record_count": len(records),
                "deleted_by_merge": deleted_by_merge,
                "deleted_missing": deleted_missing,
                "snapshot_complete": snapshot_complete,
            },
        )

    def list_all_records(self) -> list[InventoryRecord]:
        self.initialize()
        with self._connect() as conn:
            rows = conn.execute(
                """
                select record_key, remark_name, wxid, published_at, model, price, serial_no, status,
                       image_urls, video_urls, content_text, note, needs_manual, source_moment_ids,
                       product_key, fingerprint_reason, lifecycle_status, risk_flags, price_history,
                       last_seen_at
                from inventory_records
                order by published_at asc
                """
            ).fetchall()

        return [self._row_to_record(row) for row in rows]

    def stage_records(
        self,
        run_id: str,
        batch_index: int,
        records: list[InventoryRecord],
    ) -> None:
        self.initialize()
        with self._connect() as conn:
            conn.executemany(
                """
                insert into inventory_staging_records (
                  run_id, batch_index, record_key, remark_name, wxid, published_at, model,
                  price, serial_no, status, image_urls, video_urls, content_text, note,
                  needs_manual, source_moment_ids, product_key, fingerprint_reason,
                  lifecycle_status, risk_flags, price_history, last_seen_at
                ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                on conflict(run_id, record_key) do update set
                  batch_index = excluded.batch_index,
                  remark_name = excluded.remark_name,
                  wxid = excluded.wxid,
                  published_at = excluded.published_at,
                  model = excluded.model,
                  price = excluded.price,
                  serial_no = excluded.serial_no,
                  status = excluded.status,
                  image_urls = excluded.image_urls,
                  video_urls = excluded.video_urls,
                  content_text = excluded.content_text,
                  note = excluded.note,
                  needs_manual = excluded.needs_manual,
                  source_moment_ids = excluded.source_moment_ids,
                  product_key = excluded.product_key,
                  fingerprint_reason = excluded.fingerprint_reason,
                  lifecycle_status = excluded.lifecycle_status,
                  risk_flags = excluded.risk_flags,
                  price_history = excluded.price_history,
                  last_seen_at = excluded.last_seen_at
                """,
                [(run_id, batch_index, *self._record_to_row(record)) for record in records],
            )

    def list_staged_records(self, run_id: str) -> list[InventoryRecord]:
        self.initialize()
        with self._connect() as conn:
            rows = conn.execute(
                """
                select record_key, remark_name, wxid, published_at, model, price, serial_no,
                       status, image_urls, video_urls, content_text, note, needs_manual,
                       source_moment_ids, product_key, fingerprint_reason, lifecycle_status,
                       risk_flags, price_history, last_seen_at
                from inventory_staging_records
                where run_id = ?
                order by batch_index asc, published_at asc, record_key asc
                """,
                (run_id,),
            ).fetchall()
        return [self._row_to_record(row) for row in rows]

    def clear_staged_records(self, run_id: str) -> None:
        self.initialize()
        with self._connect() as conn:
            conn.execute(
                "delete from inventory_staging_records where run_id = ?",
                (run_id,),
            )

    def replace_current_records_from_stage(
        self,
        run_id: str,
        committed_at: str | None = None,
    ) -> None:
        self.initialize()
        committed_timestamp = committed_at or datetime.now().astimezone().isoformat()
        with self._connect() as conn:
            rows = conn.execute(
                """
                select record_key, remark_name, wxid, published_at, model, price, serial_no,
                       status, image_urls, video_urls, content_text, note, needs_manual,
                       source_moment_ids, product_key, fingerprint_reason, lifecycle_status,
                       risk_flags, price_history, last_seen_at
                from inventory_staging_records
                where run_id = ?
                order by batch_index asc, published_at asc, record_key asc
                """,
                (run_id,),
            ).fetchall()
            records = [self._row_to_record(row) for row in rows]

            conn.execute("delete from inventory_records")
            for record in records:
                record_row = self._record_to_row(record)
                conn.execute(
                    """
                    insert into inventory_records (
                      record_key, remark_name, wxid, published_at, model, price, serial_no, status,
                      image_urls, video_urls, content_text, note, needs_manual, source_moment_ids,
                      product_key, fingerprint_reason, lifecycle_status, risk_flags, price_history,
                      last_seen_at, first_seen_at
                    ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        *record_row,
                        committed_timestamp,
                    ),
                )
                self._replace_detail_rows(conn, record)

    def _list_record_keys_by_detail(
        self,
        table_name: str,
        column_name: str,
        value: str,
    ) -> list[str]:
        allowed_columns = _DETAIL_TABLE_COLUMNS.get(table_name)
        if allowed_columns is None:
            raise ValueError(f"unsupported detail table: {table_name}")
        if column_name not in allowed_columns:
            raise ValueError(f"unsupported detail column for {table_name}: {column_name}")
        self.initialize()
        query = (
            f"select record_key from {table_name} where {column_name} = ? "
            "order by record_key asc"
        )
        with self._connect() as conn:
            rows = conn.execute(query, (value,)).fetchall()
        return [row[0] for row in rows]

    def list_record_keys_by_image_url(self, url: str) -> list[str]:
        return self._list_record_keys_by_detail("record_images", "url", url)

    def list_record_keys_by_video_url(self, url: str) -> list[str]:
        return self._list_record_keys_by_detail("record_videos", "url", url)

    def list_record_keys_by_source_moment_id(self, moment_id: str) -> list[str]:
        return self._list_record_keys_by_detail(
            "record_source_moments",
            "moment_id",
            moment_id,
        )
