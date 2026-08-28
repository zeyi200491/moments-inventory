from __future__ import annotations

import json

import openpyxl
import pytest

from moments_inventory.model_catalog import (
    ModelCatalogError,
    build_model_catalog_index,
    load_model_catalog_index,
    normalize_model_key,
    save_model_catalog_index,
)


REQUIRED_HEADERS = [
    "序号",
    "品牌",
    "品牌英文名",
    "规范型号/物理机型",
    "传感器口径",
    "数据来源状态",
    "CCD补齐实际出现名称",
    "别名/简称/可能名称",
    "有歧义名称",
    "安全搜索匹配名称合集",
    "全部搜索匹配名称合集",
    "安全标准化匹配键",
    "备注",
]


def _write_catalog(path, rows):
    workbook = openpyxl.Workbook()
    try:
        sheet = workbook.active
        sheet.title = "完整型号主表"
        sheet.append(REQUIRED_HEADERS)
        for row in rows:
            sheet.append([row.get(header, "") for header in REQUIRED_HEADERS])
        workbook.save(path)
    finally:
        workbook.close()


def test_normalize_model_key_removes_case_spaces_and_punctuation():
    assert normalize_model_key("Canon IXUS-100 HS") == "canonixus100hs"
    assert normalize_model_key("佳能 ixus 100") == "佳能ixus100"


def test_build_model_catalog_index_reads_safe_all_and_ambiguous_aliases(tmp_path):
    catalog_path = tmp_path / "model_catalog.xlsx"
    _write_catalog(
        catalog_path,
        [
            {
                "序号": 1,
                "品牌": "佳能",
                "品牌英文名": "Canon",
                "规范型号/物理机型": "IXUS 100 IS",
                "传感器口径": "1/2.3",
                "数据来源状态": "已确认",
                "CCD补齐实际出现名称": "佳能 IXUS 100",
                "别名/简称/可能名称": "Canon IXUS 100; IXUS 100",
                "有歧义名称": "100",
                "安全搜索匹配名称合集": "佳能 IXUS 100; Canon IXUS 100; IXUS 100 IS",
                "全部搜索匹配名称合集": "佳能 IXUS 100; Canon IXUS 100; IXUS 100 IS; IXUS-100 IS; 100",
                "安全标准化匹配键": "佳能ixus100; canonixus100; ixus100is",
            },
            {
                "序号": 2,
                "品牌": "索尼",
                "品牌英文名": "Sony",
                "规范型号/物理机型": "DSC-WX300",
                "传感器口径": "1/2.3",
                "数据来源状态": "已确认",
                "CCD补齐实际出现名称": "索尼 WX300",
                "别名/简称/可能名称": "Sony WX300; Cyber-shot WX300",
                "有歧义名称": "",
                "安全搜索匹配名称合集": "索尼 WX300; Sony DSC-WX300; DSC-WX300",
                "全部搜索匹配名称合集": "索尼 WX300; Sony DSC-WX300; DSC-WX300; Cyber-shot WX300",
                "安全标准化匹配键": "索尼wx300; sonydscwx300; dscwx300",
            },
        ],
    )

    index = build_model_catalog_index(catalog_path)

    assert index.version == 1
    assert len(index.models) == 2
    assert index.models[0].brand == "佳能"
    assert index.models[0].canonical_model == "IXUS 100 IS"
    assert "佳能 IXUS 100" in index.models[0].safe_aliases
    assert "100" in index.models[0].ambiguous_aliases
    assert index.aliases_by_key["佳能ixus100"][0].canonical_model == "IXUS 100 IS"
    assert index.aliases_by_key["佳能ixus100"][0].safe is True
    assert index.aliases_by_key["ixus100is"][1].alias == "IXUS-100 IS"
    assert index.aliases_by_key["ixus100is"][1].safe is True
    assert index.aliases_by_key["100"][0].ambiguous is True
    assert "Cyber-shot WX300" in index.models[1].all_aliases
    assert index.aliases_by_key["cybershotwx300"][0].canonical_model == "DSC-WX300"
    assert index.aliases_by_key["cybershotwx300"][0].safe is False


