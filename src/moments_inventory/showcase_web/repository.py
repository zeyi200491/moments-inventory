from __future__ import annotations

import sqlite3
import hashlib
import json
import threading
from contextlib import contextmanager
from dataclasses import replace
from pathlib import Path
from uuid import uuid4

from moments_inventory.showcase_web.migrations import migrate

from moments_inventory.showcase_brands import KNOWN_SHOWCASE_BRANDS
from moments_inventory.showcase_web.models import (
    ShowcaseAdminOperationLog,
    ShowcaseAdminProductSearch,
    ShowcaseAdminProductSearchResult,
    ShowcaseAdminProductSummary,
    ShowcaseAuthorizedPartner,
    ShowcaseGalleryAlbum,
    ShowcaseGalleryImage,
    ShowcaseProduct,
    ShowcaseProductImage,
    ShowcaseProductSearch,
    ShowcaseProductSearchResult,
    ShowcasePurchaseStep,
    ShowcaseSection,
    ShowcaseSectionItem,
)


SALES_TAG_RULES: dict[str, tuple[str, ...]] = {
    "新手推荐": ("新手", "操作简单", "闭眼入", "好上手"),
    "礼盒装": ("礼盒", "精品礼盒", "送礼"),
    "长焦": ("长焦", "10倍", "12倍", "20倍", "25倍", "30倍", "演唱会"),
    "自拍": ("自拍", "翻转屏"),
    "小巧": ("小巧", "便携", "超薄", "口袋"),
    "冷白皮": ("冷白皮", "冷白"),
    "氛围感": ("氛围感", "胶片感", "复古"),
}

PUBLIC_SALES_FILTER_TAGS: tuple[str, ...] = (
    "长焦",
    "自拍",
    "小巧",
    "冷白皮",
    "氛围感",
)

DEFAULT_GALLERY_ALBUMS: tuple[tuple[str, str, str], ...] = (
    ("camera-real", "相机实拍", "真实库存、不同颜色、不同机型外观。"),
    ("gift-box", "礼盒装展示", "礼盒、包装、配件、发货前状态。"),
    ("studio-daily", "工作室日常", "整理相机、打包、检测、拍摄台。"),
    ("buyer-feedback", "买家反馈", "客户好评截图、收到货反馈、出片反馈。"),
)

DEFAULT_PURCHASE_STEPS: tuple[tuple[str, str, str], ...] = (
    ("choose-model", "挑选型号", "按品牌、预算、关键词筛选喜欢的 CCD。"),
    ("copy-inquiry", "复制咨询文案", "点商品卡片里的复制按钮，回微信发给我。"),
    ("wechat-service", "微信咨询客服", "确认这台是否还在、是否适合你的需求。"),
    ("check-video", "核对验机视频", "看开机、拍摄、闪光、读卡、外观成色和配件。"),
    ("confirm-rules", "确认售后规则", "二手 CCD 默认有使用痕迹，售后规则提前确认。"),
    ("pay-lock", "付款锁单", "确认无误后付款，避免被别人先订走。"),
    ("ship", "安排发货", "打包发出，收到请录完整开箱视频。"),
)


def list_sales_tags() -> list[str]:
    return list(PUBLIC_SALES_FILTER_TAGS)


def product_sales_tags(product: ShowcaseProduct) -> list[str]:
    raw_text = " ".join(
        [
            product.model,
            product.brand,
            product.raw_copy,
            product.display_copy,
            product.short_selling_point,
            product.recommend_tags,
        ]
    )
    tags: list[str] = []
    seen: set[str] = set()
    for raw_tag in product.recommend_tags.replace("，", ",").split(","):
        tag = raw_tag.strip()
        if tag and tag not in seen:
            seen.add(tag)
            tags.append(tag)
    for tag, keywords in SALES_TAG_RULES.items():
        if tag in seen:
            continue
        if any(keyword in raw_text for keyword in keywords):
            seen.add(tag)
            tags.append(tag)
    return tags


def _sales_tags_json(*values: str) -> str:
    """写入时派生标签；查询直接读取索引映射表。"""
    tags = list(dict.fromkeys(value.strip() for value in values[-1].replace("，", ",").split(",") if value.strip()))
    text = " ".join(values)
    tags.extend(tag for tag, terms in SALES_TAG_RULES.items() if tag not in tags and any(term in text for term in terms))
    return json.dumps(tags, ensure_ascii=False)


def _build_public_product_filters(search: ShowcaseProductSearch) -> tuple[list[str], list[object]]:
    where = ["visible = 1", "sold = 0"]
    params: list[object] = []
    brands = _search_brands(search)
    if brands:
        placeholders = ", ".join("?" for _ in brands)
        where.append(f"brand in ({placeholders})")
        params.extend(brands)
    if search.price_min is not None:
        where.append("display_price >= ?")
        params.append(search.price_min)
    if search.price_max is not None:
        where.append("display_price <= ?")
        params.append(search.price_max)
    query = search.query.strip()
    if query:
        like = f"%{query}%"
        where.append(
            """
            (
              model like ?
              or brand like ?
              or raw_copy like ?
              or display_copy like ?
              or short_selling_point like ?
              or recommend_tags like ?
            )
            """
        )
        params.extend([like, like, like, like, like, like])
    for raw_tag in search.tags:
        tag = raw_tag.strip()
        if tag:
            where.append("product_id in (select product_id from showcase_product_tags where tag=?)")
            params.append(tag)
    return where, params


def _search_brands(search: ShowcaseProductSearch) -> tuple[str, ...]:
    brands: list[str] = []
    seen: set[str] = set()
    for raw_brand in (search.brand, *search.brands):
        brand = raw_brand.strip()
        if not brand or brand in seen:
            continue
        seen.add(brand)
        brands.append(brand)
    return tuple(brands)


def _public_product_order_by(sort: str) -> str:
    if sort == "price_asc":
        return "display_price asc, published_at desc, created_at desc, product_id asc"
    if sort == "price_desc":
        return "display_price desc, published_at desc, created_at desc, product_id asc"
    return "published_at desc, created_at desc, product_id asc"


def _public_product_select_sql(where_sql: str, order_by: str | None = None) -> str:
    order_sql = order_by or _public_product_order_by("latest")
    return f"""
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
               last_seen_import_id,
               short_selling_point,
               recommend_tags, public_id, row_version, source_scope, source_available, source_display_price, source_display_copy, source_visible, last_seen_at, price_override, copy_override, visibility_override, override_origin, review_state, last_verified_at
        from showcase_products
        where {where_sql}
        order by {order_sql}
        """


