from __future__ import annotations

from dataclasses import dataclass
from difflib import SequenceMatcher
import hashlib
from pathlib import Path
import re
from threading import RLock
import time
from typing import Callable, TypeVar

from moments_inventory.showcase_web.models import ShowcaseProduct
from moments_inventory.showcase_web.repository import SQLiteShowcaseRepository


SUPPORTED_SAMPLE_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp"}
_SAMPLE_ASSET_CACHE_LOCK = RLock()
_SAMPLE_ASSET_CACHE: dict[str, tuple[float, list["SampleImageAsset"], object]] = {}
_SAMPLE_ASSET_CACHE_TTL = 30.0

_BRAND_ALIASES: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    ("佳能", "canon", ("佳能", "canon")),
    ("索尼", "sony", ("索尼", "sony")),
    ("富士", "fuji", ("富士", "fujifilm", "fuji")),
    ("奥林巴斯", "olympus", ("奥林巴斯", "olympus")),
    ("柯达", "kodak", ("柯达", "kodak")),
    ("尼康", "nikon", ("尼康", "nikon")),
    ("卡西欧", "casio", ("卡西欧", "casio")),
    ("三星", "samsung", ("三星", "samsung")),
    ("松下", "panasonic", ("松下", "panasonic", "lumix")),
    ("宾得", "pentax", ("宾得", "pentax")),
    ("理光", "ricoh", ("理光", "ricoh")),
    ("美能达", "minolta", ("美能达", "minolta")),
    ("爱国者", "aigo", ("爱国者", "aigo")),
    ("明基", "benq", ("明基", "benq")),
    ("拍得丽", "premier", ("拍得丽", "premier")),
    ("三洋", "sanyo", ("三洋", "sanyo")),
)

_NOISE_TOKENS = (
    "出片图",
    "样片",
    "ccd",
    "数码相机",
    "相机",
    "digitalcamera",
    "digital",
    "powershot",
    "cyber-shot",
    "cybershot",
    "dsc",
    "dimage",
    "lumix",
    "finepix",
    "coolpix",
    "exilim",
    "optio",
    "easyshare",
    "photosmart",
    "digimax",
    "caplio",
    "ultra",
    "wide",
    "zoom",
)

_MODEL_ALIAS_KEYS = {
    "canon_ixy910is": "canon_ixus860is",
    "canon_ixus860is": "canon_ixus860is",
}

_MODEL_SPLIT_PATTERN = re.compile(r"[/／、]|(?:\s+[_＋+]\s+)|(?:\s+or\s+)", re.IGNORECASE)
_CandidateT = TypeVar("_CandidateT")


@dataclass(slots=True)
class SampleImageImportResult:
    available_model_count: int
    matched_product_count: int
    inserted_image_count: int
    unmatched_product_count: int


@dataclass(slots=True)
class SampleImageGroup:
    brand: str
    model_folder: str
    image_paths: list[Path]


@dataclass(frozen=True, slots=True)
class SampleImageAsset:
    brand: str
    model_folder: str
    folder_path: str
    model_key: str
    image_paths: list[str]

    @property
    def image_count(self) -> int:
        return len(self.image_paths)


@dataclass(frozen=True, slots=True)
class SampleMatchingSummary:
    total_products: int
    asset_model_count: int
    matched_product_count: int
    missing_product_count: int
    low_confidence_product_count: int
    coverage_rate: float


@dataclass(frozen=True, slots=True)
class SampleMatchingProduct:
    product_id: str
    model: str
    brand: str
    status: str
    confidence: int
    reason: str
    folder_path: str
    image_count: int


@dataclass(frozen=True, slots=True)
class SampleMatchingGroup:
    brand: str
    model: str
    status: str
    confidence: int
    reason: str
    folder_path: str
    image_count: int
    product_ids: list[str]

    @property
    def product_count(self) -> int:
        return len(self.product_ids)


@dataclass(frozen=True, slots=True)
class _IndexedSampleAsset:
    asset: SampleImageAsset
    alias_keys: frozenset[str]


