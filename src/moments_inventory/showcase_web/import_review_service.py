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
    idempotency_key: str = "",
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
        for error in item["errors"]
    ]
    if row_errors:
        raise ValueError("工作簿行校验失败：" + "；".join(row_errors))
    if mode == "full" and (not complete or not parsed):
        raise ValueError("全量导入需要完整性声明且不能是空表")
    now = datetime.now(timezone.utc).isoformat()
    batch_id = uuid4().hex
    fingerprint = hashlib.sha256(content).hexdigest()

    with repository._read_connection() as conn:
        aliases = {}
        for alias_scope, source_key, product_id in conn.execute(
            "select source_scope,source_key,product_id from showcase_source_identity_aliases"
        ).fetchall():
            aliases.setdefault(str(source_key), []).append((str(alias_scope), str(product_id)))
        scoped_product_ids = {str(row[0]) for row in conn.execute(
            "select product_id from showcase_products where source_scope=?", (source_scope,)
        ).fetchall()}
    # sqlite rows become tuples without row_factory, map them explicitly.
    with repository._read_connection() as conn:
        cursor = conn.execute(
            "select product_id,model,brand,row_version,source_scope,source_product_key from showcase_products"
        )
        columns = [column[0] for column in cursor.description]
        products = [dict(zip(columns, row)) for row in cursor.fetchall()]
    products_by_id = {str(product["product_id"]): product for product in products}
    by_source_key = {
        (str(product["source_scope"]), str(product["source_product_key"])): product
        for product in products if str(product["source_product_key"] or "")
    }

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
    resolved_targets: set[str] = set()
    for item in parsed:
        record = item["snapshot"] if "product_id" in item["snapshot"] else None
        errors = item["errors"]
        recommendation = None
        candidates = []
        if record:
            source_key = item["source_key"]
            if source_key:
                other_scope = next((product for (scope, key), product in by_source_key.items()
                                    if key == source_key and scope != source_scope), None)
                other_alias = next((product_id for scope, product_id in aliases.get(source_key, ())
                                    if scope != source_scope), None)
                if other_scope is not None or other_alias is not None:
                    errors.append("来源商品键已属于其他来源范围")
                else:
                    exact = by_source_key.get((source_scope, source_key))
                    alias_id = next((product_id for scope, product_id in aliases.get(source_key, ())
                                     if scope == source_scope), None)
                    target = exact or (products_by_id.get(alias_id) if alias_id else None)
                    if target:
                        recommendation = _product_summary(target, "source_key" if exact else "alias")
                        selected_targets.setdefault(str(target["product_id"]), []).append(item)
                        resolved_targets.add(str(target["product_id"]))
            source_product_id = str(record.get("product_id", ""))
            existing_id = products_by_id.get(source_product_id)
            if existing_id and existing_id["source_scope"] != source_scope:
                errors.append("商品ID已属于其他来源范围")
            model_key = normalize_showcase_model_key(str(record.get("model", "")))
            brand = str(record.get("brand", ""))
            for product in products:
                if product["brand"] == brand and normalize_showcase_model_key(str(product["model"])) == model_key:
                    candidates.append(_product_summary(product, "model"))
                    if len(candidates) == 5:
                        break
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

    missing_count = len(scoped_product_ids - resolved_targets) if mode == "full" else 0
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
        "idempotency_key": idempotency_key,
        "result_json": json.dumps({"warnings": warnings}, ensure_ascii=False),
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
