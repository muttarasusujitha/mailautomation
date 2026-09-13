import io

import openpyxl
import pytest

from app.routes.excel import _toc_to_excel


@pytest.mark.parametrize("mode", ["ai", "dataset"])
def test_export_contains_curriculum_and_schedule(mode):
    content = _toc_to_excel({
        "generation_mode": mode,
        "timing": "09:00 - 17:00",
        "days": [{
            "day": 1,
            "date": "2026-10-10",
            "focus_area": "Containers",
            "subtopics": ["Images", "Networking"],
            "learning_objectives": ["Build a container image"],
        }],
    })

    workbook = openpyxl.load_workbook(io.BytesIO(content))
    sheet = workbook.active

    assert sheet.max_column == 8

    values = [cell.value for cell in sheet[2]]

    assert "Containers" in values
    assert "Images\nNetworking" in values
    assert "Build a container image" in values
    assert "09:00 - 17:00" in values

    assert sheet.cell(2, 2).value.year == 2026
    assert sheet.freeze_panes == "A2"