def _build_admin_product_filters(search: ShowcaseAdminProductSearch) -> tuple[list[str], list[object]]:
    where = ["1 = 1"]
    params: list[object] = []
    if search.brands:
        placeholders = ", ".join("?" for _ in search.brands)
        where.append(f"p.brand in ({placeholders})")
        params.extend(search.brands)
    if search.price_min is not None:
        where.append("p.display_price >= ?")
        params.append(search.price_min)
    if search.price_max is not None:
        where.append("p.display_price <= ?")
        params.append(search.price_max)
    if search.visible is not None:
        where.append("p.visible = ?")
        params.append(int(search.visible))
    if search.sold is not None:
        where.append("p.sold = ?")
        params.append(int(search.sold))
    if search.has_body_image is not None:
        operator = "exists" if search.has_body_image else "not exists"
        where.append(
            f"""
            {operator} (
              select 1 from showcase_all_product_images bi
              where bi.product_id = p.product_id and bi.image_type = 'body'
            )
            """
        )
    if search.has_sample_image is not None:
        operator = "exists" if search.has_sample_image else "not exists"
        where.append(
            f"""
            {operator} (
              select 1 from showcase_all_product_images si
              where si.product_id = p.product_id and si.image_type = 'sample'
            )
            """
        )
    if search.manual_price is not None:
        where.append(
            "p.price_override is not null"
            if search.manual_price
            else "p.price_override is null"
        )
    if search.section_id:
        where.append(
            """
            exists (
              select 1 from showcase_section_items section_filter
              where section_filter.product_id = p.product_id and section_filter.section_id = ?
            )
            """
        )
        params.append(search.section_id)
    if search.updated_after:
        where.append("p.updated_at >= ?")
        params.append(search.updated_after)
    if search.import_id:
        where.append("p.last_seen_import_id = ?")
        params.append(search.import_id)
    if search.review_state:
        where.append("p.review_state = ?")
        params.append(search.review_state)
    model = search.model.strip()
    if model:
        where.append("p.model like ?")
        params.append(f"%{model}%")
    query = search.query.strip()
    if query:
        like = f"%{query}%"
        where.append(
            """
            (
              p.product_id like ?
              or p.model like ?
              or p.brand like ?
              or p.raw_copy like ?
              or p.display_copy like ?
              or p.short_selling_point like ?
              or p.recommend_tags like ?
            )
            """
        )
        params.extend([like, like, like, like, like, like, like])
    for raw_tag in search.tags:
        tag = raw_tag.strip()
        if not tag:
            continue
        like = f"%{tag}%"
        where.append(
            """
            (
              p.model like ?
              or p.brand like ?
              or p.raw_copy like ?
              or p.display_copy like ?
              or p.short_selling_point like ?
              or p.recommend_tags like ?
            )
            """
        )
        params.extend([like, like, like, like, like, like])
    return where, params


def _admin_product_select_sql(where_sql: str) -> str:
    return f"""
        select p.product_id,
               p.model,
               p.brand,
               p.cost_price,
               p.display_price,
               p.visible,
               p.sold,
               p.published_at,
               p.raw_copy,
               p.display_copy,
               p.cover_image_path,
               p.created_at,
               p.updated_at,
               p.last_seen_import_id,
               p.short_selling_point,
               p.recommend_tags, p.public_id, p.row_version, p.source_scope, p.source_available, p.source_display_price, p.source_display_copy, p.source_visible, p.last_seen_at, p.price_override, p.copy_override, p.visibility_override, p.override_origin, p.review_state, p.last_verified_at,
               exists (
                 select 1 from showcase_all_product_images bi
                 where bi.product_id = p.product_id and bi.image_type = 'body'
               ) as has_body_image,
               exists (
                 select 1 from showcase_all_product_images si
                 where si.product_id = p.product_id and si.image_type = 'sample'
               ) as has_sample_image,
               p.price_override is not null as manual_price
        from showcase_products p
        where {where_sql}
        order by p.updated_at desc, p.published_at desc, p.product_id asc
        """