@dataclass(frozen=True, slots=True)
class _SampleAssetIndex:
    exact_by_key: dict[str, SampleImageAsset]
    exact_candidates_by_key: dict[str, list[SampleImageAsset]]
    by_brand: dict[str, list[_IndexedSampleAsset]]
    indexed_assets: list[_IndexedSampleAsset]


def import_sample_images(
    sample_images_dir: str | Path,
    repository: SQLiteShowcaseRepository,
    *,
    max_images_per_product: int = 8,
    product_ids: list[str] | None = None,
) -> SampleImageImportResult:
    root = Path(sample_images_dir).resolve()
    if not root.is_dir():
        raise ValueError("样片根目录不存在或不可读取，已取消重建")
    if max_images_per_product < 1:
        raise ValueError("每组样片数量必须大于0")
    try:
        groups = _scan_sample_image_groups(root)
        for group in groups:
            for path in group.image_paths:
                with path.open("rb") as stream:
                    stream.read(1)
    except OSError as exc:
        raise ValueError("样片目录不可读取，已取消重建") from exc
    if not groups:
        raise ValueError("样片目录为空，已取消重建以保留已有绑定")
    groups_by_key = _groups_by_alias(groups)
    group_by_relative_path = {
        f"{group.brand}/{group.model_folder}".replace("\\", "/"): group
        for group in groups
    }
    manual_bindings = repository.list_sample_folder_bindings()

    group_images = {
        folder: [f"sample-images/{image.relative_to(root).as_posix()}" for image in group.image_paths[:max_images_per_product]]
        for folder, group in group_by_relative_path.items()
    }
    product_groups: dict[str, str] = {}
    targets = set(product_ids) if product_ids is not None else None
    matched_product_count = 0
    unmatched_product_count = 0
    exact_cache: dict[tuple[str, str], SampleImageGroup | None] = {}
    for product in repository.list_products(include_hidden=True):
        if targets is not None and product.product_id not in targets:
            continue
        group = _manual_group_for_product(
            product.product_id,
            product.brand,
            product.model,
            manual_bindings,
            group_by_relative_path,
        )
        if group is None:
            key = (product.brand, product.model)
            if key not in exact_cache:
                exact_cache[key] = _exact_group_for_product(product, groups_by_key)
            group = exact_cache[key]
        if group is None:
            unmatched_product_count += 1
            continue
        matched_product_count += 1
        product_groups[product.product_id] = f"{group.brand}/{group.model_folder}".replace("\\", "/")

    referenced_groups = {folder: group_images[folder] for folder in set(product_groups.values())}
    repository.replace_sample_group_links(referenced_groups, product_groups, product_ids=product_ids)
    return SampleImageImportResult(
        available_model_count=len(groups),
        matched_product_count=matched_product_count,
        inserted_image_count=sum(len(paths) for paths in referenced_groups.values()),
        unmatched_product_count=unmatched_product_count,
    )


def build_model_key(brand: str, model: str) -> str:
    brand_name, brand_key = _normalize_brand(f"{brand} {model}")
    normalized_model = _normalize_model_text(model)
    normalized_model = _strip_brand_aliases(normalized_model)
    for token in _NOISE_TOKENS:
        normalized_model = normalized_model.replace(_normalize_model_text(token), "")
    normalized_model = normalized_model.replace("μ", "u")
    normalized_model = normalized_model.replace("+", "plus")
    normalized_model = re.sub(r"[^a-z0-9]+", "", normalized_model)
    raw_key = f"{brand_key}_{normalized_model}" if normalized_model else brand_key
    return _MODEL_ALIAS_KEYS.get(raw_key, raw_key)


def build_model_alias_keys(brand: str, model: str) -> set[str]:
    aliases: set[str] = set()
    for part in _split_model_parts(model):
        aliases.update(_expand_model_key_aliases(build_model_key(brand, part)))
    return {alias for alias in aliases if alias}


def list_sample_image_assets(sample_images_dir: str | Path) -> list[SampleImageAsset]:
    root = Path(sample_images_dir).resolve()
    assets, _ = _sample_asset_snapshot(root)
    return list(assets)


