from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from uuid import uuid4

from moments_inventory.showcase_brands import normalize_showcase_model_key
from moments_inventory.showcase_web.importer import parse_review_workbook


def create_import_review_batch(
    repository,
    content: bytes,
    *,
    source_scope: str,
    mode: str = "incremental",
    complete: bool = False,
    source_path: str = "",
    source_label: str = "",
    max_missing_fraction: float = 0.3,
) -> dict[str, object]:
    """解析并持久化人工复核批次；不更改商品库存和正式导入日志。"""
    if mode not in ("incremental", "full") or not source_scope.strip():
        raise ValueError("导入模式或来源范围无效")
    source_scope = source_scope.strip()
    if not 0 <= max_missing_fraction <= 1:
        raise ValueError("缺失复核阈值必须介于0和1")
    parsed = parse_review_workbook(content)
    row_errors = [
        f"第 {item['row_number']} 行：{error}"
        for item in parsed
        for error in item["validation_errors"]
    ]
    if row_errors:
        raise ValueError("工作簿行校验失败：" + "；".join(row_errors))
    if mode == "full" and (not complete or not parsed):
        raise ValueError("全量导入需要完整性声明且不能是空表")
    now = datetime.now(timezone.utc).isoformat()
    batch_id = uuid4().hex
    fingerprint = hashlib.sha256(content).hexdigest()

    with repository._read_connection() as conn:
        # 三组数据必须来自同一 SQLite 读快照，避免商品在查询间增删造成范围摘要错位。
        conn.execute("BEGIN")
        try:
            aliases = {}
            for alias_scope, source_key, product_id in conn.execute(
                "select source_scope,source_key,product_id from showcase_source_identity_aliases"
            ).fetchall():
                aliases.setdefault(str(source_key), []).append((str(alias_scope), str(product_id)))
            scoped_product_ids = {str(row[0]) for row in conn.execute(
                "select product_id from showcase_products where source_scope=?", (source_scope,)
            ).fetchall()}
            cursor = conn.execute(
                "select product_id,model,brand,row_version,source_scope,source_product_key from showcase_products"
            )
            columns = [column[0] for column in cursor.description]
            products = [dict(zip(columns, row)) for row in cursor.fetchall()]
        finally:
            conn.rollback()
    products_by_id = {str(product["product_id"]): product for product in products}
    by_source_key = {
        (str(product["source_scope"]), str(product["source_product_key"])): product
        for product in products if str(product["source_product_key"] or "")
    }
    source_key_owners: dict[str, set[str]] = {}
    for product in products:
        source_key = str(product["source_product_key"] or "")
        if source_key:
            source_key_owners.setdefault(source_key, set()).add(str(product["source_scope"]))
    for source_key, owners in aliases.items():
        source_key_owners.setdefault(source_key, set()).update(scope for scope, _ in owners)
    candidates_by_identity: dict[tuple[str, str, str], list[dict[str, object]]] = {}
    for product in products:
        identity = (
            str(product["source_scope"]),
            str(product["brand"]),
            normalize_showcase_model_key(str(product["model"])),
        )
        candidates_by_identity.setdefault(identity, []).append(product)
    for candidates in candidates_by_identity.values():
        candidates.sort(key=lambda product: str(product["product_id"]))

    key_rows: dict[str, list[dict]] = {}
    for item in parsed:
        if item["source_key"]:
            key_rows.setdefault(item["source_key"], []).append(item)
    for source_key, matches in key_rows.items():
        if len(matches) > 1:
            for item in matches:
                item["errors"].append(f"来源商品键在本批次重复：{source_key}")

    selected_targets: dict[str, list[dict]] = {}
    staged_rows = []
    source_present_ids: set[str] = set()
    for item in parsed:
        record = item["snapshot"] if "product_id" in item["snapshot"] else None
        errors = item["errors"]
        recommendation = None
        candidates = []
        if record:
            source_key = item["source_key"]
            if source_key:
                other_scope = any(scope != source_scope for scope in source_key_owners.get(source_key, ()))
                if other_scope:
                    errors.append("来源商品键已属于其他来源范围")
                else:
                    exact = by_source_key.get((source_scope, source_key))
                    alias_id = next((product_id for scope, product_id in aliases.get(source_key, ())
                                     if scope == source_scope), None)
                    target = exact or (products_by_id.get(alias_id) if alias_id else None)
                    if target:
                        if target["source_scope"] != source_scope:
                            errors.append("来源身份 alias 指向其他来源范围的商品")
                        else:
                            recommendation = _product_summary(target, "source_key" if exact else "alias")
                            selected_targets.setdefault(str(target["product_id"]), []).append(item)
                            source_present_ids.add(str(target["product_id"]))
            source_product_id = str(record.get("product_id", ""))
            existing_id = products_by_id.get(source_product_id)
            if existing_id and existing_id["source_scope"] != source_scope:
                errors.append("商品ID已属于其他来源范围")
            elif existing_id:
                # 稳定键缺失时，工作簿商品 ID 仍能证明商品在 full 来源快照中。
                # 这只影响缺失摘要，不形成身份建议或人工决定。
                source_present_ids.add(source_product_id)
            model_key = normalize_showcase_model_key(str(record.get("model", "")))
            brand = str(record.get("brand", ""))
            candidates = [
                _product_summary(product, "model")
                for product in candidates_by_identity.get((source_scope, brand, model_key), ())[:5]
            ]
        staged_rows.append({
            "review_row_id": uuid4().hex,
            "batch_id": batch_id,
            "row_number": item["row_number"],
            "source_key": item["source_key"],
            "status": "pending",
            "decision": None,
            "product_id": None,
            "target_row_version": None,
            "snapshot_json": "",
            "created_at": now,
            "updated_at": now,
            "_item": item,
            "_record": record,
            "_recommendation": recommendation,
            "_candidates": candidates,
        })
    for target_id, matches in selected_targets.items():
        if len(matches) > 1:
            for item in matches:
                item["errors"].append(f"多行建议关联同一商品：{target_id}")

    # 同一工作簿商品ID也可能对应同一已有目标，明确标注，保持行供人工处理。
    duplicate_ids: dict[str, list[dict]] = {}
    for item in parsed:
        snapshot = item["snapshot"]
        if "product_id" in snapshot:
            duplicate_ids.setdefault(str(snapshot["product_id"]), []).append(item)
    for product_id, matches in duplicate_ids.items():
        if len(matches) > 1:
            for item in matches:
                item["errors"].append(f"多个导入行使用同一商品ID：{product_id}")

    for row in staged_rows:
        item = row.pop("_item")
        record = row.pop("_record")
        recommendation = row.pop("_recommendation")
        candidates = row.pop("_candidates")
        row["snapshot_json"] = json.dumps({
            "record": record if record is not None else item["snapshot"].get("raw", {}),
            "errors": item["errors"],
            "recommendation": recommendation,
            "candidates": candidates,
        }, ensure_ascii=False, separators=(",", ":"))

    missing_items = []
    if mode == "full":
        missing_ids = scoped_product_ids - source_present_ids
        missing_by_id = {str(product["product_id"]): product for product in products}
        missing_items = [
            {
                "product_id": product_id,
                "model": missing_by_id[product_id]["model"],
                "brand": missing_by_id[product_id]["brand"],
                "source_product_key": missing_by_id[product_id]["source_product_key"],
                "row_version": int(missing_by_id[product_id]["row_version"]),
            }
            for product_id in sorted(missing_ids)
        ]
    missing_count = len(missing_items)
    warnings = []
    if mode == "full" and scoped_product_ids and missing_count / len(scoped_product_ids) > max_missing_fraction:
        warnings.append("全量范围内未匹配商品超过缺失阈值，需要人工复核范围")
    batch = {
        "batch_id": batch_id,
        "source_scope": source_scope,
        "mode": mode,
        "complete": int(bool(complete)),
        "source_path": source_path,
        "source_label": source_label,
        "source_fingerprint": fingerprint,
        "parsed_row_count": len(staged_rows),
        "missing_count": missing_count,
        # 幂等键属于最终提交请求；上传暂存批次固定留空。
        "idempotency_key": "",
        "result_json": json.dumps({
            "warnings": warnings,
            "missing_items": missing_items,
            "scope_snapshot": ([
                {"product_id": str(product["product_id"]), "row_version": int(product["row_version"])}
                for product in products if str(product["source_scope"]) == source_scope
            ] if mode == "full" else []),
        }, ensure_ascii=False),
        "status": "pending",
        "created_at": now,
        "completed_at": "",
    }
    repository.create_import_review_batch(batch, staged_rows)
    return get_import_review_batch(repository, batch_id)