class SQLiteShowcaseRepository:
    def __init__(self, database_path: str | Path) -> None:
        self._database_path = str(database_path)
        self._connection: sqlite3.Connection | None = None
        self._lock = threading.RLock()
        self._initialized = False
        self.initialize()

    def _get_connection(self) -> sqlite3.Connection:
        with self._lock:
            if self._connection is None:
                if self._database_path != ":memory:":
                    Path(self._database_path).parent.mkdir(parents=True, exist_ok=True)
                self._connection = sqlite3.connect(
                    self._database_path,
                    check_same_thread=False,
                )
                self._connection.create_function("showcase_sales_tags", 6, _sales_tags_json, deterministic=True)
                self._connection.execute("pragma busy_timeout=5000")
                self._connection.execute("pragma foreign_keys=on")
                if self._database_path != ":memory:":
                    self._connection.execute("pragma journal_mode=wal")
            return self._connection

    @contextmanager
    def _read_connection(self):
        """文件库的读取使用短连接，让并发读无需等待全局写锁。"""
        if self._database_path == ":memory:":
            with self._lock:
                yield self._get_connection()
            return
        uri = Path(self._database_path).resolve().as_uri() + "?mode=ro"
        connection = sqlite3.connect(uri, uri=True, check_same_thread=False)
        connection.execute("pragma busy_timeout=5000")
        connection.execute("pragma query_only=on")
        try:
            yield connection
        finally:
            connection.close()

    def close(self) -> None:
        with self._lock:
            if self._connection is not None:
                self._connection.close()
                self._connection = None
                self._initialized = False

    def initialize(self) -> None:
        with self._lock:
            if self._initialized:
                return
            with self._get_connection() as conn:
                if migrate(conn):
                    _seed_default_gallery_albums(conn)
                    _seed_default_purchase_steps(conn)
            self._initialized = True

    def list_table_names(self) -> set[str]:
        with self._read_connection() as conn:
            rows = conn.execute(
                """
                select name
                from sqlite_master
                where type = 'table'
                """
            ).fetchall()
        return {str(row[0]) for row in rows}

    def upsert_product(self, product: ShowcaseProduct) -> None:
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
                      last_seen_import_id,
                      short_selling_point,
                      recommend_tags, public_id, row_version,
                      source_scope, source_available, source_display_price, source_display_copy,
                      source_visible, last_seen_at, price_override, copy_override,
                      visibility_override, override_origin, review_state, last_verified_at
                    )
                    values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                      last_seen_import_id = excluded.last_seen_import_id,
                      short_selling_point = excluded.short_selling_point,
                      recommend_tags = excluded.recommend_tags,
                      source_scope = excluded.source_scope,
                      source_available = excluded.source_available,
                      source_display_price = excluded.source_display_price,
                      source_display_copy = excluded.source_display_copy,
                      source_visible = excluded.source_visible,
                      last_seen_at = excluded.last_seen_at,
                      price_override = excluded.price_override,
                      copy_override = excluded.copy_override,
                      visibility_override = excluded.visibility_override,
                      override_origin = excluded.override_origin,
                      review_state = excluded.review_state,
                      last_verified_at = excluded.last_verified_at
                    """,
                    _product_to_row(product),
                )

                saved = conn.execute("select public_id, row_version from showcase_products where product_id=?", (product.product_id,)).fetchone()
                product.public_id, product.row_version = str(saved[0]), int(saved[1])

    def bulk_upsert_products_with_body_images(
        self,
        products: list[ShowcaseProduct],
        body_image_paths: dict[str, str],
    ) -> None:
        with self._lock:
            with self._get_connection() as conn:
                conn.executemany(
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
                      last_seen_import_id,
                      short_selling_point,
                      recommend_tags, public_id, row_version,
                      source_scope, source_available, source_display_price, source_display_copy,
                      source_visible, last_seen_at, price_override, copy_override,
                      visibility_override, override_origin, review_state, last_verified_at
                    )
                    values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                      last_seen_import_id = excluded.last_seen_import_id,
                      short_selling_point = excluded.short_selling_point,
                      recommend_tags = excluded.recommend_tags,
                      source_scope = excluded.source_scope,
                      source_available = excluded.source_available,
                      source_display_price = excluded.source_display_price,
                      source_display_copy = excluded.source_display_copy,
                      source_visible = excluded.source_visible,
                      last_seen_at = excluded.last_seen_at,
                      price_override = excluded.price_override,
                      copy_override = excluded.copy_override,
                      visibility_override = excluded.visibility_override,
                      override_origin = excluded.override_origin,
                      review_state = excluded.review_state,
                      last_verified_at = excluded.last_verified_at
                    """,
                    [_product_to_row(product) for product in products],
                )
                conn.executemany(
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
                    [
                        (
                            f"{product_id}|body|0",
                            product_id,
                            image_path,
                            "body",
                            0,
                            1,
                        )
                        for product_id, image_path in body_image_paths.items()
                        if image_path
                    ],
                )

                for product in products:
                    saved = conn.execute("select public_id, row_version from showcase_products where product_id=?", (product.product_id,)).fetchone()
                    product.public_id, product.row_version = str(saved[0]), int(saved[1])

    def replace_product_images_by_type(
        self, image_type: str, images: list[ShowcaseProductImage],
        *, product_ids: list[str] | None = None,
    ) -> None:
        targets = list(dict.fromkeys(product_ids)) if product_ids is not None else None
        if targets == []:
            return
        if targets is not None and any(image.product_id not in targets for image in images):
            raise ValueError("图片不属于目标商品范围")
        with self._lock:
            with self._get_connection() as conn:
                where = "image_type=? and source='auto_match'"
                params = [image_type]
                if targets is not None:
                    where += " and product_id in (" + ",".join("?" for _ in targets) + ")"
                    params.extend(targets)
                affected = {row[0] for row in conn.execute("select product_id from showcase_product_images where " + where, params)}
                conn.execute("delete from showcase_product_images where " + where, params)
                for image in images:
                    if image.image_type != image_type:
                        raise ValueError("图片类型与替换目标不符")
                    conn.execute("""insert into showcase_product_images
                        (image_id,product_id,image_path,image_type,sort_order,is_cover,source)
                        values (?,?,?,?,?,?,?)""",
                        (image.image_id,image.product_id,image.image_path,image.image_type,image.sort_order,int(image.is_cover),"auto_match"))
                    affected.add(image.product_id)
                for product_id in affected:
                    self._repair_cover(conn, product_id)

    def replace_sample_group_links(
        self, groups: dict[str, list[str]], product_groups: dict[str, str],
        *, product_ids: list[str] | None = None,
    ) -> None:
        targets = None if product_ids is None else set(product_ids)
        if targets is not None and not set(product_groups).issubset(targets):
            raise ValueError("样片绑定超出目标商品范围")
        if not set(product_groups.values()).issubset(groups):
            raise ValueError("样片绑定引用了未提供的图库")
        # 图库内容进入标识，局部刷新不会改变仍关联旧图库的其他商品。
        group_keys = {key: hashlib.sha256(json.dumps([key, list(dict.fromkeys(paths))], ensure_ascii=False).encode()).hexdigest() for key, paths in groups.items()}
        with self._lock:
            with self._get_connection() as conn:
                existing = {str(row[0]) for row in conn.execute("select product_id from showcase_products")}
                if not set(product_groups).issubset(existing):
                    raise ValueError("样片绑定引用了不存在的商品")
                affected = existing if targets is None else targets & existing
                if not affected:
                    return
                for folder, paths in groups.items():
                    group_key = group_keys[folder]
                    conn.execute("insert or ignore into showcase_sample_groups values (?)", (group_key,))
                    # 一张图库的图片只保存一份，商品通过一条关系关联。
                    conn.execute("delete from showcase_sample_group_images where group_key=?", (group_key,))
                    conn.executemany("insert into showcase_sample_group_images values (?,?,?,?)", [
                        (hashlib.sha256((group_key+"\0"+path).encode()).hexdigest(),group_key,path,order+10)
                        for order,path in enumerate(dict.fromkeys(paths))
                    ])
                conn.executemany("delete from showcase_product_sample_groups where product_id=?", [(key,) for key in affected])
                conn.executemany("delete from showcase_product_images where product_id=? and image_type='sample' and source='auto_match'", [(key,) for key in affected])
                conn.executemany("insert into showcase_product_sample_groups values (?,?)", [(key,group_keys[folder]) for key,folder in product_groups.items()])
                conn.execute("delete from showcase_sample_group_images where group_key not in (select group_key from showcase_product_sample_groups)")
                conn.execute("delete from showcase_sample_groups where group_key not in (select group_key from showcase_product_sample_groups)")
                for key in affected:
                    self._repair_cover(conn, key)

    def get_product(self, product_id: str) -> ShowcaseProduct | None:
        with self._read_connection() as conn:
            row = conn.execute(
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
                       last_seen_import_id,
                       short_selling_point,
                       recommend_tags, public_id, row_version, source_scope, source_available, source_display_price, source_display_copy, source_visible, last_seen_at, price_override, copy_override, visibility_override, override_origin, review_state, last_verified_at
                from showcase_products
                where product_id = ? or public_id = ?
                """,
                (product_id, product_id),
            ).fetchone()
        return _product_from_row(row) if row is not None else None

    def get_products_by_ids(self, product_ids: list[str]) -> dict[str, ShowcaseProduct]:
        normalized = list(dict.fromkeys(key for key in product_ids if key))
        if not normalized:
            return {}
        products: dict[str, ShowcaseProduct] = {}
        with self._read_connection() as conn:
            chunk_size = max(1, min(900, conn.getlimit(sqlite3.SQLITE_LIMIT_VARIABLE_NUMBER)))
            for start in range(0, len(normalized), chunk_size):
                chunk = normalized[start:start + chunk_size]
                placeholders = ",".join("?" for _ in chunk)
                rows = conn.execute(
                    _public_product_select_sql(f"product_id in ({placeholders})"),
                    chunk,
                ).fetchall()
                for row in rows:
                    product = _product_from_row(row)
                    products[product.product_id] = product
        return products

    def list_products(self, *, include_hidden: bool = False) -> list[ShowcaseProduct]:
        where_clause = "" if include_hidden else "where visible = 1"
        with self._read_connection() as conn:
            rows = conn.execute(
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
                       last_seen_import_id,
                       short_selling_point,
                       recommend_tags, public_id, row_version, source_scope, source_available, source_display_price, source_display_copy, source_visible, last_seen_at, price_override, copy_override, visibility_override, override_origin, review_state, last_verified_at
                from showcase_products
                {where_clause}
                order by published_at desc, product_id asc
                """
            ).fetchall()
        return [_product_from_row(row) for row in rows]

    def search_admin_products(
        self,
        search: ShowcaseAdminProductSearch | None = None,
    ) -> ShowcaseAdminProductSearchResult:
        search = search or ShowcaseAdminProductSearch()
        page_limit = min(max(search.limit, 1), 200)
        page_offset = max(search.offset, 0)
        where, params = _build_admin_product_filters(search)
        where_sql = " and ".join(where)
        with self._read_connection() as conn:
            total = int(
                conn.execute(
                    f"select count(*) from showcase_products p where {where_sql}",
                    params,
                ).fetchone()[0]
            )
            rows = conn.execute(
                f"{_admin_product_select_sql(where_sql)} limit ? offset ?",
                [*params, page_limit, page_offset],
            ).fetchall()
        return ShowcaseAdminProductSearchResult(
            products=[_admin_summary_from_row(row) for row in rows],
            total=total,
            limit=page_limit,
            offset=page_offset,
        )

    def list_admin_products_for_bulk(
        self,
        search: ShowcaseAdminProductSearch | None = None,
        *,
        product_ids: list[str] | None = None,
    ) -> list[ShowcaseAdminProductSummary]:
        search = search or ShowcaseAdminProductSearch(limit=100000)
        where, params = _build_admin_product_filters(replace(search, limit=100000, offset=0))
        normalized_ids = [product_id for product_id in dict.fromkeys(product_ids or []) if product_id]
        with self._read_connection() as conn:
            if not normalized_ids:
                rows = conn.execute(
                    _admin_product_select_sql(" and ".join(where)), params
                ).fetchall()
            else:
                rows = []
                # SQLite 默认变量上限可能只有 999，选择全库时按块解析。
                for start in range(0, len(normalized_ids), 500):
                    chunk = normalized_ids[start : start + 500]
                    placeholders = ", ".join("?" for _ in chunk)
                    chunk_where = [*where, f"p.product_id in ({placeholders})"]
                    rows.extend(
                        conn.execute(
                            _admin_product_select_sql(" and ".join(chunk_where)),
                            [*params, *chunk],
                        ).fetchall()
                    )
        return [_admin_summary_from_row(row) for row in rows]

    def resolve_product_references(self, references: list[str]) -> list[str]:
        """把 product_id/public_id 一次分块解析为稳定 product_id，保留输入顺序。"""
        normalized = [value for value in dict.fromkeys(references) if value]
        if not normalized:
            return []
        resolved: dict[str, str] = {}
        with self._read_connection() as conn:
            for start in range(0, len(normalized), 400):
                chunk = normalized[start : start + 400]
                placeholders = ",".join("?" for _ in chunk)
                rows = conn.execute(
                    f"select product_id,public_id from showcase_products "
                    f"where product_id in ({placeholders}) or public_id in ({placeholders})",
                    [*chunk, *chunk],
                ).fetchall()
                for row in rows:
                    resolved[str(row[0])] = str(row[0])
                    resolved[str(row[1])] = str(row[0])
        return [resolved.get(value, value) for value in normalized]

    def get_admin_product_summary(self, product_id: str) -> ShowcaseAdminProductSummary | None:
        items = self.list_admin_products_for_bulk(product_ids=[self._resolve_product_id(product_id)])
        return items[0] if items else None

    def search_products(
        self,
        search: ShowcaseProductSearch | None = None,
        *,
        limit: int | None = None,
        offset: int | None = None,
    ) -> ShowcaseProductSearchResult:
        search = search or ShowcaseProductSearch()
        if limit is not None:
            search = replace(search, limit=limit)
        if offset is not None:
            search = replace(search, offset=offset)
        page_limit = min(max(search.limit, 1), 120)
        page_offset = max(search.offset, 0)
        where, params = _build_public_product_filters(search)
        where_sql = " and ".join(where)
        order_by = _public_product_order_by(search.sort)
        with self._read_connection() as conn:
            if not conn.in_transaction:
                conn.execute("begin")
            revision_row = conn.execute(
                "select setting_value from showcase_settings where setting_key='catalog_revision'"
            ).fetchone()
            total = int(
                conn.execute(
                    f"select count(*) from showcase_products where {where_sql}",
                    params,
                ).fetchone()[0]
            )
            rows = conn.execute(
                f"{_public_product_select_sql(where_sql, order_by)} limit ? offset ?",
                [*params, page_limit, page_offset],
            ).fetchall()
        return ShowcaseProductSearchResult(
            products=[_product_from_row(row) for row in rows],
            total=total,
            limit=page_limit,
            offset=page_offset,
            catalog_revision=str(revision_row[0]) if revision_row else "0",
        )

    def list_public_brands(self) -> list[str]:
        with self._read_connection() as conn:
            rows = conn.execute(
                """
                select distinct brand
                from showcase_products
                where visible = 1 and sold = 0 and brand != ''
                order by brand
                """
            ).fetchall()
        available = {str(row[0]) for row in rows}
        ordered = [brand for brand in KNOWN_SHOWCASE_BRANDS if brand in available]
        extras = sorted(available - set(ordered))
        return [*ordered, *extras]

    def update_product_price(self, product_id: str, display_price: int) -> bool:
        product_id = self._resolve_product_id(product_id)
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
        product_id = self._resolve_product_id(product_id)
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

    def save_admin_operation(
        self,
        *,
        operation_id: str,
        operation_type: str,
        summary: str,
        filter_text: str,
        updated_count: int,
        created_at: str,
        items: list[dict[str, object]],
    ) -> None:
        with self._lock:
            with self._get_connection() as conn:
                conn.execute(
                    """
                    insert into showcase_admin_operation_logs (
                      operation_id,
                      operation_type,
                      summary,
                      filter_text,
                      updated_count,
                      created_at,
                      undone_at
                    )
                    values (?, ?, ?, ?, ?, ?, '')
                    """,
                    (
                        operation_id,
                        operation_type,
                        summary,
                        filter_text,
                        updated_count,
                        created_at,
                    ),
                )
                conn.executemany(
                    """
                    insert into showcase_admin_operation_items (
                      item_id,
                      operation_id,
                      product_id,
                      old_price,
                      new_price,
                      old_visible,
                      new_visible
                    )
                    values (?, ?, ?, ?, ?, ?, ?)
                    """,
                    [
                        (
                            str(item["item_id"]),
                            operation_id,
                            str(item["product_id"]),
                            item.get("old_price"),
                            item.get("new_price"),
                            item.get("old_visible"),
                            item.get("new_visible"),
                        )
                        for item in items
                    ],
                )

    def list_admin_operations(self, *, limit: int = 30) -> list[ShowcaseAdminOperationLog]:
        with self._read_connection() as conn:
            rows = conn.execute(
                """
                select operation_id,
                       operation_type,
                       summary,
                       filter_text,
                       updated_count,
                       created_at,
                       undone_at
                from showcase_admin_operation_logs
                order by created_at desc, operation_id desc
                limit ?
                """,
                (max(1, min(limit, 100)),),
            ).fetchall()
        return [
            ShowcaseAdminOperationLog(
                operation_id=str(row[0]),
                operation_type=str(row[1]),
                summary=str(row[2]),
                filter_text=str(row[3]),
                updated_count=int(row[4]),
                created_at=str(row[5]),
                undone_at=str(row[6]),
            )
            for row in rows
        ]

    def undo_admin_price_operation(self, operation_id: str, undone_at: str) -> int:
        with self._lock:
            with self._get_connection() as conn:
                log = conn.execute(
                    """
                    select operation_type, undone_at
                    from showcase_admin_operation_logs
                    where operation_id = ?
                    """,
                    (operation_id,),
                ).fetchone()
                if log is None or str(log[0]) != "price" or str(log[1]):
                    return 0
                rows = conn.execute(
                    """
                    select product_id, old_price
                    from showcase_admin_operation_items
                    where operation_id = ? and old_price is not null
                    """,
                    (operation_id,),
                ).fetchall()
                for row in rows:
                    conn.execute(
                        """
                        update showcase_products
                        set display_price = ?, updated_at = ?
                        where product_id = ?
                        """,
                        (int(row[1]), undone_at, str(row[0])),
                    )
                conn.execute(
                    """
                    update showcase_admin_operation_logs
                    set undone_at = ?
                    where operation_id = ?
                    """,
                    (undone_at, operation_id),
                )
                return len(rows)

    def save_sample_folder_binding(
        self,
        *,
        binding_key: str,
        product_id: str,
        model_key: str,
        brand: str,
        folder_path: str,
        created_at: str,
        updated_at: str,
    ) -> None:
        with self._lock:
            with self._get_connection() as conn:
                conn.execute(
                    """
                    insert into showcase_sample_folder_bindings (
                      binding_key,
                      product_id,
                      model_key,
                      brand,
                      folder_path,
                      created_at,
                      updated_at
                    )
                    values (?, ?, ?, ?, ?, ?, ?)
                    on conflict(binding_key) do update set
                      product_id = excluded.product_id,
                      model_key = excluded.model_key,
                      brand = excluded.brand,
                      folder_path = excluded.folder_path,
                      updated_at = excluded.updated_at
                    """,
                    (
                        binding_key,
                        product_id,
                        model_key,
                        brand,
                        folder_path,
                        created_at,
                        updated_at,
                    ),
                )

    def list_sample_folder_bindings(self) -> dict[str, str]:
        with self._read_connection() as conn:
            rows = conn.execute(
                """
                select binding_key, folder_path
                from showcase_sample_folder_bindings
                """
            ).fetchall()
        return {str(row[0]): str(row[1]) for row in rows}

    def create_database_backup(self, backup_dir: str | Path, *, filename: str) -> Path:
        target_dir = Path(backup_dir)
        target_dir.mkdir(parents=True, exist_ok=True)
        target_path = target_dir / filename
        with self._lock:
            source = self._get_connection()
            with sqlite3.connect(target_path) as backup:
                source.backup(backup)
        return target_path

    def _resolve_product_id(self, product_id: str) -> str:
        with self._read_connection() as conn:
            row = conn.execute(
                "select product_id from showcase_products where product_id=? or public_id=?",
                (product_id, product_id),
            ).fetchone()
        return str(row[0]) if row else product_id

    def add_product_image(
        self, image_id: str, product_id: str, image_path: str,
        image_type: str, sort_order: int, is_cover: bool,
        source: str = "manual_upload",
    ) -> None:
        product_id = self._resolve_product_id(product_id)
        with self._lock:
            with self._get_connection() as conn:
                conn.execute("""insert into showcase_product_images
                    (image_id,product_id,image_path,image_type,sort_order,is_cover,source)
                    values (?,?,?,?,?,?,?)
                    on conflict(image_id) do update set
                    image_path=excluded.image_path,image_type=excluded.image_type,
                    sort_order=excluded.sort_order,is_cover=excluded.is_cover,source=excluded.source
                    where showcase_product_images.product_id=excluded.product_id""",
                    (image_id,product_id,image_path,image_type,sort_order,int(is_cover),source))
                if is_cover:
                    conn.execute("update showcase_product_images set is_cover=(image_id=?) where product_id=?", (image_id,product_id))
                    conn.execute("update showcase_products set cover_image_path=? where product_id=?", (image_path,product_id))

    def get_product_image(self, image_id: str) -> ShowcaseProductImage | None:
        with self._read_connection() as conn:
            row = conn.execute(
                "select image_id,product_id,image_path,image_type,sort_order,is_cover,source from showcase_all_product_images where image_id=?",
                (image_id,),
            ).fetchone()
        return ShowcaseProductImage(*row[:5], bool(row[5]), str(row[6])) if row else None

    def list_product_images(self, product_id: str) -> list[ShowcaseProductImage]:
        product_id = self._resolve_product_id(product_id)
        with self._read_connection() as conn:
            rows = conn.execute(
                """select image_id,product_id,image_path,image_type,sort_order,is_cover,source
                from showcase_all_product_images where product_id=? order by sort_order,image_id""",
                (product_id,),
            ).fetchall()
        return [ShowcaseProductImage(*row[:5],bool(row[5]),str(row[6])) for row in rows]

    @staticmethod
    def _repair_cover(conn: sqlite3.Connection, product_id: str) -> None:
        row = conn.execute("select cover_image_path from showcase_products where product_id=?", (product_id,)).fetchone()
        if row is None:
            return
        image = conn.execute("""select image_id,image_path from showcase_all_product_images
            where product_id=? order by (image_path=?) desc,is_cover desc,sort_order,image_id limit 1""", (product_id,row[0])).fetchone()
        path = str(image[1]) if image else ""
        conn.execute("update showcase_product_images set is_cover=(image_id=?) where product_id=?", (image[0] if image else "",product_id))
        conn.execute("update showcase_products set cover_image_path=? where product_id=?", (path,product_id))

    def list_first_image_paths_by_type(self, image_type: str) -> dict[str, str]:
        with self._read_connection() as conn:
            rows = conn.execute(
                """
                select product_id, image_path
                from (
                  select product_id,
                         image_path,
                         row_number() over (
                           partition by product_id
                           order by sort_order asc, image_id asc
                         ) as row_index
                  from showcase_all_product_images
                  where image_type = ?
                )
                where row_index = 1
                """,
                (image_type,),
            ).fetchall()
        return {str(row[0]): str(row[1]) for row in rows}

    def list_first_image_paths_by_type_for_products(
        self, image_type: str, product_ids: list[str],
    ) -> dict[str, str]:
        normalized_ids = [key for key in dict.fromkeys(product_ids) if key]
        result: dict[str, str] = {}
        with self._read_connection() as conn:
            chunk_size = max(1, min(900, conn.getlimit(sqlite3.SQLITE_LIMIT_VARIABLE_NUMBER) - 1))
            for start in range(0, len(normalized_ids), chunk_size):
                chunk = normalized_ids[start:start + chunk_size]
                placeholders = ",".join("?" for _ in chunk)
                rows = conn.execute(f"""select product_id,image_path from (
                    select product_id,image_path,row_number() over (
                        partition by product_id order by sort_order,image_id) as row_index
                    from showcase_all_product_images where image_type=? and product_id in ({placeholders})
                    ) where row_index=1""", [image_type,*chunk]).fetchall()
                result.update((str(row[0]),str(row[1])) for row in rows)
        return result

    def reorder_product_images(self, product_id: str, image_ids: list[str]) -> None:
        product_id = self._resolve_product_id(product_id)
        with self._lock:
            with self._get_connection() as conn:
                for sort_order, image_id in enumerate(image_ids):
                    if image_id.startswith("shared:"):
                        image = self.get_product_image(image_id)
                        if image is None or image.product_id != product_id:
                            continue
                        conn.execute("""insert into showcase_sample_image_overrides(product_id,image_id,sort_order)
                            values (?,?,?) on conflict(product_id,image_id) do update set sort_order=excluded.sort_order""",
                            (product_id,image_id.rsplit(":",1)[1],sort_order))
                    else:
                        conn.execute("update showcase_product_images set sort_order=? where product_id=? and image_id=?", (sort_order,product_id,image_id))
                conn.execute("update showcase_products set row_version=row_version+1 where product_id=?", (product_id,))

    def set_product_cover_image(self, product_id: str, image_id: str) -> bool:
        product_id = self._resolve_product_id(product_id)
        with self._lock:
            with self._get_connection() as conn:
                row = conn.execute(
                    """
                    select image_path
                    from showcase_all_product_images
                    where product_id = ? and image_id = ?
                    """,
                    (product_id, image_id),
                ).fetchone()
                if row is None:
                    return False
                conn.execute(
                    """
                    update showcase_product_images
                    set is_cover = 0
                    where product_id = ?
                    """,
                    (product_id,),
                )
                conn.execute(
                    """
                    update showcase_product_images
                    set is_cover = 1
                    where product_id = ? and image_id = ?
                    """,
                    (product_id, image_id),
                )
                conn.execute(
                    """
                    update showcase_products
                    set cover_image_path = ?
                    where product_id = ?
                    """,
                    (str(row[0]), product_id),
                )
                return True

    def delete_product_image(self, product_id: str, image_id: str) -> bool:
        product_id = self._resolve_product_id(product_id)
        with self._lock:
            with self._get_connection() as conn:
                if image_id.startswith("shared:"):
                    image = self.get_product_image(image_id)
                    if image is None or image.product_id != product_id:
                        return False
                    conn.execute("""insert into showcase_sample_image_overrides(product_id,image_id,hidden)
                        values (?,?,1) on conflict(product_id,image_id) do update set hidden=1""",
                        (product_id,image_id.rsplit(":",1)[1]))
                else:
                    cursor = conn.execute("delete from showcase_product_images where product_id=? and image_id=?", (product_id,image_id))
                    if cursor.rowcount == 0:
                        return False
                self._repair_cover(conn, product_id)
                return True

    def upsert_gallery_album(self, album: ShowcaseGalleryAlbum) -> None:
        with self._lock:
            with self._get_connection() as conn:
                conn.execute(
                    """
                    insert into showcase_gallery_albums (
                      album_id,
                      title,
                      description,
                      sort_order,
                      is_visible,
                      created_at,
                      updated_at
                    )
                    values (?, ?, ?, ?, ?, ?, ?)
                    on conflict(album_id) do update set
                      title = excluded.title,
                      description = excluded.description,
                      sort_order = excluded.sort_order,
                      is_visible = excluded.is_visible,
                      updated_at = excluded.updated_at
                    """,
                    (
                        album.album_id,
                        album.title,
                        album.description,
                        album.sort_order,
                        int(album.is_visible),
                        album.created_at,
                        album.updated_at,
                    ),
                )

    def get_gallery_album(self, album_id: str) -> ShowcaseGalleryAlbum | None:
        with self._read_connection() as conn:
            row = conn.execute(
                """
                select album_id, title, description, sort_order, is_visible, created_at, updated_at
                from showcase_gallery_albums
                where album_id = ?
                """,
                (album_id,),
            ).fetchone()
        return _gallery_album_from_row(row) if row is not None else None

    def list_gallery_albums(
        self,
        *,
        include_hidden: bool = False,
    ) -> list[ShowcaseGalleryAlbum]:
        where_clause = "" if include_hidden else "where is_visible = 1"
        with self._read_connection() as conn:
            rows = conn.execute(
                f"""
                select album_id, title, description, sort_order, is_visible, created_at, updated_at
                from showcase_gallery_albums
                {where_clause}
                order by sort_order asc, album_id asc
                """
            ).fetchall()
        return [_gallery_album_from_row(row) for row in rows]

    def delete_gallery_album(self, album_id: str) -> bool:
        with self._lock:
            with self._get_connection() as conn:
                conn.execute("delete from showcase_gallery_images where album_id = ?", (album_id,))
                cursor = conn.execute(
                    "delete from showcase_gallery_albums where album_id = ?",
                    (album_id,),
                )
                return cursor.rowcount > 0

    def add_gallery_image(self, image: ShowcaseGalleryImage) -> None:
        with self._lock:
            with self._get_connection() as conn:
                conn.execute(
                    """
                    insert into showcase_gallery_images (
                      image_id,
                      album_id,
                      image_path,
                      caption,
                      sort_order,
                      is_visible,
                      created_at,
                      updated_at
                    )
                    values (?, ?, ?, ?, ?, ?, ?, ?)
                    on conflict(image_id) do update set
                      album_id = excluded.album_id,
                      image_path = excluded.image_path,
                      caption = excluded.caption,
                      sort_order = excluded.sort_order,
                      is_visible = excluded.is_visible,
                      updated_at = excluded.updated_at
                    """,
                    (
                        image.image_id,
                        image.album_id,
                        image.image_path,
                        image.caption,
                        image.sort_order,
                        int(image.is_visible),
                        image.created_at,
                        image.updated_at,
                    ),
                )

    def get_gallery_image(self, image_id: str) -> ShowcaseGalleryImage | None:
        with self._read_connection() as conn:
            row = conn.execute(
                """
                select image_id, album_id, image_path, caption, sort_order, is_visible, created_at, updated_at
                from showcase_gallery_images
                where image_id = ?
                """,
                (image_id,),
            ).fetchone()
        return _gallery_image_from_row(row) if row is not None else None

    def list_gallery_images(
        self,
        album_id: str,
        *,
        include_hidden: bool = False,
    ) -> list[ShowcaseGalleryImage]:
        where_clause = "album_id = ?"
        if not include_hidden:
            where_clause += " and is_visible = 1"
        with self._read_connection() as conn:
            rows = conn.execute(
                f"""
                select image_id, album_id, image_path, caption, sort_order, is_visible, created_at, updated_at
                from showcase_gallery_images
                where {where_clause}
                order by sort_order asc, image_id asc
                """,
                (album_id,),
            ).fetchall()
        return [_gallery_image_from_row(row) for row in rows]

    def reorder_gallery_images(self, album_id: str, image_ids: list[str]) -> None:
        with self._lock:
            with self._get_connection() as conn:
                for sort_order, image_id in enumerate(image_ids):
                    conn.execute(
                        """
                        update showcase_gallery_images
                        set sort_order = ?
                        where album_id = ? and image_id = ?
                        """,
                        (sort_order, album_id, image_id),
                    )

    def delete_gallery_image(self, image_id: str) -> bool:
        with self._lock:
            with self._get_connection() as conn:
                cursor = conn.execute(
                    "delete from showcase_gallery_images where image_id = ?",
                    (image_id,),
                )
                return cursor.rowcount > 0

    def upsert_purchase_step(self, step: ShowcasePurchaseStep) -> None:
        with self._lock:
            with self._get_connection() as conn:
                conn.execute(
                    """
                    insert into showcase_purchase_steps (
                      step_id,
                      title,
                      description,
                      sort_order,
                      is_visible,
                      created_at,
                      updated_at
                    )
                    values (?, ?, ?, ?, ?, ?, ?)
                    on conflict(step_id) do update set
                      title = excluded.title,
                      description = excluded.description,
                      sort_order = excluded.sort_order,
                      is_visible = excluded.is_visible,
                      updated_at = excluded.updated_at
                    """,
                    (
                        step.step_id,
                        step.title,
                        step.description,
                        step.sort_order,
                        int(step.is_visible),
                        step.created_at,
                        step.updated_at,
                    ),
                )

    def get_purchase_step(self, step_id: str) -> ShowcasePurchaseStep | None:
        with self._read_connection() as conn:
            row = conn.execute(
                """
                select step_id, title, description, sort_order, is_visible, created_at, updated_at
                from showcase_purchase_steps
                where step_id = ?
                """,
                (step_id,),
            ).fetchone()
        return _purchase_step_from_row(row) if row is not None else None

    def list_purchase_steps(
        self,
        *,
        include_hidden: bool = False,
    ) -> list[ShowcasePurchaseStep]:
        where_clause = "" if include_hidden else "where is_visible = 1"
        with self._read_connection() as conn:
            rows = conn.execute(
                f"""
                select step_id, title, description, sort_order, is_visible, created_at, updated_at
                from showcase_purchase_steps
                {where_clause}
                order by sort_order asc, step_id asc
                """
            ).fetchall()
        return [_purchase_step_from_row(row) for row in rows]

    def delete_purchase_step(self, step_id: str) -> bool:
        with self._lock:
            with self._get_connection() as conn:
                cursor = conn.execute(
                    "delete from showcase_purchase_steps where step_id = ?",
                    (step_id,),
                )
                return cursor.rowcount > 0

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

    def list_import_logs(self, *, limit: int = 20) -> list[dict[str, object]]:
        with self._read_connection() as conn:
            rows = conn.execute(
                """
                select import_id,
                       source_path,
                       imported_at,
                       inserted_count,
                       updated_count,
                       missing_count
                from showcase_import_logs
                order by imported_at desc, import_id desc
                limit ?
                """,
                (max(1, min(limit, 100)),),
            ).fetchall()
        return [
            {
                "import_id": str(row[0]),
                "source_path": str(row[1]),
                "imported_at": str(row[2]),
                "inserted_count": int(row[3]),
                "updated_count": int(row[4]),
                "missing_count": int(row[5]),
                "unmatched_count": 0,
                "missing_image_count": 0,
            }
            for row in rows
        ]

    def list_product_ids(self) -> set[str]:
        with self._read_connection() as conn:
            rows = conn.execute(
                "select product_id from showcase_products"
            ).fetchall()
        return {str(row[0]) for row in rows}

    def set_setting(self, key: str, value: str) -> None:
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
        with self._read_connection() as conn:
            row = conn.execute(
                """
                select setting_value
                from showcase_settings
                where setting_key = ?
                """,
                (key,),
            ).fetchone()
        return str(row[0]) if row is not None else None

    def save_admin_session(self, session_id: str, expires_at: str) -> None:
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
        with self._read_connection() as conn:
            row = conn.execute(
                """
                select expires_at
                from showcase_admin_sessions
                where session_id = ?
                """,
                (session_id,),
            ).fetchone()
        return str(row[0]) if row is not None else None

    def save_customer_session(self, session_id: str, expires_at: str) -> None:
        with self._lock:
            with self._get_connection() as conn:
                conn.execute(
                    """
                    insert into showcase_customer_sessions (session_id, expires_at)
                    values (?, ?)
                    """,
                    (session_id, expires_at),
                )

    def get_customer_session_expires_at(self, session_id: str) -> str | None:
        with self._read_connection() as conn:
            row = conn.execute(
                """
                select expires_at
                from showcase_customer_sessions
                where session_id = ?
                """,
                (session_id,),
            ).fetchone()
        return str(row[0]) if row is not None else None

    def delete_product(self, product_id: str) -> bool:
        product_id = self._resolve_product_id(product_id)
        with self._lock:
            with self._get_connection() as conn:
                # 专栏是当前展示关系，可以随商品删除；批量操作项是审计快照，保留历史。
                conn.execute("delete from showcase_section_items where product_id=?", (product_id,))
                conn.execute("delete from showcase_sample_folder_bindings where product_id=?", (product_id,))
                conn.execute("delete from showcase_product_sample_groups where product_id=?", (product_id,))
                conn.execute("delete from showcase_sample_image_overrides where product_id=?", (product_id,))
                conn.execute(
                    "delete from showcase_product_images where product_id = ?",
                    (product_id,),
                )
                cursor = conn.execute(
                    "delete from showcase_products where product_id = ?",
                    (product_id,),
                )
                return cursor.rowcount > 0

    def add_authorized_partner(
        self,
        partner_id: str,
        name: str,
        note: str,
        sort_order: int,
        active: bool,
    ) -> None:
        with self._lock:
            with self._get_connection() as conn:
                conn.execute(
                    """
                    insert into showcase_authorized_partners (
                      partner_id,
                      name,
                      note,
                      sort_order,
                      active
                    )
                    values (?, ?, ?, ?, ?)
                    on conflict(partner_id) do update set
                      name = excluded.name,
                      note = excluded.note,
                      sort_order = excluded.sort_order,
                      active = excluded.active
                    """,
                    (partner_id, name, note, sort_order, int(active)),
                )

    def list_authorized_partners(
        self,
        *,
        active_only: bool = False,
    ) -> list[ShowcaseAuthorizedPartner]:
        where_clause = "where active = 1" if active_only else ""
        with self._read_connection() as conn:
            rows = conn.execute(
                f"""
                select partner_id, name, note, sort_order, active
                from showcase_authorized_partners
                {where_clause}
                order by sort_order asc, partner_id asc
                """
            ).fetchall()
        return [
            ShowcaseAuthorizedPartner(
                partner_id=str(row[0]),
                name=str(row[1]),
                note=str(row[2]),
                sort_order=int(row[3]),
                active=bool(row[4]),
            )
            for row in rows
        ]

    def get_authorized_partner(self, partner_id: str) -> ShowcaseAuthorizedPartner | None:
        with self._read_connection() as conn:
            row = conn.execute(
                """
                select partner_id, name, note, sort_order, active
                from showcase_authorized_partners
                where partner_id = ?
                """,
                (partner_id,),
            ).fetchone()
        if row is None:
            return None
        return ShowcaseAuthorizedPartner(
            partner_id=str(row[0]),
            name=str(row[1]),
            note=str(row[2]),
            sort_order=int(row[3]),
            active=bool(row[4]),
        )

    def delete_authorized_partner(self, partner_id: str) -> bool:
        with self._lock:
            with self._get_connection() as conn:
                cursor = conn.execute(
                    """
                    delete from showcase_authorized_partners
                    where partner_id = ?
                    """,
                    (partner_id,),
                )
                return cursor.rowcount > 0

    def upsert_section(self, section: ShowcaseSection) -> None:
        with self._lock:
            with self._get_connection() as conn:
                conn.execute(
                    """
                    insert into showcase_sections (
                      section_id,
                      title,
                      subtitle,
                      active,
                      sort_order,
                      created_at,
                      updated_at
                    )
                    values (?, ?, ?, ?, ?, ?, ?)
                    on conflict(section_id) do update set
                      title = excluded.title,
                      subtitle = excluded.subtitle,
                      active = excluded.active,
                      sort_order = excluded.sort_order,
                      created_at = excluded.created_at,
                      updated_at = excluded.updated_at
                    """,
                    (
                        section.section_id,
                        section.title,
                        section.subtitle,
                        int(section.active),
                        section.sort_order,
                        section.created_at,
                        section.updated_at,
                    ),
                )

    def list_sections(self, *, include_hidden: bool = False) -> list[ShowcaseSection]:
        where_clause = "" if include_hidden else "where active = 1"
        with self._read_connection() as conn:
            rows = conn.execute(
                f"""
                select section_id, title, subtitle, active, sort_order, created_at, updated_at
                from showcase_sections
                {where_clause}
                order by sort_order asc, section_id asc
                """
            ).fetchall()
        return [_section_from_row(row) for row in rows]

    def get_section(self, section_id: str) -> ShowcaseSection | None:
        with self._read_connection() as conn:
            row = conn.execute(
                """
                select section_id, title, subtitle, active, sort_order, created_at, updated_at
                from showcase_sections
                where section_id = ?
                """,
                (section_id,),
            ).fetchone()
        return _section_from_row(row) if row is not None else None

    def delete_section(self, section_id: str) -> bool:
        with self._lock:
            with self._get_connection() as conn:
                conn.execute(
                    "delete from showcase_section_items where section_id = ?",
                    (section_id,),
                )
                cursor = conn.execute(
                    "delete from showcase_sections where section_id = ?",
                    (section_id,),
                )
                return cursor.rowcount > 0

    def upsert_section_item(self, item: ShowcaseSectionItem) -> None:
        with self._lock:
            with self._get_connection() as conn:
                conn.execute(
                    """
                    insert into showcase_section_items (
                      item_id,
                      section_id,
                      product_id,
                      sort_order,
                      recommend_note,
                      created_at,
                      updated_at
                    )
                    values (?, ?, ?, ?, ?, ?, ?)
                    on conflict(item_id) do update set
                      section_id = excluded.section_id,
                      product_id = excluded.product_id,
                      sort_order = excluded.sort_order,
                      recommend_note = excluded.recommend_note,
                      created_at = excluded.created_at,
                      updated_at = excluded.updated_at
                    """,
                    (
                        item.item_id,
                        item.section_id,
                        item.product_id,
                        item.sort_order,
                        item.recommend_note,
                        item.created_at,
                        item.updated_at,
                    ),
                )

    def list_section_items(self, section_id: str) -> list[ShowcaseSectionItem]:
        with self._read_connection() as conn:
            rows = conn.execute(
                """
                select item_id, section_id, product_id, sort_order, recommend_note, created_at, updated_at
                from showcase_section_items
                where section_id = ?
                order by sort_order asc, item_id asc
                """,
                (section_id,),
            ).fetchall()
        return [_section_item_from_row(row) for row in rows]

    def get_section_item(self, item_id: str) -> ShowcaseSectionItem | None:
        with self._read_connection() as conn:
            row = conn.execute(
                """
                select item_id, section_id, product_id, sort_order, recommend_note, created_at, updated_at
                from showcase_section_items
                where item_id = ?
                """,
                (item_id,),
            ).fetchone()
        return _section_item_from_row(row) if row is not None else None

    def delete_section_item(self, item_id: str) -> bool:
        with self._lock:
            with self._get_connection() as conn:
                cursor = conn.execute(
                    "delete from showcase_section_items where item_id = ?",
                    (item_id,),
                )
                return cursor.rowcount > 0