def build_sample_matching_summary(
    sample_images_dir: str | Path,
    repository: SQLiteShowcaseRepository,
) -> SampleMatchingSummary:
    products = repository.list_products(include_hidden=True)
    assets, asset_index = _sample_asset_snapshot(Path(sample_images_dir).resolve())
    sample_paths = repository.list_first_image_paths_by_type("sample")
    matched_product_count = sum(1 for product in products if product.product_id in sample_paths)
    missing_products = [product for product in products if product.product_id not in sample_paths]
    candidate_cache: dict[tuple[str, str, str], tuple[SampleImageAsset, int, str, str] | None] = {}
    low_confidence_product_count = sum(
        1
        for product in missing_products
        if _cached_product_match(product, asset_index, candidate_cache, include_exact=False) is not None
    )
    total_products = len(products)
    return SampleMatchingSummary(
        total_products=total_products,
        asset_model_count=len(assets),
        matched_product_count=matched_product_count,
        missing_product_count=total_products - matched_product_count,
        low_confidence_product_count=low_confidence_product_count,
        coverage_rate=round((matched_product_count / total_products * 100), 1) if total_products else 0.0,
    )


def list_sample_matching_products(
    sample_images_dir: str | Path,
    repository: SQLiteShowcaseRepository,
    *,
    status: str = "needs_attention",
    limit: int = 100,
) -> list[SampleMatchingProduct]:
    products = repository.list_products(include_hidden=True)
    assets, asset_index = _sample_asset_snapshot(Path(sample_images_dir).resolve())
    sample_paths = repository.list_first_image_paths_by_type("sample")
    items: list[SampleMatchingProduct] = []
    candidate_cache: dict[tuple[str, str, str], tuple[SampleImageAsset, int, str, str] | None] = {}
    for product in products:
        has_sample = product.product_id in sample_paths
        candidate = None if has_sample else _cached_product_match(
            product,
            asset_index,
            candidate_cache,
            include_exact=True,
        )
        item_status = "matched" if has_sample else "missing"
        confidence = 100 if has_sample else 0
        reason = "商品已经有出片图" if has_sample else "未找到可自动绑定的图库"
        folder_path = ""
        image_count = 0
        if candidate is not None:
            asset, confidence, reason, item_status = candidate
            folder_path = asset.folder_path
            image_count = asset.image_count
        if status == "needs_attention" and item_status == "matched":
            continue
        if status not in {"all", "needs_attention"} and item_status != status:
            continue
        items.append(
            SampleMatchingProduct(
                product_id=product.product_id,
                model=product.model,
                brand=product.brand,
                status=item_status,
                confidence=confidence,
                reason=reason,
                folder_path=folder_path,
                image_count=image_count,
            )
        )
        if len(items) >= limit:
            break
    return items


def list_sample_matching_groups(
    sample_images_dir: str | Path,
    repository: SQLiteShowcaseRepository,
    *,
    limit: int = 100,
) -> list[SampleMatchingGroup]:
    products = repository.list_products(include_hidden=True)
    assets, asset_index = _sample_asset_snapshot(Path(sample_images_dir).resolve())
    sample_paths = repository.list_first_image_paths_by_type("sample")
    grouped: dict[tuple[str, str, str], SampleMatchingGroup] = {}
    candidate_cache: dict[tuple[str, str, str], tuple[SampleImageAsset, int, str, str] | None] = {}
    for product in products:
        if product.product_id in sample_paths:
            continue
        candidate = _cached_product_match(product, asset_index, candidate_cache, include_exact=True)
        if candidate is None:
            continue
        asset, confidence, reason, status = candidate
        key = (product.brand, product.model, asset.folder_path)
        existing = grouped.get(key)
        if existing is None:
            grouped[key] = SampleMatchingGroup(
                brand=product.brand,
                model=product.model,
                status=status,
                confidence=confidence,
                reason=reason,
                folder_path=asset.folder_path,
                image_count=asset.image_count,
                product_ids=[product.product_id],
            )
            continue
        existing.product_ids.append(product.product_id)
    return sorted(
        grouped.values(),
        key=lambda item: (-item.product_count, item.status != "auto_matched", -item.confidence, item.brand, item.model),
    )[:limit]


