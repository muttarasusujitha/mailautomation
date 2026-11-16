import asyncio
import fitz
import pytest
from app.commercial_documents import render_pdf
from app.routes.pdf import generate_invoice, InvoiceRequest
from fastapi import HTTPException


@pytest.mark.parametrize('kind', ['invoice', 'po'])
def test_large_document_keeps_all_items_and_repeats_headers(kind):
    context = {'invoice_number': 'TEST-1', 'po_number': 'TEST-1', 'client_name': 'Test client', 'gst_rate': 0,
               'items': [{'description': f'Unique course {i}: ' + 'Practical training ' * 8,
                          'quantity': 1, 'rate': 100, 'amount': 1} for i in range(35)]}
    pdf = fitz.open(stream=render_pdf(context, kind), filetype='pdf')
    assert len(pdf) > 1
    content = '\n'.join(page.get_text() for page in pdf)
    for i in range(35):
        assert f'Unique course {i}:' in content
    assert '3,500.00' in content
    assert content.count('DESCRIPTION') >= 2
    assert all(f'Page {i+1}' in page.get_text() for i, page in enumerate(pdf))
    for page in pdf:
        assert all(block[0] >= 40 and block[2] <= page.rect.width - 40 for block in page.get_text('blocks'))


def test_invalid_invoice_is_rejected_before_rendering():
    with pytest.raises(HTTPException) as error:
        asyncio.run(generate_invoice(InvoiceRequest(items=[{'description': 'Training', 'quantity': 1, 'rate': -2}])))
    assert error.value.status_code == 422
