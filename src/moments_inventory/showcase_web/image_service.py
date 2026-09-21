"""本地图片的按需缩略图缓存；原图永不覆盖。"""
from __future__ import annotations

import hashlib
import os
from pathlib import Path, PurePosixPath
from threading import Lock
from uuid import uuid4

from PIL import Image, ImageOps


class ImageVariantService:
    """只允许配置根目录内的图片，以及固定的 480/960 两种尺寸。"""

    def __init__(self, roots: dict[str, str | Path], cache_dir: str | Path):
        self.roots = {key.strip("/"): Path(value).resolve() for key, value in roots.items()}
        self.cache_dir = Path(cache_dir).resolve()
        self._locks = [Lock() for _ in range(32)]

    def get_variant(self, image_path: str, width: int) -> Path:
        if width not in {480, 960}:
            raise ValueError("图片尺寸仅支持480或960")
        path = str(image_path).replace("\\", "/")
        parts = PurePosixPath(path).parts
        if not path or path.startswith("/") or ":" in path or ".." in parts or "\x00" in path:
            raise ValueError("图片路径无效")
        source = None
        for prefix, root in sorted(self.roots.items(), key=lambda pair: -len(pair[0])):
            if path.startswith(prefix + "/"):
                candidate = (root / path[len(prefix) + 1:]).resolve()
                if not candidate.is_relative_to(root):
                    raise ValueError("图片路径超出允许目录")
                source = candidate
                break
        if source is None:
            raise ValueError("未配置该图片目录")
        if source.suffix.lower() not in {".jpg", ".jpeg", ".png", ".webp"}:
            raise ValueError("不支持的图片类型")
        stat = source.stat()
        fingerprint = hashlib.sha256(f"v1|{source}|{stat.st_mtime_ns}|{stat.st_size}|{width}".encode()).hexdigest()
        target = self.cache_dir / fingerprint[:2] / f"{fingerprint}.webp"
        with self._locks[int(fingerprint[:2], 16) % len(self._locks)]:
            if target.is_file():
                return target
            target.parent.mkdir(parents=True, exist_ok=True)
            temporary = target.with_name(f".{fingerprint}-{uuid4().hex}.tmp")
            try:
                with Image.open(source) as original:
                    if original.width * original.height > 40_000_000:
                        raise ValueError("图片像素过大")
                    image = ImageOps.exif_transpose(original)
                    image.thumbnail((width, image.height), Image.Resampling.LANCZOS)
                    if image.mode not in {"RGB", "RGBA"}:
                        image = image.convert("RGBA" if "transparency" in image.info else "RGB")
                    image.save(temporary, format="WEBP", quality=82, method=4)
                os.replace(temporary, target)
            finally:
                temporary.unlink(missing_ok=True)
        return target