def _ensure_column(
    conn: sqlite3.Connection,
    table_name: str,
    column_name: str,
    column_definition: str,
) -> None:
    rows = conn.execute(f"pragma table_info({table_name})").fetchall()
    if column_name in {str(row[1]) for row in rows}:
        return
    conn.execute(f"alter table {table_name} add column {column_name} {column_definition}")


def _seed_default_gallery_albums(conn: sqlite3.Connection) -> None:
    now = "2026-08-22T00:00:00+08:00"
    for sort_order, (album_id, title, description) in enumerate(DEFAULT_GALLERY_ALBUMS, start=1):
        conn.execute(
            """
            insert into showcase_gallery_albums (
              album_id,
              title,
              description,
              sort_order,
              is_visible,
              created_at,
              updated_at
            )
            values (?, ?, ?, ?, 1, ?, ?)
            on conflict(album_id) do nothing
            """,
            (album_id, title, description, sort_order, now, now),
        )


def _seed_default_purchase_steps(conn: sqlite3.Connection) -> None:
    now = "2026-08-22T00:00:00+08:00"
    for sort_order, (step_id, title, description) in enumerate(DEFAULT_PURCHASE_STEPS, start=1):
        conn.execute(
            """
            insert into showcase_purchase_steps (
              step_id,
              title,
              description,
              sort_order,
              is_visible,
              created_at,
              updated_at
            )
            values (?, ?, ?, ?, 1, ?, ?)
            on conflict(step_id) do nothing
            """,
            (step_id, title, description, sort_order, now, now),
        )


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
        product.short_selling_point,
        product.recommend_tags,
        product.public_id or str(uuid4()),
        product.row_version,
        product.source_scope,
        int(product.source_available),
        product.source_display_price,
        product.source_display_copy,
        int(product.source_visible),
        product.last_seen_at,
        product.price_override,
        product.copy_override,
        int(product.visibility_override) if product.visibility_override is not None else None,
        product.override_origin,
        product.review_state,
        product.last_verified_at,
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
        short_selling_point=str(row[14]),
        recommend_tags=str(row[15]),
        public_id=str(row[16]),
        row_version=int(row[17]),
        source_scope=str(row[18]),
        source_available=bool(row[19]),
        source_display_price=int(row[20]),
        source_display_copy=str(row[21]),
        source_visible=bool(row[22]),
        last_seen_at=str(row[23]),
        price_override=int(row[24]) if row[24] is not None else None,
        copy_override=str(row[25]) if row[25] is not None else None,
        visibility_override=bool(row[26]) if row[26] is not None else None,
        override_origin=str(row[27]),
        review_state=str(row[28]),
        last_verified_at=str(row[29]),
    )


