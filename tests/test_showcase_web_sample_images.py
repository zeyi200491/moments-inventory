from __future__ import annotations

from pathlib import Path

from moments_inventory.showcase_web.models import ShowcaseProduct
from moments_inventory.showcase_web.repository import SQLiteShowcaseRepository
from moments_inventory.showcase_web.sample_images import (
    build_model_alias_keys,
    build_model_key,
    build_sample_matching_summary,
    import_sample_images,
    list_sample_image_assets,
    list_sample_matching_groups,
)


def _product(product_id: str, brand: str, model: str) -> ShowcaseProduct:
    return ShowcaseProduct(
        product_id=product_id,
        model=model,
        brand=brand,
        cost_price=300,
        display_price=399,
        visible=True,
        sold=False,
        published_at="2026-08-10T10:00:00+08:00",
        raw_copy="原文",
        display_copy="展示文案",
        cover_image_path="",
        created_at="2026-08-10T10:01:00+08:00",
        updated_at="2026-08-10T10:01:00+08:00",
        last_seen_import_id="import-1",
    )


def test_import_sample_images_matches_model_folder_with_brand_aliases(tmp_path: Path) -> None:
    sample_root = tmp_path / "ccdcpt"
    model_dir = sample_root / "佳能" / "Canon 佳能DIGITAL IXUS 860 IS"
    model_dir.mkdir(parents=True)
    (model_dir / "01.jpg").write_bytes(b"sample-1")
    (model_dir / "02.jpg").write_bytes(b"sample-2")
    repo = SQLiteShowcaseRepository(tmp_path / "showcase.db")
    repo.upsert_product(_product("p1", "佳能", "佳能ixus860"))

    result = import_sample_images(sample_root, repo)

    images = repo.list_product_images("p1")
    assert result.matched_product_count == 1
    assert result.inserted_image_count == 2
    assert [image.image_type for image in images] == ["sample", "sample"]
    assert images[0].image_path == "sample-images/佳能/Canon 佳能DIGITAL IXUS 860 IS/01.jpg"


def test_import_sample_images_matches_new_brand_series_prefixes(tmp_path: Path) -> None:
    sample_root = tmp_path / "ccdcpt"
    fuji_dir = sample_root / "富士" / "富士FinePix A800"
    samsung_dir = sample_root / "三星" / "三星Digimax L60"
    fuji_dir.mkdir(parents=True)
    samsung_dir.mkdir(parents=True)
    (fuji_dir / "01.jpg").write_bytes(b"fuji")
    (samsung_dir / "01.jpg").write_bytes(b"samsung")
    repo = SQLiteShowcaseRepository(tmp_path / "showcase.db")
    repo.upsert_product(_product("fuji", "富士", "富士a800"))
    repo.upsert_product(_product("samsung", "三星", "三星l60"))

    result = import_sample_images(sample_root, repo)

    assert result.matched_product_count == 2
    assert repo.list_product_images("fuji")[0].image_path == "sample-images/富士/富士FinePix A800/01.jpg"
    assert repo.list_product_images("samsung")[0].image_path == "sample-images/三星/三星Digimax L60/01.jpg"


def test_import_sample_images_replaces_old_sample_images_only(tmp_path: Path) -> None:
    sample_root = tmp_path / "ccdcpt"
    model_dir = sample_root / "索尼" / "索尼DSC-T10"
    model_dir.mkdir(parents=True)
    (model_dir / "01.jpg").write_bytes(b"sample-1")
    repo = SQLiteShowcaseRepository(tmp_path / "showcase.db")
    repo.upsert_product(_product("p1", "索尼", "索尼t10"))
    repo.add_product_image("body", "p1", "storage/showcase_images/p1/body.jpg", "body", 0, True)
    repo.add_product_image("old", "p1", "sample-images/old.jpg", "sample", 10, False, source="auto_match")

    import_sample_images(sample_root, repo)

    images = repo.list_product_images("p1")
    assert [image.image_type for image in images] == ["body", "sample"]
    assert images[1].image_path == "sample-images/索尼/索尼DSC-T10/01.jpg"


