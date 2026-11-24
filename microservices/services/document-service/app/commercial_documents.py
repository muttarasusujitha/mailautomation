"""Consistent, paginated purchase orders and invoices from verified record fields."""
from html import escape
from io import BytesIO
from pathlib import Path

from shared.document_amounts import calculate_document, number, money


def prepare(context):
    result = dict(context)
    totals = calculate_document(result.get('items'), result.get('total_amount'), result.get('gst_rate', 0),
        description=f"{result.get('training_domain') or 'Training'} services",
        duration=result.get('duration'), day_rate=result.get('day_rate'))
    result.update(totals)
    balance = result.get('balance_due')
    result['balance_due'] = totals['grand_total'] if balance is None else float(money(number(balance, 'Balance due')))
    if result['balance_due'] > totals['grand_total']:
        raise ValueError('Balance due cannot exceed the invoice total')
    return result


def text(value):
    return escape(str(value if value is not None else '').replace('\u20b9', 'INR ').replace('\u2014', '-').replace('\u2013', '-')).replace('\n', '<br/>')


def issuer(context, kind):
    # Clahan runs the workflow, but Beulix is the legal issuer for both
    # commercial document types. A saved company profile can still override
    # this only when an authorised staff member intentionally supplies one.
    return context.get('company_name_full') or context.get('company_name') or 'BEULIX SOLUTIONS PRIVATE LIMITED'


def tax_lines(c):
    if c.get('tax_type') == 'cgst_sgst':
        # Keep both components in paise and preserve the authoritative total.
        central = float(money(number(c['gst_amount'], 'Tax') / 2))
        state = round(c['gst_amount'] - central, 2)
        return [(f"CGST ({c['gst_rate'] / 2:g}%)", central),
                (f"SGST ({c['gst_rate'] / 2:g}%)", state)]
    caption = 'IGST' if c.get('tax_type') == 'igst' else 'Tax / GST'
    return [(f"{caption} ({c['gst_rate']:g}%)", c['gst_amount'])]


