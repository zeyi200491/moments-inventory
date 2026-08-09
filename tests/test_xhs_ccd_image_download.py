from pathlib import Path
import importlib.util
import sys

import openpyxl
import pytest


SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "download_xhs_ccd_images.py"
spec = importlib.util.spec_from_file_location("download_xhs_ccd_images", SCRIPT_PATH)
xhs = importlib.util.module_from_spec(spec)
assert spec.loader is not None
sys.modules[spec.name] = xhs
spec.loader.exec_module(xhs)


def make_workbook(path: Path, rows: list[list[str]]) -> Path:
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "CCD完整型号表"
    ws.append(["序号", "品牌", "统一物理机型/规范名", "产品类别", "系列", "欧亚/中国常见名", "传感器"])
    for row in rows:
        ws.append(row)
    wb.save(path)
    return path


def test_load_model_tasks_prefers_common_name_and_filters_ccd(tmp_path: Path):
    workbook = make_workbook(
        tmp_path / "canon.xlsx",
        [
            ["1", "Canon 佳能", "PowerShot A720 IS", "相机", "A", "佳能A720", "CCD"],
            ["2", "Canon 佳能", "PowerShot G7 X", "相机", "G", "佳能G7X", "CMOS"],
            ["3", "Canon 佳能", "PowerShot A570 IS", "相机", "A", "", "ccd"],
        ],
    )

    tasks = xhs.load_model_tasks(workbook)

    assert [task.model_name for task in tasks] == ["佳能A720", "PowerShot A570 IS"]
    assert [task.search_query for task in tasks] == ["佳能A720 出片图", "PowerShot A570 IS 出片图"]
    assert {task.brand_dir for task in tasks} == {"佳能"}


def test_load_model_tasks_deduplicates_by_brand_and_model(tmp_path: Path):
    workbook = make_workbook(
        tmp_path / "canon.xlsx",
        [
            ["1", "Canon 佳能", "PowerShot A720 IS", "相机", "A", "佳能A720", "CCD"],
            ["2", "Canon 佳能", "PowerShot A720 IS", "相机", "A", "佳能A720", "CCD"],
        ],
    )

    tasks = xhs.load_model_tasks(workbook)

    assert len(tasks) == 1
    assert tasks[0].model_name == "佳能A720"


def test_load_model_tasks_reports_missing_headers(tmp_path: Path):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["品牌", "传感器"])
    path = tmp_path / "bad.xlsx"
    wb.save(path)

    with pytest.raises(xhs.ExcelFormatError) as exc:
        xhs.load_model_tasks(path)

    assert "统一物理机型/规范名" in str(exc.value)
    assert "欧亚/中国常见名" in str(exc.value)


def test_load_model_tasks_closes_workbook_after_success(tmp_path: Path):
    workbook = make_workbook(
        tmp_path / "canon.xlsx",
        [
            ["1", "Canon 佳能", "PowerShot A720 IS", "相机", "A", "佳能A720", "CCD"],
        ],
    )

    xhs.load_model_tasks(workbook)

    workbook.unlink()
    assert not workbook.exists()


def test_load_model_tasks_reports_duplicate_headers(tmp_path: Path):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["品牌", "品牌", "统一物理机型/规范名", "欧亚/中国常见名", "传感器"])
    path = tmp_path / "duplicate.xlsx"
    wb.save(path)

    with pytest.raises(xhs.ExcelFormatError) as exc:
        xhs.load_model_tasks(path)

    assert "Excel 存在重复字段：品牌" in str(exc.value)


def test_safe_path_part_prefixes_windows_reserved_device_names():
    assert xhs.safe_path_part("CON") == "_CON"
    assert xhs.safe_path_part("NUL.txt") == "_NUL.txt"


def test_existing_image_numbers_count_only_target_jpgs(tmp_path: Path):
    for name in ["1.jpg", "2.jpeg", "03.JPG", "4.png", "note.jpg", "8.jpg", "0.jpeg"]:
        (tmp_path / name).write_bytes(b"image")

    assert xhs.existing_image_numbers(tmp_path) == {1, 2, 3}


def test_next_image_number_returns_none_when_full(tmp_path: Path):
    for number in range(1, xhs.TARGET_IMAGES_PER_MODEL + 1):
        (tmp_path / f"{number}.jpg").write_bytes(b"image")

    assert xhs.next_image_number(tmp_path) is None


def test_save_image_bytes_uses_next_available_number(tmp_path: Path):
    (tmp_path / "1.jpg").write_bytes(b"old")
    (tmp_path / "3.jpeg").write_bytes(b"old")

    saved_path = xhs.save_image_bytes(tmp_path, b"new image")

    assert saved_path == tmp_path / "2.jpg"
    assert saved_path.read_bytes() == b"new image"