def test_sample_image_hidden_override_survives_adding_another_image(tmp_path: Path) -> None:
    sample_root = tmp_path / "ccdcpt"
    model_dir = sample_root / "佳能" / "ixus 80"
    model_dir.mkdir(parents=True)
    (model_dir / "01.jpg").write_bytes(b"sample-1")
    repo = SQLiteShowcaseRepository(tmp_path / "showcase.db")
    repo.upsert_product(_product("p1", "佳能", "佳能ixus80"))

    import_sample_images(sample_root, repo)
    hidden = repo.list_product_images("p1")[0]
    assert repo.delete_product_image("p1", hidden.image_id)
    (model_dir / "02.jpg").write_bytes(b"sample-2")

    import_sample_images(sample_root, repo)

    images = repo.list_product_images("p1")
    assert [image.image_path for image in images] == [
        "sample-images/佳能/ixus 80/02.jpg",
    ]


def test_import_sample_images_uses_manual_product_folder_binding(tmp_path: Path) -> None:
    sample_root = tmp_path / "ccdcpt"
    model_dir = sample_root / "佳能" / "ixus 80"
    model_dir.mkdir(parents=True)
    (model_dir / "01.jpg").write_bytes(b"sample-1")
    repo = SQLiteShowcaseRepository(tmp_path / "showcase.db")
    repo.upsert_product(_product("p1", "佳能", "佳能ixus80ccd"))
    repo.save_sample_folder_binding(
        binding_key="product:p1",
        product_id="p1",
        model_key="",
        brand="佳能",
        folder_path="佳能/ixus 80",
        created_at="2026-08-15T10:00:00+08:00",
        updated_at="2026-08-15T10:00:00+08:00",
    )

    result = import_sample_images(sample_root, repo)

    assert result.matched_product_count == 1
    assert repo.list_product_images("p1")[0].image_path == "sample-images/佳能/ixus 80/01.jpg"


def test_model_key_maps_canon_cross_market_aliases() -> None:
    assert build_model_key("佳能", "佳能 IXY 910 IS") == build_model_key(
        "佳能",
        "Canon DIGITAL IXUS 860 IS",
    )


def test_model_alias_keys_expand_safe_series_prefixes_and_split_multi_model_names() -> None:
    assert "casio_z500" in build_model_alias_keys("卡西欧", "卡西欧EX-Z500")
    assert "panasonic_fx30" in build_model_alias_keys("松下", "松下DMC-FX30")
    assert "samsung_wb200f" in build_model_alias_keys("三星", "三星WB200 _ WB200F")
    assert "canon_ixus870" in build_model_alias_keys("佳能", "佳能ixus870/ixy920is")
    assert "canon_ixy920is" in build_model_alias_keys("佳能", "佳能ixus870/ixy920is")


def test_import_sample_images_uses_safe_alias_index_without_fuzzy_wrong_match(tmp_path: Path) -> None:
    sample_root = tmp_path / "ccdcpt"
    for folder in [
        sample_root / "卡西欧" / "卡西欧EX-Z500",
        sample_root / "松下" / "松下DMC-FX30",
        sample_root / "三星" / "三星WB200 _ WB200F",
        sample_root / "佳能" / "Canon 佳能DIGITAL IXUS 60",
    ]:
        folder.mkdir(parents=True)
        (folder / "01.jpg").write_bytes(folder.name.encode("utf-8"))
    repo = SQLiteShowcaseRepository(tmp_path / "showcase.db")
    repo.upsert_product(_product("casio", "卡西欧", "卡西欧z500"))
    repo.upsert_product(_product("panasonic", "松下", "松下fx30"))
    repo.upsert_product(_product("samsung", "三星", "三星wb200f"))
    repo.upsert_product(_product("canon", "佳能", "佳能ixus860"))

    result = import_sample_images(sample_root, repo)

    assert result.matched_product_count == 3
    assert repo.list_product_images("casio")[0].image_path == "sample-images/卡西欧/卡西欧EX-Z500/01.jpg"
    assert repo.list_product_images("panasonic")[0].image_path == "sample-images/松下/松下DMC-FX30/01.jpg"
    assert repo.list_product_images("samsung")[0].image_path == "sample-images/三星/三星WB200 _ WB200F/01.jpg"
    assert repo.list_product_images("canon") == []


def test_import_sample_images_matches_duplicate_inventory_suffix_folders(
    tmp_path: Path,
) -> None:
    sample_root = tmp_path / "ccdcpt"
    base_dir = sample_root / "索尼" / "索尼wx1"
    suffix_dir = sample_root / "索尼" / "索尼wx1-8518"
    base_dir.mkdir(parents=True)
    suffix_dir.mkdir(parents=True)
    (base_dir / "01.jpg").write_bytes(b"base")
    (suffix_dir / "01.jpg").write_bytes(b"suffix")
    repo = SQLiteShowcaseRepository(tmp_path / "showcase.db")
    repo.upsert_product(_product("base", "索尼", "索尼wx1"))
    repo.upsert_product(_product("suffix", "索尼", "索尼wx1-8518"))

    result = import_sample_images(sample_root, repo)

    assert result.matched_product_count == 2
    assert repo.list_product_images("base")[0].image_path == "sample-images/索尼/索尼wx1/01.jpg"
    assert repo.list_product_images("suffix")[0].image_path == "sample-images/索尼/索尼wx1-8518/01.jpg"


