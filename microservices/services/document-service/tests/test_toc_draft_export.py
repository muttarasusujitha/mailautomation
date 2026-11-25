import asyncio
import io

import openpyxl
import pytest
from fastapi import HTTPException
from app.routes.excel import export_toc_workbook


def test_draft_is_downloadable_and_labelled_without_changing_delivery_status():
    toc = {"title": "Review example", "quality": {"status": "requires_review", "review_warnings": ["Confirm lab feasibility"]},
           "days": [{"day": 1, "focus_area": "Python", "minutes": 60}]}
    response = asyncio.run(export_toc_workbook({"toc": toc, "draft": True}))
    wb = openpyxl.load_workbook(io.BytesIO(response.body))
    assert wb["Program Overview"]["B2"].value.startswith("DRAFT - FOR REVIEW")
    assert "Confirm lab feasibility" in str(list(wb["Readiness & Risks"].values))
    assert "DRAFT_" in response.headers["content-disposition"]
    assert toc["quality"]["status"] == "requires_review"
    delivery_response = asyncio.run(export_toc_workbook({"toc": toc}))
    delivery_wb = openpyxl.load_workbook(io.BytesIO(delivery_response.body))
    delivery_values = [
        cell.value
        for sheet in delivery_wb.worksheets
        for row in sheet.iter_rows()
        for cell in row
    ]
    assert delivery_response.status_code == 200
    assert not any("DRAFT" in str(value).upper() for value in delivery_values if value is not None)
    assert "DRAFT_" not in delivery_response.headers["content-disposition"]


def test_draft_does_not_allow_empty_curriculum():
    with pytest.raises(HTTPException):
        asyncio.run(export_toc_workbook({"toc": {"days": []}, "draft": True}))


def test_automatically_reviewed_toc_is_exportable():
    toc = {
        "title": "Automatically reviewed",
        "quality": {
            "status": "requires_review",
            "automatic_review": True,
            "content_evaluation": {"status": "pass", "score": 90},
        },
        "days": [{"day": 1, "focus_area": "Python", "minutes": 60}],
    }
    response = asyncio.run(export_toc_workbook({"toc": toc}))
    assert response.status_code == 200
