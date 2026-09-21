from pathlib import Path

import pytest
from PIL import Image

from moments_inventory.showcase_web.image_service import ImageVariantService


def test_variant_is_cached_and_keeps_original(tmp_path: Path) -> None:
    root = tmp_path / "samples"
    root.mkdir()
    original = root / "a.jpg"
    Image.new("RGB", (1600, 1000), "pink").save(original)
    source_bytes = original.read_bytes()
    service = ImageVariantService({"sample-images": root}, tmp_path / "cache")
    result = service.get_variant("sample-images/a.jpg", 480)
    assert Image.open(result).size == (480, 300)
    before = result.stat().st_mtime_ns
    assert service.get_variant("sample-images/a.jpg", 480) == result
    assert result.stat().st_mtime_ns == before
    assert original.read_bytes() == source_bytes
    assert Image.open(service.get_variant("sample-images/a.jpg", 960)).size == (960, 600)


@pytest.mark.parametrize("path", ["sample-images/../private.jpg", "/private.jpg", "https://example.com/a.jpg", "sample-images/C:/a.jpg", "sample-images/..\\private.jpg"])
def test_variant_rejects_paths_outside_roots(tmp_path: Path, path: str) -> None:
    service = ImageVariantService({"sample-images": tmp_path / "samples"}, tmp_path / "cache")
    with pytest.raises(ValueError):
        service.get_variant(path, 480)


def test_invalid_width_is_rejected(tmp_path: Path) -> None:
    service = ImageVariantService({"sample-images": tmp_path}, tmp_path / "cache")
    with pytest.raises(ValueError):
        service.get_variant("sample-images/a.jpg", 10000)


def test_source_change_invalidates_cache(tmp_path: Path) -> None:
    original = tmp_path / "a.jpg"
    service = ImageVariantService({"sample-images": tmp_path}, tmp_path / "cache")
    Image.new("RGB", (800, 600), "red").save(original)
    old = service.get_variant("sample-images/a.jpg", 480)
    Image.new("RGB", (1200, 600), "blue").save(original)
    new = service.get_variant("sample-images/a.jpg", 480)
    assert new != old
    assert Image.open(new).size == (480, 240)
