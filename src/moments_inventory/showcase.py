from __future__ import annotations

import re


_BRAND_ALIASES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("佳能", ("佳能", "canon")),
    ("索尼", ("索尼", "sony")),
    ("富士", ("富士", "fujifilm", "fuji")),
    ("奥林巴斯", ("奥林巴斯", "olympus")),
    ("柯达", ("柯达", "kodak")),
    ("尼康", ("尼康", "nikon")),
    ("卡西欧", ("卡西欧", "casio")),
    ("三星", ("三星", "samsung")),
    ("松下", ("松下", "panasonic")),
)


def normalize_showcase_model_key(value: str) -> str:
    compact = re.sub(r"[\s\-_]+", "", value.strip()).lower()
    for brand, aliases in _BRAND_ALIASES:
        for alias in aliases:
            alias_key = re.sub(r"[\s\-_]+", "", alias).lower()
            if compact.startswith(alias_key):
                return f"{brand}{compact[len(alias_key):]}"
    return compact
