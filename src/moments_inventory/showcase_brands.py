from __future__ import annotations

import re


KNOWN_SHOWCASE_BRANDS: tuple[str, ...] = (
    "爱国者",
    "奥林巴斯",
    "宾得",
    "方正",
    "富士",
    "惠普",
    "佳能",
    "卡西欧",
    "柯达",
    "理光",
    "联想",
    "美能达",
    "明基",
    "尼康",
    "拍得丽",
    "三星",
    "松下",
    "索尼",
    "徕卡",
    "通用",
)

BRAND_MODEL_ALIASES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("爱国者", ("爱国者", "aigo")),
    ("奥林巴斯", ("奥林巴斯", "olympus")),
    ("宾得", ("宾得", "pentax")),
    ("方正", ("方正", "founder")),
    ("富士", ("富士", "fujifilm", "fuji")),
    ("惠普", ("惠普", "hp", "hewlett packard", "hewlettpackard")),
    ("佳能", ("佳能", "canon")),
    ("卡西欧", ("卡西欧", "casio")),
    ("柯达", ("柯达", "kodak")),
    ("理光", ("理光", "ricoh")),
    ("联想", ("联想", "lenovo")),
    ("美能达", ("美能达", "minolta", "konica minolta", "konicaminolta")),
    ("明基", ("明基", "benq")),
    ("尼康", ("尼康", "nikon")),
    ("拍得丽", ("拍得丽", "premier")),
    ("三星", ("三星", "samsung")),
    ("松下", ("松下", "panasonic")),
    ("索尼", ("索尼", "sony")),
    ("徕卡", ("徕卡", "leica")),
)

BRAND_DETECTION_ALIASES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("佳能", ("ixus", "ixy", "powershot")),
    ("索尼", ("cyber shot", "cyber-shot", "cybershot", "dsc")),
    ("富士", ("finepix",)),
    ("尼康", ("coolpix",)),
    ("卡西欧", ("exilim",)),
    ("柯达", ("easyshare",)),
    ("理光", ("caplio",)),
    ("美能达", ("dimage",)),
    *BRAND_MODEL_ALIASES,
)


def normalize_showcase_model_key(value: str) -> str:
    compact = _compact(value)
    for brand, aliases in BRAND_MODEL_ALIASES:
        for alias in aliases:
            alias_key = _compact(alias)
            if compact.startswith(alias_key):
                remainder = compact[len(alias_key) :]
                if remainder.startswith(brand):
                    remainder = remainder[len(brand) :]
                return f"{brand}{remainder}"
    return compact


def derive_showcase_brand(*values: str) -> str:
    for value in values:
        brand = _brand_from_text(value)
        if brand:
            return brand
    return "通用"


def normalize_showcase_brand(raw_brand: str, *fallback_values: str) -> str:
    brand = _brand_from_text(raw_brand)
    if brand:
        return brand
    return derive_showcase_brand(*fallback_values)


def _brand_from_text(value: str) -> str:
    normalized = str(value or "").strip()
    if not normalized:
        return ""
    if normalized in KNOWN_SHOWCASE_BRANDS:
        return normalized
    compact = _compact(normalized)
    for brand, aliases in BRAND_DETECTION_ALIASES:
        if compact == _compact(brand):
            return brand
        for alias in aliases:
            alias_key = _compact(alias)
            if (
                compact == alias_key
                or compact.startswith(alias_key)
                or (_can_match_inside_text(alias_key) and alias_key in compact)
            ):
                return brand
    return ""


def _compact(value: str) -> str:
    return re.sub(r"[\s\-_]+", "", str(value or "").strip()).lower()


def _can_match_inside_text(alias_key: str) -> bool:
    return len(alias_key) >= 4 or any("\u4e00" <= character <= "\u9fff" for character in alias_key)