def _scan_sample_image_groups(root: Path) -> list[SampleImageGroup]:
    if not root.exists():
        return []
    root = root.resolve()
    groups: list[SampleImageGroup] = []
    for brand_dir in sorted((path for path in root.iterdir() if path.is_dir()), key=lambda path: path.name):
        if not brand_dir.resolve().is_relative_to(root):
            raise ValueError("样片目录超出允许根目录")
        for model_dir in sorted((path for path in brand_dir.iterdir() if path.is_dir()), key=lambda path: path.name):
            if not model_dir.resolve().is_relative_to(root):
                raise ValueError("样片目录超出允许根目录")
            image_paths = sorted(
                (
                    path
                    for path in model_dir.iterdir()
                    if path.is_file() and path.suffix.lower() in SUPPORTED_SAMPLE_SUFFIXES
                ),
                key=lambda path: path.name,
            )
            if any(not path.resolve().is_relative_to(root) for path in image_paths):
                raise ValueError("样片文件超出允许根目录")
            if image_paths:
                groups.append(
                    SampleImageGroup(
                        brand=brand_dir.name,
                        model_folder=model_dir.name,
                        image_paths=image_paths,
                    )
                )
    return groups


def _folder_aliases(brand: str, model_folder: str) -> set[str]:
    return build_model_alias_keys(brand, model_folder)


def _normalize_model(value: str) -> str:
    text = value.lower()
    replacements = [
        "canon",
        "佳能",
        "sony",
        "索尼",
        "olympus",
        "奥林巴斯",
        "fujifilm",
        "fuji",
        "富士",
        "samsung",
        "三星",
        "nikon",
        "尼康",
        "panasonic",
        "lumix",
        "松下",
        "casio",
        "exilim",
        "卡西欧",
        "kodak",
        "柯达",
        "ricoh",
        "理光",
        "pentax",
        "宾得",
        "benq",
        "明基",
        "sanyo",
        "三洋",
        "aigo",
        "爱国者",
        "finepix",
        "digimax",
        "coolpix",
        "easyshare",
        "optio",
        "caplio",
        "dimage",
        "cybershot",
        "digital",
        "powershot",
        "cyber-shot",
        "dsc",
        "ultra",
        "wide",
        "zoom",
    ]
    for word in replacements:
        text = text.replace(word, "")
    return re.sub(r"[^0-9a-z\u4e00-\u9fff]+", "", text)


def _manual_group_for_product(
    product_id: str,
    brand: str,
    model: str,
    manual_bindings: dict[str, str],
    group_by_relative_path: dict[str, SampleImageGroup],
) -> SampleImageGroup | None:
    keys = [
        f"product:{product_id}",
        f"model:{brand}:{_normalize_model(model)}",
    ]
    for key in keys:
        folder_path = manual_bindings.get(key)
        if not folder_path:
            continue
        normalized_path = folder_path.replace("\\", "/").strip("/")
        group = group_by_relative_path.get(normalized_path)
        if group is not None:
            return group
    return None


def _match_product_to_assets(
    product: ShowcaseProduct,
    asset_index: _SampleAssetIndex,
    *,
    include_exact: bool,
) -> tuple[SampleImageAsset, int, str, str] | None:
    product_keys = build_model_alias_keys(product.brand, product.model)
    exact = _exact_asset_for_product(product, asset_index.exact_candidates_by_key)
    if exact is not None:
        if not include_exact:
            return None
        return exact, 100, "型号 key 完全匹配或命中跨市场别名", "auto_matched"

    product_brand, _ = _normalize_brand(product.brand)
    candidates = asset_index.by_brand.get(product_brand) or asset_index.indexed_assets
    best_asset: SampleImageAsset | None = None
    best_score = 0
    product_candidates = product_keys or {build_model_key(product.brand, product.model)}
    for indexed_asset in candidates:
        for product_key in product_candidates:
            for asset_key in indexed_asset.alias_keys:
                if not _is_fuzzy_candidate_allowed(product_key, asset_key):
                    continue
                score = int(SequenceMatcher(None, product_key, asset_key).ratio() * 100)
                if score > best_score:
                    best_score = score
                    best_asset = indexed_asset.asset
    if best_asset is None or best_score < 72:
        return None
    return best_asset, best_score, f"同品牌型号相似度 {best_score}%，需人工确认", "low_confidence"