def test_import_sample_images_prefers_closest_equivalent_folder(
    tmp_path: Path,
) -> None:
    sample_root = tmp_path / "ccdcpt"
    official_dir = sample_root / "奥林巴斯" / "奥林巴斯FE-4020"
    compact_dir = sample_root / "奥林巴斯" / "奥林巴斯fe4020"
    official_dir.mkdir(parents=True)
    compact_dir.mkdir(parents=True)
    (official_dir / "01.jpg").write_bytes(b"official")
    (compact_dir / "01.jpg").write_bytes(b"compact")
    repo = SQLiteShowcaseRepository(tmp_path / "showcase.db")
    repo.upsert_product(_product("compact", "奥林巴斯", "奥林巴斯fe4020"))
    repo.upsert_product(_product("official", "奥林巴斯", "奥林巴斯fe-4020"))

    result = import_sample_images(sample_root, repo)

    assert result.matched_product_count == 2
    assert repo.list_product_images("compact")[0].image_path == "sample-images/奥林巴斯/奥林巴斯fe4020/01.jpg"
    assert repo.list_product_images("official")[0].image_path == "sample-images/奥林巴斯/奥林巴斯FE-4020/01.jpg"


def test_model_alias_keys_keep_real_four_digit_model_numbers() -> None:
    assert "olympus_fe5010" in build_model_alias_keys("奥林巴斯", "奥林巴斯fe-5010")
    assert "olympus_u7020" in build_model_alias_keys("奥林巴斯", "奥林巴斯u-7020")
    assert "casio_qv2300" in build_model_alias_keys("卡西欧", "卡西欧qv-2300")
    assert "premier_dm7362" in build_model_alias_keys("拍得丽", "拍得丽dm-7362")
    assert "sony_wx1" in build_model_alias_keys("索尼", "索尼wx1-8518")


def test_sample_matching_summary_reports_assets_and_missing_products(tmp_path: Path) -> None:
    sample_root = tmp_path / "ccdcpt"
    model_dir = sample_root / "佳能" / "Canon 佳能DIGITAL IXUS 860 IS"
    model_dir.mkdir(parents=True)
    (model_dir / "01.jpg").write_bytes(b"sample-1")
    repo = SQLiteShowcaseRepository(tmp_path / "showcase.db")
    repo.upsert_product(_product("canon", "佳能", "佳能 IXY 910 IS"))
    repo.upsert_product(_product("nikon", "尼康", "尼康 s01"))

    assets = list_sample_image_assets(sample_root)
    import_sample_images(sample_root, repo)
    summary = build_sample_matching_summary(sample_root, repo)

    assert assets[0].folder_path == "佳能/Canon 佳能DIGITAL IXUS 860 IS"
    assert summary.total_products == 2
    assert summary.asset_model_count == 1
    assert summary.matched_product_count == 1
    assert summary.missing_product_count == 1
    assert summary.coverage_rate == 50.0


def test_sample_matching_groups_reject_numeric_mismatch(tmp_path: Path) -> None:
    sample_root = tmp_path / "ccdcpt"
    model_dir = sample_root / "卡西欧" / "卡西欧EX-ZS15"
    model_dir.mkdir(parents=True)
    (model_dir / "01.jpg").write_bytes(b"sample-1")
    repo = SQLiteShowcaseRepository(tmp_path / "showcase.db")
    repo.upsert_product(_product("p1", "卡西欧", "卡西欧zs5"))

    groups = list_sample_matching_groups(sample_root, repo)

    assert groups == []


def test_sample_matching_groups_keep_sony_short_and_long_series_separate(tmp_path: Path) -> None:
    sample_root = tmp_path / "ccdcpt"
    for folder in [
        sample_root / "索尼" / "索尼DSC-W300",
        sample_root / "索尼" / "索尼DSC-T5",
        sample_root / "索尼" / "索尼DSC-H5",
    ]:
        folder.mkdir(parents=True)
        (folder / "01.jpg").write_bytes(folder.name.encode("utf-8"))
    repo = SQLiteShowcaseRepository(tmp_path / "showcase.db")
    repo.upsert_product(_product("wx", "索尼", "索尼wx300"))
    repo.upsert_product(_product("tx", "索尼", "索尼tx5"))
    repo.upsert_product(_product("hx", "索尼", "索尼hx5"))

    groups = list_sample_matching_groups(sample_root, repo)

    assert groups == []


