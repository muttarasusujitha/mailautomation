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
    assert content.count('ITEM') >= 2
    assert all(f'Page {i+1}' in page.get_text() for i, page in enumerate(pdf))
    for page in pdf:
        assert all(block[0] >= 40 and block[2] <= page.rect.width - 40 for block in page.get_text('blocks'))


def test_invalid_invoice_is_rejected_before_rendering():
    with pytest.raises(HTTPException) as error:
        asyncio.run(generate_invoice(InvoiceRequest(items=[{'description': 'Training', 'quantity': 1, 'rate': -2}])))
    assert error.value.status_code == 422


def test_beulix_is_the_default_issuer_for_po_and_tax_invoice_templates():
    po = fitz.open(stream=render_pdf({
        'po_number': 'TPO-100', 'date': '01-09-2026', 'vendor_name': 'Murali Mohan',
        'vendor_email': 'trainer@example.com', 'vendor_gst': '29TRAINER1Z5',
        'client_name': 'Tata Elxsi', 'training_domain': 'AWS Cloud Practitioner',
        'items': [{'description': 'AWS Cloud Practitioner training', 'quantity': 1, 'rate': 15000}],
    }, 'po'), filetype='pdf')
    invoice = fitz.open(stream=render_pdf({
        'invoice_number': 'INV-100', 'client_name': 'Tata Elxsi',
        'items': [{'description': 'Training services', 'quantity': 1, 'rate': 15000}],
    }, 'invoice'), filetype='pdf')

    po_text = ''.join(page.get_text() for page in po)
    invoice_text = ''.join(page.get_text() for page in invoice)
    assert 'PURCHASE' in po_text and 'ORDER' in po_text
    assert 'Murali Mohan' in po_text
    assert 'TAX' in invoice_text and 'INVOICE' in invoice_text
    assert len(po[0].get_images()) >= 2
    assert len(invoice[0].get_images()) >= 2