def _admin_summary_from_row(row: tuple[object, ...]) -> ShowcaseAdminProductSummary:
    return ShowcaseAdminProductSummary(
        product=_product_from_row(row[:30]),
        has_body_image=bool(row[30]),
        has_sample_image=bool(row[31]),
        manual_price=bool(row[32]),
    )


def _section_from_row(row: tuple[object, ...]) -> ShowcaseSection:
    return ShowcaseSection(
        section_id=str(row[0]),
        title=str(row[1]),
        subtitle=str(row[2]),
        active=bool(row[3]),
        sort_order=int(row[4]),
        created_at=str(row[5]),
        updated_at=str(row[6]),
    )


def _section_item_from_row(row: tuple[object, ...]) -> ShowcaseSectionItem:
    return ShowcaseSectionItem(
        item_id=str(row[0]),
        section_id=str(row[1]),
        product_id=str(row[2]),
        sort_order=int(row[3]),
        recommend_note=str(row[4]),
        created_at=str(row[5]),
        updated_at=str(row[6]),
    )


def _gallery_album_from_row(row: tuple[object, ...]) -> ShowcaseGalleryAlbum:
    return ShowcaseGalleryAlbum(
        album_id=str(row[0]),
        title=str(row[1]),
        description=str(row[2]),
        sort_order=int(row[3]),
        is_visible=bool(row[4]),
        created_at=str(row[5]),
        updated_at=str(row[6]),
    )


def _gallery_image_from_row(row: tuple[object, ...]) -> ShowcaseGalleryImage:
    return ShowcaseGalleryImage(
        image_id=str(row[0]),
        album_id=str(row[1]),
        image_path=str(row[2]),
        caption=str(row[3]),
        sort_order=int(row[4]),
        is_visible=bool(row[5]),
        created_at=str(row[6]),
        updated_at=str(row[7]),
    )


def _purchase_step_from_row(row: tuple[object, ...]) -> ShowcasePurchaseStep:
    return ShowcasePurchaseStep(
        step_id=str(row[0]),
        title=str(row[1]),
        description=str(row[2]),
        sort_order=int(row[3]),
        is_visible=bool(row[4]),
        created_at=str(row[5]),
        updated_at=str(row[6]),
    )