def _cached_product_match(
    product: ShowcaseProduct,
    asset_index: _SampleAssetIndex,
    cache: dict[tuple[str, str, str], tuple[SampleImageAsset, int, str, str] | None],
    *,
    include_exact: bool,
) -> tuple[SampleImageAsset, int, str, str] | None:
    key = (product.brand, product.model, "exact" if include_exact else "fuzzy")
    if key not in cache:
        cache[key] = _match_product_to_assets(product, asset_index, include_exact=include_exact)
    return cache[key]


def _build_asset_index(assets: list[SampleImageAsset]) -> _SampleAssetIndex:
    alias_map: dict[str, list[SampleImageAsset]] = {}
    by_brand: dict[str, list[_IndexedSampleAsset]] = {}
    indexed_assets: list[_IndexedSampleAsset] = []
    for asset in assets:
        alias_keys = frozenset(build_model_alias_keys(asset.brand, asset.model_folder) or {asset.model_key})
        indexed_asset = _IndexedSampleAsset(asset=asset, alias_keys=alias_keys)
        indexed_assets.append(indexed_asset)
        by_brand.setdefault(asset.brand, []).append(indexed_asset)
        for alias in alias_keys:
            alias_map.setdefault(alias, []).append(asset)
    exact_by_key = {
        alias: alias_assets[0]
        for alias, alias_assets in alias_map.items()
        if len(alias_assets) == 1
    }
    return _SampleAssetIndex(
        exact_by_key=exact_by_key,
        exact_candidates_by_key=alias_map,
        by_brand=by_brand,
        indexed_assets=indexed_assets,
    )


def _sample_asset_snapshot(root: Path) -> tuple[list[SampleImageAsset], _SampleAssetIndex]:
    """短时复用目录扫描和匹配索引，避免管理页并发重复遍历上万文件。"""
    key = str(root.resolve())
    now = time.monotonic()
    with _SAMPLE_ASSET_CACHE_LOCK:
        cached = _SAMPLE_ASSET_CACHE.get(key)
        if cached is not None and now - cached[0] < _SAMPLE_ASSET_CACHE_TTL:
            return cached[1], cached[2]  # type: ignore[return-value]
        assets: list[SampleImageAsset] = []
        for group in _scan_sample_image_groups(root):
            folder_path = f"{group.brand}/{group.model_folder}".replace("\\", "/")
            brand_name, _ = _normalize_brand(group.brand)
            assets.append(
                SampleImageAsset(
                    brand=brand_name,
                    model_folder=group.model_folder,
                    folder_path=folder_path,
                    model_key=build_model_key(group.brand, group.model_folder),
                    image_paths=[path.relative_to(root).as_posix() for path in group.image_paths],
                )
            )
        index = _build_asset_index(assets)
        _SAMPLE_ASSET_CACHE[key] = (now, assets, index)
        return assets, index


def _groups_by_alias(groups: list[SampleImageGroup]) -> dict[str, list[SampleImageGroup]]:
    alias_groups: dict[str, list[SampleImageGroup]] = {}
    seen: set[tuple[str, str]] = set()
    for group in groups:
        for alias in _folder_aliases(group.brand, group.model_folder):
            folder_path = f"{group.brand}/{group.model_folder}".replace("\\", "/")
            key = (alias, folder_path)
            if key in seen:
                continue
            seen.add(key)
            alias_groups.setdefault(alias, []).append(group)
    return alias_groups


def _group_by_safe_alias(groups: list[SampleImageGroup]) -> dict[str, SampleImageGroup]:
    alias_groups = _groups_by_alias(groups)
    group_by_folder_path = {
        f"{group.brand}/{group.model_folder}".replace("\\", "/"): group
        for group in groups
    }
    return {
        alias: group_by_folder_path[f"{groups_for_alias[0].brand}/{groups_for_alias[0].model_folder}".replace("\\", "/")]
        for alias, groups_for_alias in alias_groups.items()
        if len(groups_for_alias) == 1
    }