def test_sample_matching_groups_keep_panasonic_fx_and_fs_separate(tmp_path: Path) -> None:
    sample_root = tmp_path / "ccdcpt"
    model_dir = sample_root / "松下" / "松下DMC-FS40"
    model_dir.mkdir(parents=True)
    (model_dir / "01.jpg").write_bytes(b"sample-1")
    repo = SQLiteShowcaseRepository(tmp_path / "showcase.db")
    repo.upsert_product(_product("p1", "松下", "松下fx40"))

    groups = list_sample_matching_groups(sample_root, repo)

    assert groups == []


def test_sample_matching_groups_skip_casio_zr_until_assets_are_ready(tmp_path: Path) -> None:
    sample_root = tmp_path / "ccdcpt"
    model_dir = sample_root / "卡西欧" / "卡西欧EX-Z70"
    model_dir.mkdir(parents=True)
    (model_dir / "01.jpg").write_bytes(b"sample-1")
    repo = SQLiteShowcaseRepository(tmp_path / "showcase.db")
    repo.upsert_product(_product("p1", "卡西欧", "卡西欧zr70"))

    groups = list_sample_matching_groups(sample_root, repo)

    assert groups == []


def test_import_sample_images_treats_canon_ixus_is_and_hs_as_same_model(tmp_path: Path) -> None:
    sample_root = tmp_path / "ccdcpt"
    model_dir = sample_root / "佳能" / "Canon 佳能IXUS 115 IS"
    model_dir.mkdir(parents=True)
    (model_dir / "01.jpg").write_bytes(b"sample-1")
    repo = SQLiteShowcaseRepository(tmp_path / "showcase.db")
    repo.upsert_product(_product("p1", "佳能", "佳能ixus115hs"))

    result = import_sample_images(sample_root, repo)

    assert result.matched_product_count == 1
    assert repo.list_product_images("p1")[0].image_path == "sample-images/佳能/Canon 佳能IXUS 115 IS/01.jpg"


def test_sample_matching_groups_reject_missing_numeric_side(tmp_path: Path) -> None:
    sample_root = tmp_path / "ccdcpt"
    model_dir = sample_root / "佳能" / "Canon 佳能DIGITAL IXUS"
    model_dir.mkdir(parents=True)
    (model_dir / "01.jpg").write_bytes(b"sample-1")
    repo = SQLiteShowcaseRepository(tmp_path / "showcase.db")
    repo.upsert_product(_product("p1", "佳能", "佳能ixus115"))

    groups = list_sample_matching_groups(sample_root, repo)

    assert groups == []


def test_import_sample_images_matches_brand_scoped_suffix_aliases(tmp_path: Path) -> None:
    sample_root = tmp_path / "ccdcpt"
    folders = {
        "fuji-z": sample_root / "富士" / "富士FinePix Z250fd",
        "fuji-j": sample_root / "富士" / "富士FinePix J15",
        "olympus-c": sample_root / "奥林巴斯" / "奥林巴斯C-760 UZ",
        "olympus-sp": sample_root / "奥林巴斯" / "奥林巴斯SP-565UZ",
        "sony-w": sample_root / "索尼" / "索尼DSC-W350",
        "nikon-s": sample_root / "尼康" / "尼康COOLPIX S7c",
        "sony-f": sample_root / "索尼" / "索尼DSC-F77",
        "casio-z": sample_root / "卡西欧" / "卡西欧EX-Z85",
    }
    for folder in folders.values():
        folder.mkdir(parents=True)
        (folder / "01.jpg").write_bytes(folder.name.encode("utf-8"))
    repo = SQLiteShowcaseRepository(tmp_path / "showcase.db")
    repo.upsert_product(_product("fuji-z", "富士", "富士z250"))
    repo.upsert_product(_product("fuji-j", "富士", "富士j15fd"))
    repo.upsert_product(_product("olympus-c", "奥林巴斯", "奥林巴斯c760"))
    repo.upsert_product(_product("olympus-sp", "奥林巴斯", "奥林巴斯sp565"))
    repo.upsert_product(_product("sony-w", "索尼", "索尼w350d"))
    repo.upsert_product(_product("nikon-s", "尼康", "尼康s7"))
    repo.upsert_product(_product("sony-f", "索尼", "索尼f77a"))
    repo.upsert_product(_product("casio-z", "卡西欧", "卡西欧z85a"))

    result = import_sample_images(sample_root, repo)

    assert result.matched_product_count == 8
    for product_id, folder in folders.items():
        assert repo.list_product_images(product_id)[0].image_path == f"sample-images/{folder.relative_to(sample_root).as_posix()}/01.jpg"


