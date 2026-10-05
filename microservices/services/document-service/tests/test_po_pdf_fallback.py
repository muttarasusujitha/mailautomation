import asyncio
import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

from app.routes import pdf


def test_po_route_supplies_structured_data_to_pdf_fallback(monkeypatch):
    renderer = AsyncMock(return_value=b"%PDF-test")
    monkeypatch.setattr(pdf, "_html_to_pdf", renderer)
    payload = pdf.PORequest(po_number="PO-TEST", vendor_name="Sample Trainer", total_amount=100)
    response = asyncio.run(pdf.generate_purchase_order(payload))
    assert response.body == b"%PDF-test"
    assert renderer.await_args.kwargs["purchase_order_context"]["vendor_name"] == "Sample Trainer"
    assert renderer.await_args.kwargs["purchase_order_context"]["total_amount"] == 100


def test_missing_html_renderer_uses_designed_po_renderer(monkeypatch):
    monkeypatch.setitem(sys.modules, "weasyprint", SimpleNamespace(HTML=Mock(side_effect=RuntimeError("Native library unavailable"))))
    fallback = Mock(return_value=b"%PDF-styled-purchase-order")
    monkeypatch.setattr(pdf, "_render_purchase_order_pdf_reportlab", fallback)
    context = {"po_number": "PO-TEST", "items": []}
    result = asyncio.run(pdf._html_to_pdf("<html></html>", purchase_order_context=context))
    assert result == b"%PDF-styled-purchase-order"
    fallback.assert_called_once_with(context)