def _exact_group_for_product(
    product: ShowcaseProduct,
    groups_by_key: dict[str, list[SampleImageGroup]],
) -> SampleImageGroup | None:
    for alias in build_model_alias_keys(product.brand, product.model):
        candidates = groups_by_key.get(alias, [])
        selected = _select_model_candidate(
            product.model,
            candidates,
            lambda group: group.model_folder,
        )
        if selected is not None:
            return selected
    return None


def _exact_asset_for_product(
    product: ShowcaseProduct,
    assets_by_key: dict[str, list[SampleImageAsset]],
) -> SampleImageAsset | None:
    for alias in build_model_alias_keys(product.brand, product.model):
        candidates = assets_by_key.get(alias, [])
        selected = _select_model_candidate(
            product.model,
            candidates,
            lambda asset: asset.model_folder,
        )
        if selected is not None:
            return selected
    return None


def _select_model_candidate(
    product_model: str,
    candidates: list[_CandidateT],
    model_getter: Callable[[_CandidateT], str],
) -> _CandidateT | None:
    if len(candidates) == 1:
        return candidates[0]

    raw_product = _compact_raw_model_text(product_model)
    raw_matches = [
        candidate
        for candidate in candidates
        if raw_product and _compact_raw_model_text(model_getter(candidate)) == raw_product
    ]
    if len(raw_matches) == 1:
        return raw_matches[0]
    selected = _select_closest_text_candidate(product_model, raw_matches, model_getter)
    if selected is not None:
        return selected

    normalized_product = _normalize_model(product_model)
    normalized_matches = [
        candidate
        for candidate in candidates
        if normalized_product and _normalize_model(model_getter(candidate)) == normalized_product
    ]
    if len(normalized_matches) == 1:
        return normalized_matches[0]
    selected = _select_closest_text_candidate(product_model, normalized_matches, model_getter)
    if selected is not None:
        return selected

    stripped_product = _normalize_model(_strip_inventory_suffix(product_model))
    stripped_matches = [
        candidate
        for candidate in candidates
        if stripped_product and _normalize_model(_strip_inventory_suffix(model_getter(candidate))) == stripped_product
    ]
    if len(stripped_matches) == 1:
        return stripped_matches[0]
    selected = _select_closest_text_candidate(product_model, stripped_matches, model_getter)
    if selected is not None:
        return selected

    return None


def _split_model_parts(model: str) -> list[str]:
    cleaned = _strip_inventory_suffix(model.strip())
    parts = [part.strip() for part in _MODEL_SPLIT_PATTERN.split(cleaned) if part.strip()]
    return parts or [cleaned]


def _strip_inventory_suffix(model: str) -> str:
    match = re.search(r"^(?P<head>.+)[-_][0-9]{4,6}$", model)
    if match is None:
        return model
    head = match.group("head")
    if re.search(r"[0-9]", _normalize_model_text(head)):
        return head
    return model


def _compact_raw_model_text(value: str) -> str:
    text = value.casefold().replace("μ", "u")
    return re.sub(r"[^0-9a-z\u4e00-\u9fff]+", "", text)


def _select_closest_text_candidate(
    product_model: str,
    candidates: list[_CandidateT],
    model_getter: Callable[[_CandidateT], str],
) -> _CandidateT | None:
    if len(candidates) <= 1:
        return candidates[0] if candidates else None
    product_text = product_model.casefold().strip()
    ranked = sorted(
        (
            (
                int(SequenceMatcher(None, product_text, model_getter(candidate).casefold().strip()).ratio() * 1000),
                -abs(len(model_getter(candidate)) - len(product_model)),
                candidate,
            )
            for candidate in candidates
        ),
        key=lambda item: (item[0], item[1]),
        reverse=True,
    )
    if len(ranked) >= 2 and ranked[0][:2] == ranked[1][:2]:
        return None
    return ranked[0][2]