def test_sample_matching_groups_do_not_match_canon_g1x_to_powershot_g1(tmp_path: Path) -> None:
    sample_root = tmp_path / "ccdcpt"
    model_dir = sample_root / "佳能" / "Canon 佳能PowerShot G1"
    model_dir.mkdir(parents=True)
    (model_dir / "01.jpg").write_bytes(b"sample-1")
    repo = SQLiteShowcaseRepository(tmp_path / "showcase.db")
    repo.upsert_product(_product("p1", "佳能", "佳能g1x"))

    groups = list_sample_matching_groups(sample_root, repo)

    assert groups == []


def test_empty_sample_root_does_not_destroy_existing_images(tmp_path: Path) -> None:
    import pytest
    repo = SQLiteShowcaseRepository(tmp_path / "showcase.db")
    repo.upsert_product(_product("p1", "索尼", "索尼t10"))
    repo.add_product_image("old", "p1", "sample-images/old.jpg", "sample", 10, False, source="auto_match")
    empty = tmp_path / "empty"
    empty.mkdir()
    with pytest.raises(ValueError, match="样片"):
        import_sample_images(empty, repo)
    assert repo.list_product_images("p1")[0].image_id == "old"


def test_partial_rebuild_keeps_manual_and_unrelated_products(tmp_path: Path) -> None:
    root = tmp_path / "samples"
    model_dir = root / "索尼" / "索尼DSC-T10"
    model_dir.mkdir(parents=True)
    (model_dir / "1.jpg").write_bytes(b"sample")
    repo = SQLiteShowcaseRepository(tmp_path / "showcase.db")
    for pid in ["p1", "p2"]:
        repo.upsert_product(_product(pid, "索尼", "索尼t10"))
    repo.add_product_image("manual", "p1", "sample-images/manual.jpg", "sample", 1, False)
    repo.add_product_image("untouched", "p2", "sample-images/old.jpg", "sample", 1, False, source="auto_match")
    import_sample_images(root, repo, product_ids=["p1"])
    assert any(image.image_id == "manual" for image in repo.list_product_images("p1"))
    assert [image.image_id for image in repo.list_product_images("p2")] == ["untouched"]


def test_same_model_stores_one_shared_gallery(tmp_path: Path) -> None:
    import sqlite3
    root = tmp_path / "samples"
    model_dir = root / "索尼" / "索尼DSC-T10"
    model_dir.mkdir(parents=True)
    for index in range(8):
        (model_dir / f"{index}.jpg").write_bytes(b"sample")
    database = tmp_path / "showcase.db"
    repo = SQLiteShowcaseRepository(database)
    for index in range(30):
        repo.upsert_product(_product(f"p{index}", "索尼", "索尼t10"))
    import_sample_images(root, repo)
    with sqlite3.connect(database) as connection:
        assert connection.execute("select count(*) from showcase_sample_group_images").fetchone()[0] == 8
        assert connection.execute("select count(*) from showcase_product_sample_groups").fetchone()[0] == 30
        assert connection.execute("select count(*) from showcase_product_images where source='auto_match'").fetchone()[0] == 0
    assert len(repo.list_product_images("p29")) == 8


def test_unreadable_sample_root_preserves_images(tmp_path: Path, monkeypatch) -> None:
    import pytest
    import moments_inventory.showcase_web.sample_images as module
    root = tmp_path / "samples"
    root.mkdir()
    repo = SQLiteShowcaseRepository(tmp_path / "showcase.db")
    repo.upsert_product(_product("p1", "索尼", "索尼t10"))
    repo.add_product_image("old", "p1", "sample-images/old.jpg", "sample", 10, False, source="auto_match")
    def fail_scan(_root):
        raise PermissionError("拒绝访问")
    monkeypatch.setattr(module, "_scan_sample_image_groups", fail_scan)
    with pytest.raises(ValueError, match="不可读取"):
        import_sample_images(root, repo)
    assert repo.list_product_images("p1")[0].image_id == "old"
