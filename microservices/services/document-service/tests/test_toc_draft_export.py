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
    with pytest.raises(HTTPException) as error:
        asyncio.run(export_toc_workbook({"toc": toc}))
    assert error.value.status_code == 422


def test_draft_does_not_allow_empty_curriculum():
    with pytest.raises(HTTPException):
        asyncio.run(export_toc_workbook({"toc": {"days": []}, "draft": True}))