def get_import_review_batch(repository, batch_id: str) -> dict[str, object]:
    batch = repository.get_import_review_batch(batch_id)
    if batch is None:
        raise ValueError("复核批次不存在")
    batch["complete"] = bool(batch["complete"])
    batch["result"] = json.loads(str(batch["result_json"]))
    return batch


def list_import_review_rows(repository, batch_id: str) -> list[dict[str, object]]:
    if repository.get_import_review_batch(batch_id) is None:
        raise ValueError("复核批次不存在")
    return repository.list_import_review_rows(batch_id)


def save_import_review_decision(repository, batch_id: str, review_row_id: str, *, decision: str, product_id: str | None = None) -> dict[str, object]:
    return repository.save_import_review_decision(batch_id, review_row_id, decision=decision, product_id=product_id)


def discard_import_review_batch(repository, batch_id: str) -> dict[str, object]:
    repository.discard_import_review_batch(batch_id)
    return get_import_review_batch(repository, batch_id)


def _product_summary(product: dict[str, object], reason: str) -> dict[str, object]:
    return {
        "product_id": product["product_id"],
        "model": product["model"],
        "brand": product["brand"],
        "source_scope": product["source_scope"],
        "row_version": int(product["row_version"]),
        "reason": reason,
    }


class ImportReviewConflictError(ValueError):
    """提交前快照或库存身份发生冲突；调用层可映射为 HTTP 409。"""