def test_build_model_catalog_index_adds_safe_aliases_even_when_missing_from_all(tmp_path):
    workbook_path = tmp_path / "catalog.xlsx"
    _write_catalog(
        workbook_path,
        [
            {
                "品牌": "佳能",
                "品牌英文名": "Canon",
                "规范型号/物理机型": "IXUS 100 IS",
                "安全搜索匹配名称合集": "Canon IXUS-100；佳能IXUS100",
                "全部搜索匹配名称合集": "佳能IXUS100",
                "安全标准化匹配键": "canonixus100; 佳能ixus100",
            },
        ],
    )

    index = build_model_catalog_index(workbook_path)

    assert index.aliases_by_key["canonixus100"][0].canonical_model == "IXUS 100 IS"
    assert index.aliases_by_key["canonixus100"][0].safe is True


def test_save_and_load_model_catalog_index_round_trips(tmp_path):
    catalog_path = tmp_path / "model_catalog.xlsx"
    index_path = tmp_path / "model_catalog.json"
    _write_catalog(
        catalog_path,
        [
            {
                "序号": 1,
                "品牌": "卡西欧",
                "品牌英文名": "Casio",
                "规范型号/物理机型": "EX-ZS5",
                "传感器口径": "1/2.3",
                "数据来源状态": "已确认",
                "CCD补齐实际出现名称": "卡西欧 ZS5",
                "别名/简称/可能名称": "Casio ZS5",
                "有歧义名称": "",
                "安全搜索匹配名称合集": "卡西欧 ZS5; Casio ZS5; EX-ZS5",
                "全部搜索匹配名称合集": "卡西欧 ZS5; Casio ZS5; EX-ZS5",
                "安全标准化匹配键": "卡西欧zs5; casiozs5; exzs5",
            },
        ],
    )

    index = build_model_catalog_index(catalog_path)
    save_model_catalog_index(index, index_path)
    loaded_json = json.loads(index_path.read_text(encoding="utf-8"))
    loaded_index = load_model_catalog_index(index_path)

    assert loaded_json["version"] == 1
    assert loaded_index.models[0].brand == "卡西欧"
    assert loaded_index.models[0].safe_standard_keys == ["卡西欧zs5", "casiozs5", "exzs5"]
    assert loaded_index.aliases_by_key["casiozs5"][0].canonical_model == "EX-ZS5"


def test_load_model_catalog_index_ignores_unknown_fields_and_defaults_new_fields(tmp_path):
    index_path = tmp_path / "legacy_model_catalog.json"
    index_path.write_text(
        json.dumps(
            {
                "version": 1,
                "models": [
                    {
                        "brand": "卡西欧",
                        "brand_en": "Casio",
                        "canonical_model": "EX-ZS5",
                        "safe_aliases": ["Casio ZS5"],
                        "all_aliases": ["Casio ZS5"],
                        "ambiguous_aliases": [],
                        "safe_standard_key": "casiozs5",
                        "source_row": 2,
                        "future_field": "ignored",
                    }
                ],
                "aliases_by_key": {
                    "casiozs5": [
                        {
                            "alias": "Casio ZS5",
                            "normalized_key": "casiozs5",
                            "brand": "卡西欧",
                            "brand_en": "Casio",
                            "canonical_model": "EX-ZS5",
                            "safe": True,
                            "ambiguous": False,
                            "source_row": 2,
                            "future_field": "ignored",
                        }
                    ]
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    loaded_index = load_model_catalog_index(index_path)

    assert loaded_index.models[0].safe_standard_keys == ["casiozs5"]
    assert loaded_index.models[0].safe_standard_key == "casiozs5"
    assert loaded_index.aliases_by_key["casiozs5"][0].safe is True


def test_build_model_catalog_index_reports_missing_required_column(tmp_path):
    catalog_path = tmp_path / "broken_catalog.xlsx"
    workbook = openpyxl.Workbook()
    try:
        sheet = workbook.active
        sheet.title = "完整型号主表"
        sheet.append([header for header in REQUIRED_HEADERS if header != "安全搜索匹配名称合集"])
        workbook.save(catalog_path)
    finally:
        workbook.close()

    with pytest.raises(ModelCatalogError, match="缺少必需列"):
        build_model_catalog_index(catalog_path)
