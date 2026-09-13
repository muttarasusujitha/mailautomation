import io

import openpyxl
import pytest

from app.routes.excel import _toc_to_excel


@pytest.mark.parametrize("mode", ["ai", "dataset"])
def test_export_contains_curriculum_without_schedule(mode):
    content = _toc_to_excel({
        "generation_mode": mode,
        "timing": "09:00 - 17:00",
        "days": [{
            "day": 1, "date": "2026-10-10", "focus_area": "Containers",
            "subtopics": ["Images", "Networking"],
            "learning_objectives": ["Build a container image"],
        }],
    })
    workbook = openpyxl.load_workbook(io.BytesIO(content))
    sheet = workbook.active
    assert sheet.max_column == 3
    assert [cell.value for cell in sheet[1]] == ["Topic", "Subtopics", "Learning Outcomes"]
    assert [cell.value for cell in sheet[2]] == [
        "Containers", "Images\nNetworking", "Build a container image",
    ]
    assert "09:00" not in str(list(sheet.values))
    assert "2026-10-10" not in str(list(sheet.values))