def commit_import_review_batch(repository, batch_id: str, idempotency_key: str) -> dict[str, object]:
    """在单个 BEGIN IMMEDIATE 事务中提交已复核的库存批次。"""
    if not idempotency_key or not idempotency_key.strip():
        raise ValueError("提交幂等键不能为空")
    now = datetime.now(timezone.utc).isoformat()
    with repository._lock:
        conn = repository._get_connection()
        conn.execute("BEGIN IMMEDIATE")
        try:
            batch = _fetch_dict(conn, "select * from showcase_import_review_batches where batch_id=?", (batch_id,))
            if batch is None:
                raise ValueError("复核批次不存在")
            if batch["status"] == "committed":
                if batch["idempotency_key"] != idempotency_key:
                    raise ImportReviewConflictError("该批次已使用其他幂等键提交")
                result = json.loads(str(batch["result_json"]))
                conn.rollback()
                return result
            if batch["status"] != "pending":
                raise ImportReviewConflictError("批次必须处于 pending 状态")
            if batch["mode"] == "full" and not batch["complete"]:
                raise ImportReviewConflictError("全量批次缺少完整性声明")

            rows = _fetch_all_dict(conn,
                "select * from showcase_import_review_rows where batch_id=? order by row_number,review_row_id",
                (batch_id,))
            if len(rows) != int(batch["parsed_row_count"]):
                raise ImportReviewConflictError("复核行数量与批次快照不一致")
            if any(row["status"] != "pending" or row["decision"] not in ("link", "create", "skip") for row in rows):
                raise ImportReviewConflictError("所有复核行都必须先作出决定")
            if any(
                (row["decision"] == "link" and (not row["product_id"] or row["target_row_version"] is None))
                or (row["decision"] != "link" and (row["product_id"] is not None or row["target_row_version"] is not None))
                for row in rows
            ):
                raise ImportReviewConflictError("复核决定与关联目标信息不一致")

            staged_result = json.loads(str(batch["result_json"] or "{}"))
            products = _fetch_all_dict(conn, "select * from showcase_products")
            by_id = {str(item["product_id"]): item for item in products}
            scope = str(batch["source_scope"])
            current_scope = {key: item for key, item in by_id.items() if item["source_scope"] == scope}
            scope_snapshot = {str(item["product_id"]): int(item["row_version"])
                              for item in staged_result.get("scope_snapshot", [])}
            if batch["mode"] == "full":
                if set(scope_snapshot) != set(current_scope):
                    raise ImportReviewConflictError("全量批次来源范围已增删商品")
                for product_id, expected in scope_snapshot.items():
                    if int(current_scope[product_id]["row_version"]) != expected:
                        raise ImportReviewConflictError(f"全量批次商品版本已变化：{product_id}")

            alias_rows = conn.execute("select source_scope,source_key,product_id from showcase_source_identity_aliases").fetchall()
            aliases = {(str(a_scope), str(key)): str(product_id) for a_scope, key, product_id in alias_rows}
            key_owners: dict[str, set[str]] = {}
            for product in products:
                key = str(product.get("source_product_key") or "")
                if key:
                    key_owners.setdefault(key, set()).add(str(product["source_scope"]))
            for alias_scope, key in aliases:
                key_owners.setdefault(key, set()).add(alias_scope)

            decoded = []
            for row in rows:
                snapshot = json.loads(str(row["snapshot_json"]))
                record = snapshot.get("record")
                if row["decision"] != "skip" and not isinstance(record, dict):
                    raise ImportReviewConflictError(f"第 {row['row_number']} 行没有可提交的解析记录")
                decoded.append((row, record if isinstance(record, dict) else {}))

            writers_by_key: dict[str, list[dict]] = {}
            writers_by_target: dict[str, list[dict]] = {}
            created_ids: set[str] = set()
            creates: list[tuple[dict, dict]] = []
            links: list[tuple[dict, dict]] = []
            for row, record in decoded:
                if row["decision"] == "skip":
                    continue
                key = str(row["source_key"] or record.get("source_product_key") or "")
                if key:
                    writers_by_key.setdefault(key, []).append(row)
                    if any(owner != scope for owner in key_owners.get(key, set())):
                        raise ImportReviewConflictError(f"来源商品键已属于其他来源范围：{key}")
                if row["decision"] == "link":
                    product_id = str(row["product_id"] or "")
                    target = by_id.get(product_id)
                    if not target or target["source_scope"] != scope:
                        raise ImportReviewConflictError(f"关联目标不存在或不属于来源范围：{product_id}")
                    if row["target_row_version"] is None or int(target["row_version"]) != int(row["target_row_version"]):
                        raise ImportReviewConflictError(f"关联目标版本已变化：{product_id}")
                    writers_by_target.setdefault(product_id, []).append(row)
                    links.append((row, record))
                else:
                    product_id = str(record.get("product_id") or "")
                    if not product_id or product_id in by_id:
                        raise ImportReviewConflictError(f"create 商品ID无效或已存在：{product_id}")
                    if product_id in created_ids:
                        raise ImportReviewConflictError(f"本批次多个 create 行使用同一商品ID：{product_id}")
                    created_ids.add(product_id)
                    creates.append((row, record))
            for key, writers in writers_by_key.items():
                if len(writers) > 1:
                    raise ImportReviewConflictError(f"本批次来源商品键仍有多个写入行：{key}")
            for product_id, writers in writers_by_target.items():
                if len(writers) > 1:
                    raise ImportReviewConflictError(f"本批次多个导入行认领同一商品：{product_id}")

            for row, record in [*links, *creates]:
                key = str(row["source_key"] or record.get("source_product_key") or "")
                if not key:
                    continue
                product_id = str(row["product_id"] if row["decision"] == "link" else record["product_id"])
                exact = next((str(p["product_id"]) for p in products
                              if p["source_scope"] == scope and p.get("source_product_key") == key), None)
                alias_owner = aliases.get((scope, key))
                if exact and exact != product_id:
                    raise ImportReviewConflictError(f"当前来源商品键已属于其他商品：{key}")
                if alias_owner and alias_owner != product_id:
                    raise ImportReviewConflictError(f"来源商品键已属于其他商品：{key}")
                if row["decision"] == "create" and (exact or alias_owner):
                    raise ImportReviewConflictError(f"新商品来源键已存在：{key}")

            missing_ids = []
            if batch["mode"] == "full":
                represented: set[str] = set()
                exact_by_key = {
                    str(product.get("source_product_key") or ""): product_id
                    for product_id, product in current_scope.items()
                    if product.get("source_product_key")
                }
                for row, record in decoded:
                    source_key = str(row["source_key"] or record.get("source_product_key") or "")
                    if source_key:
                        exact_id = exact_by_key.get(source_key)
                        alias_id = aliases.get((scope, source_key))
                        if exact_id:
                            represented.add(exact_id)
                        if alias_id in current_scope:
                            represented.add(alias_id)
                    record_id = str(record.get("product_id") or "")
                    if record_id in current_scope:
                        represented.add(record_id)
                    if row["decision"] == "link" and row["product_id"] in current_scope:
                        represented.add(str(row["product_id"]))
                missing_ids = sorted(set(current_scope) - represented)
                for product_id in missing_ids:
                    if int(current_scope[product_id]["row_version"]) != scope_snapshot[product_id]:
                        raise ImportReviewConflictError(f"全量缺失商品版本已变化：{product_id}")

            rev = conn.execute("select setting_value from showcase_settings where setting_key='catalog_revision'").fetchone()
            base_revision = int(rev[0]) if rev else 0
            import_id = uuid4().hex
            inserted, updated = 0, 0
            for row, record in [*links, *creates]:
                previous = by_id.get(str(row["product_id"])) if row["decision"] == "link" else None
                product_id = str(previous["product_id"] if previous else record["product_id"])
                inserted += int(previous is None)
                updated += int(previous is not None)
                values = dict(previous) if previous else dict(
                    public_id=uuid4().hex, row_version=0, created_at=now, sold=False,
                    short_selling_point="", recommend_tags="", price_override=None,
                    copy_override=None, visibility_override=None, override_origin="", last_verified_at="")
                values.update({name: value for name, value in record.items()
                               if (name == "source_product_key" and value) or name not in ("source_product_key", "body_image_paths", "product_id")})
                source_key = str(row["source_key"] or record.get("source_product_key") or "")
                if source_key:
                    values["source_product_key"] = source_key
                if previous and not record.get("cover_image_path"):
                    values["cover_image_path"] = previous["cover_image_path"]
                values.update(source_scope=scope, source_available=True, last_seen_at=now,
                              review_state="", updated_at=now, last_seen_import_id=import_id)
                values["display_price"] = values["price_override"] if values["price_override"] is not None else values["source_display_price"]
                values["display_copy"] = values["copy_override"] if values["copy_override"] is not None else values["source_display_copy"]
                values["visible"] = bool(values["visibility_override"] if values["visibility_override"] is not None else values["source_visible"]) and not values["sold"]
                columns = tuple(values)
                if previous:
                    old_source_key = str(previous.get("source_product_key") or "")
                    if old_source_key and source_key and old_source_key != source_key:
                        old_alias_owner = aliases.get((scope, old_source_key))
                        if any(owner != scope for owner in key_owners.get(old_source_key, set())):
                            raise ImportReviewConflictError(f"旧来源商品键已属于其他来源范围：{old_source_key}")
                        if old_alias_owner and old_alias_owner != product_id:
                            raise ImportReviewConflictError(f"旧来源商品键已别名到其他商品：{old_source_key}")
                        if not old_alias_owner:
                            conn.execute("insert into showcase_source_identity_aliases values (?,?,?,?,?)",
                                         (uuid4().hex, scope, old_source_key, product_id, now))
                            aliases[(scope, old_source_key)] = product_id
                    updates = [name for name in columns if name not in ("product_id", "row_version")]
                    conn.execute("UPDATE showcase_products SET " + ",".join(f"{name}=?" for name in updates) + ",row_version=row_version+1 WHERE product_id=? AND row_version=?",
                                 [values[name] for name in updates] + [product_id, int(row["target_row_version"])])
                    if conn.execute("select changes()").fetchone()[0] != 1:
                        raise ImportReviewConflictError(f"关联目标版本已变化：{product_id}")
                else:
                    conn.execute("INSERT INTO showcase_products (product_id," + ",".join(columns) + ") VALUES (" + ",".join("?" for _ in range(len(columns)+1)) + ")",
                                 [product_id] + [values[name] for name in columns])
                paths = record.get("body_image_paths") or []
                if paths:
                    conn.execute("delete from showcase_product_images where product_id=? and image_type='body' and (source='inventory_import' or (image_id=? and source='legacy_unknown'))",
                                 (product_id, f"{product_id}|body|0"))
                    conn.executemany("""insert into showcase_product_images
                        (image_id,product_id,image_path,image_type,sort_order,is_cover,source)
                        values (?,?,?,'body',?,?, 'inventory_import') on conflict(image_id) do update set
                        image_path=excluded.image_path,image_type=excluded.image_type,sort_order=excluded.sort_order,
                        is_cover=excluded.is_cover,source=excluded.source
                        where showcase_product_images.product_id=excluded.product_id
                        and showcase_product_images.source in ('inventory_import','legacy_unknown')""",
                        [(f"{product_id}|body|{i}", product_id, path, i, int(i == 0)) for i, path in enumerate(paths)])
                if previous and source_key and aliases.get((scope, source_key)) == product_id:
                    # 当前键已保存在 showcase_products.source_product_key 中，无需重复留作 alias。
                    conn.execute("delete from showcase_source_identity_aliases where source_scope=? and source_key=? and product_id=?",
                                 (scope, source_key, product_id))
                    aliases.pop((scope, source_key), None)

            for product_id in missing_ids:
                conn.execute("update showcase_products set source_available=0,review_state='missing',updated_at=?,row_version=row_version+1 where product_id=? and row_version=?",
                             (now, product_id, int(current_scope[product_id]["row_version"])))
                if conn.execute("select changes()").fetchone()[0] != 1:
                    raise ImportReviewConflictError(f"全量缺失商品版本已变化：{product_id}")

            missing_count = len(missing_ids)
            conn.execute("""insert into showcase_import_logs
                (import_id,source_path,imported_at,inserted_count,updated_count,missing_count,mode,scope,status,started_at,committed_at,source_fingerprint)
                values (?,?,?,?,?,?,?,?,?,?,?,?)""",
                (import_id, batch["source_path"], now, inserted, updated, missing_count, batch["mode"], scope,
                 "committed", now, now, batch["source_fingerprint"]))
            conn.execute("insert into showcase_settings(setting_key,setting_value) values ('inventory_updated_at',?) on conflict(setting_key) do update set setting_value=excluded.setting_value", (now,))
            conn.execute("insert into showcase_settings(setting_key,setting_value) values ('catalog_revision',?) on conflict(setting_key) do update set setting_value=excluded.setting_value", (str(base_revision + 1),))
            result = {"import_id": import_id, "inserted_count": inserted, "updated_count": updated, "missing_count": missing_count}
            conn.execute("update showcase_import_review_rows set status='committed',updated_at=? where batch_id=? and status='pending'", (now, batch_id))
            conn.execute("update showcase_import_review_batches set status='committed',idempotency_key=?,result_json=?,completed_at=? where batch_id=? and status='pending'",
                         (idempotency_key, json.dumps(result, ensure_ascii=False, separators=(",", ":")), now, batch_id))
            conn.commit()
            return result
        except Exception:
            conn.rollback()
            raise


def _fetch_dict(conn, sql: str, params=()):
    cursor = conn.execute(sql, params)
    row = cursor.fetchone()
    return dict(zip((column[0] for column in cursor.description), row)) if row else None


def _fetch_all_dict(conn, sql: str, params=()):
    cursor = conn.execute(sql, params)
    columns = [column[0] for column in cursor.description]
    return [dict(zip(columns, row)) for row in cursor.fetchall()]