def _is_fuzzy_candidate_allowed(product_key: str, asset_key: str) -> bool:
    product_brand, product_code = _split_model_key(product_key)
    asset_brand, asset_code = _split_model_key(asset_key)
    if product_brand != asset_brand:
        return False

    product_numbers = _model_number_tokens(product_code)
    asset_numbers = _model_number_tokens(asset_code)
    if not product_numbers or not asset_numbers or product_numbers != asset_numbers:
        return False

    product_series = _model_series_prefix(product_code)
    asset_series = _model_series_prefix(asset_code)
    if product_series != asset_series:
        return False
    if _model_letter_suffix(product_code) != _model_letter_suffix(asset_code):
        return False

    if product_brand == "sony" and (product_series in {"wx", "tx", "hx"} or asset_series in {"wx", "tx", "hx"}):
        return False
    if product_brand == "casio" and (product_series == "zr" or asset_series == "zr"):
        return False
    return True


def _split_model_key(model_key: str) -> tuple[str, str]:
    if "_" not in model_key:
        return "", model_key
    return model_key.split("_", 1)


def _model_number_tokens(model_code: str) -> tuple[str, ...]:
    return tuple(re.findall(r"[0-9]+", model_code))


def _model_series_prefix(model_code: str) -> str:
    match = re.match(r"[a-z]+", model_code)
    return match.group(0) if match else ""


def _model_letter_suffix(model_code: str) -> str:
    match = re.fullmatch(r"[a-z]+[0-9]+([a-z]+)", model_code)
    return match.group(1) if match else ""


def _expand_model_key_aliases(model_key: str) -> set[str]:
    if "_" not in model_key:
        return {model_key}
    brand_key, model_code = model_key.split("_", 1)
    aliases = {model_key}

    def add_alias(code: str) -> None:
        if len(code) >= 2:
            aliases.add(f"{brand_key}_{code}")

    for suffix in ("is", "hs"):
        if model_code.endswith(suffix) and len(model_code) > len(suffix) + 1:
            add_alias(model_code[: -len(suffix)])
    if model_code.endswith("zoom"):
        add_alias(model_code[:-4])
    if brand_key == "casio":
        for prefix in ("exzr", "exzs", "exz", "exh", "exs", "exv", "exfc", "exfr", "extr", "exp", "exg", "exm"):
            if model_code.startswith(prefix):
                add_alias(model_code[2:])
                break
        if re.fullmatch(r"z[0-9]+a", model_code):
            add_alias(model_code[:-1])
    if brand_key == "fuji" and re.fullmatch(r"[a-z]+[0-9]+fd", model_code):
        add_alias(model_code[:-2])
    if brand_key == "nikon" and re.fullmatch(r"s[0-9]+c", model_code):
        add_alias(model_code[:-1])
    if brand_key == "olympus" and re.fullmatch(r"(?:c|sp)[0-9]+uz", model_code):
        add_alias(model_code[:-2])
    if brand_key == "sony":
        if re.fullmatch(r"w[0-9]+d", model_code):
            add_alias(model_code[:-1])
        if re.fullmatch(r"f[0-9]+a", model_code):
            add_alias(model_code[:-1])
    if brand_key == "panasonic" and model_code.startswith("dmc"):
        add_alias(model_code[3:])
    if brand_key == "nikon" and re.fullmatch(r"e[0-9]{3,4}", model_code):
        add_alias(model_code[1:])
    return aliases


def _normalize_brand(text: str) -> tuple[str, str]:
    lowered = text.casefold()
    for brand_name, brand_key, aliases in _BRAND_ALIASES:
        if any(alias.casefold() in lowered for alias in aliases):
            return brand_name, brand_key
    chinese = "".join(re.findall(r"[\u4e00-\u9fff]+", text))
    fallback = chinese or text.strip() or "unknown"
    return fallback, _normalize_model_text(fallback) or "unknown"


def _normalize_model_text(value: str) -> str:
    return value.casefold().replace("-", "").replace("_", "").replace(" ", "")


def _strip_brand_aliases(value: str) -> str:
    result = value
    for _, _, aliases in _BRAND_ALIASES:
        for alias in aliases:
            result = result.replace(_normalize_model_text(alias), "")
    return result


def _stable_sample_image_id(product_id: str, web_path: str) -> str:
    digest = hashlib.sha1(f"{product_id}|{web_path}".encode("utf-8")).hexdigest()
    return f"sample-{digest}"
