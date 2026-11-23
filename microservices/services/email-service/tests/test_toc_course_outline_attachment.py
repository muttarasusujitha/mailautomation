"""Client ToC mail carries the Excel workbook and, when it renders, the PDF course outline."""
import asyncio
import base64
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from app.routes import inbox


class _Response:
    def __init__(self, status_code=200, content=b"", payload=None):
        self.status_code, self.content, self._payload = status_code, content, payload or {}

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


def _fake_post(pdf_response):
    calls = []

    async def post(client, url, **kwargs):
        calls.append(url)
        if url.endswith("/toc/generate"):
            return _Response(payload={"toc_data": {"title": "DevOps", "days": [{"day": 1}]}})
        if url.endswith("/documents/excel/toc"):
            return _Response(content=b"PK-workbook")
        if url.endswith("/toc/generate-pdf"):
            if isinstance(pdf_response, Exception):
                raise pdf_response
            return pdf_response
        raise AssertionError(url)
    return post, calls


class _Client:
    def __init__(self, **kwargs):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False


def _build(monkeypatch, pdf_response):
    post, calls = _fake_post(pdf_response)
    monkeypatch.setattr(inbox, "_post_with_local_fallback", post)
    monkeypatch.setattr(inbox.httpx, "AsyncClient", _Client)
    files = asyncio.run(inbox._create_standalone_toc_attachments(technology="DevOps", duration_days=5))
    return files, calls


def test_workbook_and_course_outline_pdf_are_attached(monkeypatch):
    files, calls = _build(monkeypatch, _Response(content=b"%PDF-1.7 outline"))
    assert [item["filename"] for item in files] == ["DevOps - Training ToC.xlsx", "DevOps - Course Outline.pdf"]
    assert files[1]["subtype"] == "pdf"
    assert base64.b64decode(files[1]["content_base64"]).startswith(b"%PDF")
    assert calls[-1].endswith("/toc/generate-pdf")


def test_pdf_failure_or_non_pdf_output_keeps_the_workbook(monkeypatch):
    for response in (_Response(status_code=422), _Response(content=b"not a pdf"), RuntimeError("renderer down")):
        files, _ = _build(monkeypatch, response)
        assert [item["filename"] for item in files] == ["DevOps - Training ToC.xlsx"]


def test_no_attachments_without_technology_or_duration(monkeypatch):
    post, calls = _fake_post(_Response(content=b"%PDF"))
    monkeypatch.setattr(inbox, "_post_with_local_fallback", post)
    assert asyncio.run(inbox._create_standalone_toc_attachments(technology="", duration_days=5)) == []
    assert asyncio.run(inbox._create_standalone_toc_attachments(technology="DevOps", duration_days=0)) == []
    assert calls == []


def test_combined_reply_renders_the_existing_agenda(monkeypatch):
    agenda = {"days": [{"day": 1, "focus_area": "Shell scripting"}]}
    calls = []

    async def post(client, url, *, json):
        assert json["toc"] == agenda
        calls.append(url)
        return _Response(content=b"%PDF-outline" if url.endswith("generate-pdf") else b"workbook")

    monkeypatch.setattr(inbox, "_post_with_local_fallback", post)
    monkeypatch.setattr(inbox.httpx, "AsyncClient", _Client)
    files = asyncio.run(inbox._create_standalone_toc_attachments(
        technology="DevOps", duration_days=1, toc_data=agenda))
    assert len(files) == len(calls) == 2