def render_pdf(context, kind):
    from reportlab.lib import colors
    from reportlab.lib.enums import TA_CENTER, TA_RIGHT
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Table, TableStyle, Spacer, KeepTogether, Image

    c = prepare(context)
    invoice = kind == 'invoice'
    title = 'TAX INVOICE' if invoice else 'PURCHASE ORDER'
    identifier = c.get('invoice_number' if invoice else 'po_number') or ''
    black, muted, blue = [colors.HexColor(value) for value in ('#000000', '#333333', '#2449A4')]
    body = ParagraphStyle('Body', fontName='Helvetica', fontSize=8.8, leading=12, textColor=black, splitLongWords=True)
    compact = ParagraphStyle('Compact', parent=body, fontSize=8, leading=10.5)
    label = ParagraphStyle('Label', parent=body, fontName='Helvetica-Bold', fontSize=8.5, leading=10, alignment=TA_CENTER)
    band_label = ParagraphStyle('BandLabel', parent=label, textColor=colors.white)
    strong = ParagraphStyle('Strong', parent=body, fontName='Helvetica-Bold', fontSize=9.5, leading=13)
    strong_centered = ParagraphStyle('StrongCentered', parent=strong, alignment=TA_CENTER)
    title_style = ParagraphStyle('Title', parent=body, fontName='Helvetica-Bold', fontSize=15, leading=18, alignment=TA_CENTER)
    centered = ParagraphStyle('Centered', parent=body, alignment=TA_CENTER, leading=13)
    right = ParagraphStyle('Right', parent=body, alignment=TA_RIGHT)
    company_text = ParagraphStyle('Company', parent=body, fontName='Helvetica', fontSize=7.2, leading=9, alignment=TA_RIGHT, textColor=muted)
    width = A4[0] - 84
    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4, leftMargin=42, rightMargin=42, topMargin=30, bottomMargin=42,
        title=f'{title.title()} {identifier}', author=issuer(c, kind))

    def p(value, style=body):
        return Paragraph(text(value) or '-', style)

    def panel(rows, widths, *, header_rows=0, row_heights=None):
        table = Table(rows, colWidths=widths, rowHeights=row_heights, hAlign='LEFT')
        commands = [('VALIGN', (0, 0), (-1, -1), 'TOP'), ('BOX', (0, 0), (-1, -1), 1, black),
            ('INNERGRID', (0, 0), (-1, -1), .8, black), ('LEFTPADDING', (0, 0), (-1, -1), 5),
            ('RIGHTPADDING', (0, 0), (-1, -1), 5), ('TOPPADDING', (0, 0), (-1, -1), 5), ('BOTTOMPADDING', (0, 0), (-1, -1), 5)]
        if header_rows:
            commands += [('BACKGROUND', (0, 0), (-1, header_rows - 1), blue),
                         ('VALIGN', (0, 0), (-1, header_rows - 1), 'MIDDLE')]
        table.setStyle(TableStyle(commands))
        return table

    logo_path = Path(__file__).resolve().parent / 'assets' / 'beulix_logo.png'
    company = None
    if logo_path.exists():
        company = Image(str(logo_path), width=150, height=31)
    else:
        company = p(issuer(c, kind), strong)
    issuer_details = []
    for value in (c.get('company_address'), c.get('company_email'), c.get('company_contact')):
        if value:
            issuer_details.append(str(value))
    identifiers = ' | '.join(f'{caption}: {c[key]}' for key, caption in (('company_gst', 'GST No.'), ('company_pan', 'PAN')) if c.get(key))
    if identifiers:
        issuer_details.append(identifiers)
    issuer_copy = '<b>' + text(issuer(c, kind)) + '</b>'
    if issuer_details:
        issuer_copy += '<br/>' + '<br/>'.join(text(value) for value in issuer_details)
    story = [Table([[company, Paragraph(issuer_copy, company_text)]],
                   colWidths=[width * .38, width * .62 - 8], hAlign='LEFT', style=TableStyle([
                       ('VALIGN', (0, 0), (-1, -1), 'TOP'), ('LEFTPADDING', (0, 0), (-1, -1), 0),
                       ('RIGHTPADDING', (0, 0), (-1, -1), 0), ('TOPPADDING', (0, 0), (-1, -1), 0),
                       ('BOTTOMPADDING', (0, 0), (-1, -1), 0)])), Spacer(1, 46), p(title, title_style), Spacer(1, 18)]

    other_name = c.get('client_name') if invoice else c.get('vendor_name')
    other_details = []
    for value in ((c.get('client_address') or c.get('client_billing_address')) if invoice else c.get('vendor_address'),
                  c.get('client_email') if invoice else c.get('vendor_email'),
                  c.get('vendor_contact') if not invoice else None):
        if value:
            other_details.append(p(value, compact))
    gst = c.get('client_gstin') or c.get('client_gst') if invoice else c.get('vendor_gst')
    pan = c.get('client_pan') if invoice else c.get('vendor_pan')
    ids = ' | '.join(f'{caption}: {value}' for caption, value in (('GSTIN', gst), ('PAN', pan)) if value)
    if ids:
        other_details.append(p(ids, compact))
    primary = [p(other_name, strong), *other_details]
    primary_label = 'CUSTOMER' if invoice else 'VENDOR/TRAINER'
    date_value = c.get('invoice_date' if invoice else 'date') or '-'
    number_label = 'INVOICE NUMBER' if invoice else 'ORDER NUMBER'
    top = panel([[p(primary_label, band_label), p('DATE', band_label), p(number_label, band_label)],
                 [primary, p(date_value, centered), p(identifier, centered)]],
                [width * .53, width * .21, width * .26], header_rows=1, row_heights=[26, 120])
    story += [top, Spacer(1, 16)]

    bill = [p(c.get('client_name'), strong)]
    for value in (c.get('client_address') or c.get('client_billing_address'), c.get('client_email')):
        if value:
            bill.append(p(value, compact))
    client_ids = ' | '.join(f'{caption}: {value}' for caption, value in
                            (('GST', c.get('client_gstin') or c.get('client_gst')), ('PAN', c.get('client_pan'))) if value)
    if client_ids:
        bill.append(p(client_ids, compact))
    delivery = [p(f"Client: {c.get('client_name') or '-'}", body)]
    for caption, value in (('Training', c.get('training_domain')), ('Duration', c.get('duration')),
                           ('PO reference', c.get('client_po_number') if invoice else None), ('Mode', c.get('mode'))):
        if value:
            delivery.append(p(f'{caption}: {value}', compact))
    billing = panel([[p('BILL TO', band_label), p('DELIVER TO', band_label)], [bill, delivery]],
                    [width * .53, width * .47], header_rows=1, row_heights=[24, 64])
    story += [billing, Spacer(1, 14)]

    widths = [width * .53, width * .13, width * .16, width * .18]
    rows = [[p('ITEM', band_label), Paragraph('RATE<br/>(INR)', band_label), p('Qty', band_label), p('AMOUNT (INR)', band_label)]]
    for index, item in enumerate(c['items'], 1):
        quantity = f"{item['quantity']:g}"
        if index == 1 and c.get('duration'):
            quantity += f"\n{c['duration']}"
        rows.append([p(item['description']), p(f"{item['rate']:,.2f}", centered),
            p(quantity, centered), p(f"{item['amount']:,.2f}", centered)])
    table = Table(rows, colWidths=widths, rowHeights=[36] + [None] * len(c['items']), repeatRows=1, hAlign='LEFT')
    table.setStyle(TableStyle([('BACKGROUND', (0, 0), (-1, 0), blue), ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('GRID', (0, 0), (-1, -1), .8, black), ('LEFTPADDING', (0, 0), (-1, -1), 5),
        ('RIGHTPADDING', (0, 0), (-1, -1), 5), ('TOPPADDING', (0, 0), (-1, -1), 8),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 8)]))
    total_table = Table([[p('Total', strong_centered), p(f"{c['grand_total']:,.2f}", centered)]],
                        colWidths=[width * .82, width * .18], hAlign='LEFT')
    total_table.setStyle(TableStyle([('GRID', (0, 0), (-1, -1), .8, black), ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('LEFTPADDING', (0, 0), (-1, -1), 5), ('RIGHTPADDING', (0, 0), (-1, -1), 5),
        ('TOPPADDING', (0, 0), (-1, -1), 6), ('BOTTOMPADDING', (0, 0), (-1, -1), 6)]))
    story += [table, total_table, Spacer(1, 14)]
    cents = int(money(number(c['grand_total'], 'Total')) * 100)
    amount_words = _number_to_words(cents // 100) + ' Rupees'
    if cents % 100:
        amount_words += ' and ' + _number_to_words(cents % 100) + ' Paise'
    amount_words += ' Only'
    notes = [f'1. Amount in words: {amount_words}.']
    for value in (c.get('terms_and_conditions') or c.get('payment_terms'), c.get('notes')):
        if value:
            notes.append(f'{len(notes) + 1}. {value}')
    if invoice and (c.get('bank_account_no') or c.get('bank_ifsc')):
        bank = ' | '.join(f'{caption}: {c[key]}' for key, caption in (('bank_account_no', 'Account number'), ('bank_ifsc', 'IFSC')) if c.get(key))
        notes.append(f'{len(notes) + 1}. Payment details - {bank}.')
    note_body = [p('<br/>'.join(notes), body)]
    notes_table = panel([[p('IMPORTANT NOTES', band_label)], note_body], [width], header_rows=1, row_heights=[24, 104])
    signature_path = Path(__file__).resolve().parent / 'assets' / 'murali_signature.png'
    signature = []
    if signature_path.exists():
        signature_table = Table([[Image(str(signature_path), width=104, height=31)]], colWidths=[108], hAlign='RIGHT')
        signature_table.setStyle(TableStyle([('LEFTPADDING', (0, 0), (-1, -1), 0), ('RIGHTPADDING', (0, 0), (-1, -1), 0),
            ('TOPPADDING', (0, 0), (-1, -1), 0), ('BOTTOMPADDING', (0, 0), (-1, -1), 0)]))
        signature = [Spacer(1, 7), signature_table]
    story += [notes_table, Spacer(1, 30), p(f'For {issuer(c, kind)}', right), *signature,
              Spacer(1, 7), p(c.get('signatory_name') or 'Authorized Signatory', right)]

    def footer(canvas, document):
        canvas.saveState()
        canvas.setStrokeColor(black)
        canvas.line(42, 29, A4[0] - 42, 29)
        canvas.setFillColor(muted)
        canvas.setFont('Helvetica', 7)
        canvas.drawString(42, 17, f'{title.title()} | {identifier}'[:90])
        canvas.drawRightString(A4[0] - 42, 17, f'Page {document.page}')
        canvas.restoreState()

    doc.build(story, onFirstPage=footer, onLaterPages=footer)
    return buffer.getvalue()


def render_html(context, kind):
    c = prepare(context)
    invoice = kind == 'invoice'
    title = 'Tax Invoice' if invoice else 'Purchase Order'
    identifier = c.get('invoice_number' if invoice else 'po_number')
    taxes = '<br>'.join(f'{text(caption)}: INR {amount:,.2f}' for caption, amount in tax_lines(c))
    bank = '<br>'.join(f'{label}: {text(c.get(key))}' for key, label in [('bank_account_no', 'Account number'), ('bank_ifsc', 'IFSC')] if c.get(key))
    rows = ''.join(f'<tr><td>{i}</td><td>{text(r["description"])}</td><td>{text(r.get("hsn_sac"))}</td><td>{r["quantity"]:g}</td><td>{r["rate"]:,.2f}</td><td>{r["amount"]:,.2f}</td></tr>' for i, r in enumerate(c['items'], 1))
    return f'''<!doctype html><html><head><meta charset="utf-8"><title>{title} {text(identifier)}</title>
    <style>@page{{size:A4;margin:18mm}}body{{font:14px/1.6 Arial;color:#122b40;max-width:800px;margin:40px auto}}
    header{{border-top:5px solid #087f8c;border-bottom:1px solid #dce5eb;padding:22px 0;display:flex;justify-content:space-between}}
    h1{{margin:0}}section{{padding:16px 0}}.meta,.totals{{background:#f2f6f8;padding:16px}}table{{width:100%;border-collapse:collapse}}
    th{{background:#122b40;color:white}}td,th{{padding:10px;text-align:right;border-bottom:1px solid #dce5eb}}td:nth-child(2),th:nth-child(2){{text-align:left}}
    thead{{display:table-header-group}}tr{{break-inside:avoid}}.totals{{margin:20px 0 20px auto;width:280px}}small{{color:#596b7b}}</style></head><body>
    <header><div><b>{text(issuer(c,kind))}</b><br>{text(c.get('company_address'))}</div><div><h1>{title}</h1>{text(identifier)}</div></header>
    <section class="meta">Issue date: {text(c.get('invoice_date' if invoice else 'date'))}<br>{'Due date: '+text(c.get('due_date')) if invoice else 'Training dates: '+text(c.get('training_dates'))}</section>
    <section><small>{'BILL TO' if invoice else 'CLIENT'}</small><br><b>{text(c.get('client_name'))}</b><br>{text(c.get('client_address') or c.get('client_billing_address'))}<br>GSTIN: {text(c.get('client_gstin') or c.get('client_gst'))}</section>
    <section>{'PO reference: '+text(c.get('client_po_number')) if invoice else 'Vendor / Trainer: '+text(c.get('vendor_name'))}<br>{text(c.get('training_domain'))}</section>
    <table><thead><tr><th>#</th><th>Description</th><th>HSN/SAC</th><th>Qty</th><th>Rate INR</th><th>Amount INR</th></tr></thead><tbody>{rows}</tbody></table>
    <div class="totals">Subtotal: INR {c['subtotal']:,.2f}<br>{taxes}<br><b>Total: INR {c['grand_total']:,.2f}</b></div>
    <section>{bank}</section>
    <section>{text(c.get('payment_terms') or c.get('terms_and_conditions'))}<br>{text(c.get('notes'))}</section>
    <section>{text(c.get('signatory_name') or 'Authorized signatory')}</section></body></html>'''


def _number_to_words(number: int) -> str:
    """Convert an integer number to English words for invoice totals."""
    if number == 0:
        return "Zero"

    units = ["", "One", "Two", "Three", "Four", "Five", "Six", "Seven", "Eight", "Nine"]
    teens = ["Ten", "Eleven", "Twelve", "Thirteen", "Fourteen", "Fifteen", "Sixteen", "Seventeen", "Eighteen", "Nineteen"]
    tens = ["", "", "Twenty", "Thirty", "Forty", "Fifty", "Sixty", "Seventy", "Eighty", "Ninety"]
    scales = [(10000000, "Crore"), (100000, "Lakh"), (1000, "Thousand"), (100, "Hundred")]

    def _under_thousand(n: int) -> str:
        words = []
        if n >= 100:
            words.append(units[n // 100])
            words.append("Hundred")
            n %= 100
        if n >= 20:
            words.append(tens[n // 10])
            n %= 10
        elif n >= 10:
            words.append(teens[n - 10])
            n = 0
        if n > 0:
            words.append(units[n])
        return " ".join(words)

    parts = []
    for scale_value, scale_name in scales:
        if number >= scale_value:
            scale_count = number // scale_value
            parts.append(_under_thousand(scale_count))
            parts.append(scale_name)
            number %= scale_value
    if number > 0:
        parts.append(_under_thousand(number))
    return " ".join(part for part in parts if part)
