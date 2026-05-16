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
            conn.execute(
                """
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
                  first_seen_at text not null,
                  last_seen_at text not null
                )
                """
            )
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
                first_seen = conn.execute(
                    "select first_seen_at from inventory_records where record_key = ?",
                    (record.record_key,),
                ).fetchone()
                conn.execute(
                    """
                    insert into inventory_records (
                      record_key, remark_name, wxid, published_at, model, price, serial_no, status,
                      image_urls, video_urls, content_text, note, needs_manual, source_moment_ids,
                      first_seen_at, last_seen_at
                    ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                      last_seen_at = excluded.last_seen_at
                    """,
                    (
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
                        first_seen[0] if first_seen else sync_started_at,
                        sync_started_at,
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

            orphan_keys = [
                row[0]
                for row in conn.execute(
                    "select record_key from inventory_records where model is null or trim(model) = ''"
                ).fetchall()
            ]
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
                       image_urls, video_urls, content_text, note, needs_manual, source_moment_ids
                from inventory_records
                order by published_at asc
                """
            ).fetchall()

        return [
            InventoryRecord(
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
                source_moment_ids=json.loads(row[13]),
            )
            for row in rows
        ]

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
