"""Consistent, paginated purchase orders and invoices from verified record fields."""
from html import escape
from io import BytesIO

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
    return context.get('company_name_full') or context.get('company_name') or ('BEULIX SOLUTIONS PRIVATE LIMITED' if kind == 'invoice' else 'CLAHAN TECHNOLOGIES')


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
    from reportlab.lib.enums import TA_RIGHT
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Table, TableStyle, Spacer, KeepTogether

    c = prepare(context)
    invoice = kind == 'invoice'
    title = 'INVOICE' if invoice else 'PURCHASE ORDER'
    identifier = c.get('invoice_number' if invoice else 'po_number') or ''
    navy, teal, muted, border, pale = [colors.HexColor(v) for v in ('#122B40', '#087F8C', '#596B7B', '#DCE5EB', '#F2F6F8')]
    body = ParagraphStyle('Body', fontName='Helvetica', fontSize=9, leading=13, textColor=navy, splitLongWords=True)
    label = ParagraphStyle('Label', parent=body, fontName='Helvetica-Bold', fontSize=7, leading=10, textColor=muted, spaceAfter=4)
    strong = ParagraphStyle('Strong', parent=body, fontName='Helvetica-Bold', fontSize=11, leading=15)
    heading = ParagraphStyle('Heading', parent=body, fontName='Helvetica-Bold', fontSize=25, leading=29, alignment=TA_RIGHT)
    right = ParagraphStyle('Right', parent=body, alignment=TA_RIGHT)
    small = ParagraphStyle('Small', parent=body, fontSize=8, leading=11, textColor=muted)
    white = ParagraphStyle('White', parent=label, textColor=colors.white, spaceAfter=0)
    width = A4[0] - 88
    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4, leftMargin=44, rightMargin=44, topMargin=42, bottomMargin=48,
        title=f'{title.title()} {identifier}', author=issuer(c, kind))

    def p(value, style=body):
        return Paragraph(text(value) or '-', style)

    def field(name, value):
        return [p(name.upper(), label), p(value, body)]

    def panel(rows, widths, background=None):
        table = Table(rows, colWidths=widths, hAlign='LEFT')
        commands = [('VALIGN', (0, 0), (-1, -1), 'TOP'), ('LEFTPADDING', (0, 0), (-1, -1), 12),
            ('RIGHTPADDING', (0, 0), (-1, -1), 12), ('TOPPADDING', (0, 0), (-1, -1), 11), ('BOTTOMPADDING', (0, 0), (-1, -1), 11)]
        if background:
            commands.append(('BACKGROUND', (0, 0), (-1, -1), background))
        table.setStyle(TableStyle(commands))
        return table

    company = [p(issuer(c, kind), strong)]
    for value in (c.get('company_address'), c.get('company_email'), c.get('company_contact')):
        if value:
            company.append(p(value, small))
    for key, caption in (('company_gst', 'GSTIN'), ('company_pan', 'PAN')):
        if c.get(key):
            company.append(p(f'{caption}: {c[key]}', small))
    header = panel([[company, [p(title, heading), p(identifier, right)]]], [width * .53, width * .47])
    header.setStyle(TableStyle([('LINEABOVE', (0, 0), (-1, 0), 4, teal), ('LINEBELOW', (0, 0), (-1, -1), .7, border)]))
    story = [header, Spacer(1, 16)]
    meta = [('Issue date', c.get('invoice_date' if invoice else 'date'))]
    if invoice:
        meta += [('Due date', c.get('due_date')), ('PO reference', c.get('client_po_number'))]
    else:
        meta += [('Training dates', c.get('training_dates')), ('Delivery mode', c.get('mode'))]
    story += [panel([[field(k, v) for k, v in meta]], [width / len(meta)] * len(meta), pale), Spacer(1, 18)]

    customer = [p('BILL TO' if invoice else 'CLIENT', label), p(c.get('client_name'), strong)]
    for value in (c.get('client_address') or c.get('client_billing_address'), c.get('client_email')):
        if value:
            customer.append(p(value))
    for key, caption in (('client_gstin', 'GSTIN'), ('client_pan', 'PAN')):
        value = c.get(key) or (c.get('client_gst') if key == 'client_gstin' else '')
        if value:
            customer.append(p(f'{caption}: {value}', small))
    scope = [p('ENGAGEMENT' if invoice else 'VENDOR / TRAINER', label)]
    if not invoice:
        scope.append(p(c.get('vendor_name'), strong))
    for caption, value in (('Training', c.get('training_domain')), ('Duration', c.get('duration')),
                           ('Place of supply', c.get('place_of_supply'))):
        if value:
            scope.append(p(f'{caption}: {value}'))
    story += [panel([[customer, scope]], [width * .54, width * .46]), Spacer(1, 14)]

    widths = [26, width - 267, 53, 38, 72, 78]
    rows = [[p(v, white) for v in ('#', 'DESCRIPTION', 'HSN / SAC', 'QTY', 'RATE / INR', 'AMOUNT / INR')]]
    for index, item in enumerate(c['items'], 1):
        rows.append([p(f'{index:02}', small), p(item['description']), p(item.get('hsn_sac'), small),
            p(f"{item['quantity']:g}", right), p(f"{item['rate']:,.2f}", right), p(f"{item['amount']:,.2f}", right)])
    table = Table(rows, colWidths=widths, repeatRows=1, hAlign='LEFT')
    table.setStyle(TableStyle([('BACKGROUND', (0, 0), (-1, 0), navy), ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, pale]), ('LINEBELOW', (0, 1), (-1, -1), .4, border),
        ('LEFTPADDING', (0, 0), (-1, -1), 7), ('RIGHTPADDING', (0, 0), (-1, -1), 7),
        ('TOPPADDING', (0, 0), (-1, -1), 10), ('BOTTOMPADDING', (0, 0), (-1, -1), 10)]))
    story += [table, Spacer(1, 14)]
    taxes = tax_lines(c)
    summary = [('Subtotal', c['subtotal']), *taxes,
               ('Invoice total' if invoice else 'Order total', c['grand_total'])]
    if invoice and c['balance_due'] != c['grand_total']:
        summary += [('Balance due', c['balance_due'])]
    total_table = panel([[p(name), p(f'INR {amount:,.2f}', right)] for name, amount in summary], [130, 137], pale)
    total_table.hAlign = 'RIGHT'
    total_table.setStyle(TableStyle([('LINEABOVE', (0, 1 + len(taxes)), (-1, 1 + len(taxes)), 1, teal), ('TOPPADDING', (0, 0), (-1, -1), 7), ('BOTTOMPADDING', (0, 0), (-1, -1), 7)]))
    cents = int(money(number(c['grand_total'], 'Total')) * 100)
    amount_words = _number_to_words(cents // 100) + ' Rupees'
    if cents % 100:
        amount_words += ' and ' + _number_to_words(cents % 100) + ' Paise'
    amount_words += ' Only'
    story += [KeepTogether([total_table, Spacer(1, 12), p('AMOUNT IN WORDS', label), p(amount_words, small), Spacer(1, 20)])]
    details = []
    if invoice and (c.get('bank_account_no') or c.get('bank_ifsc')):
        details += [p('PAYMENT DETAILS', label)]
        for key, caption in (('bank_account_no', 'Account number'), ('bank_ifsc', 'IFSC')):
            if c.get(key):
                details.append(p(f'{caption}: {c[key]}'))
        details += [Spacer(1, 10)]
    terms = c.get('terms_and_conditions') or c.get('payment_terms')
    if terms:
        details += [p('PAYMENT TERMS', label), p(terms), Spacer(1, 10)]
    if c.get('notes'):
        details += [p('NOTES', label), p(c['notes']), Spacer(1, 10)]
    # Text and notes remain flowing paragraphs so long documents paginate.
    story += details
    story += [KeepTogether([Spacer(1, 24), p(c.get('signatory_name') or 'Authorized signatory', right)])]

    def footer(canvas, document):
        canvas.saveState()
        canvas.setStrokeColor(border)
        canvas.line(44, 36, A4[0] - 44, 36)
        canvas.setFillColor(muted)
        canvas.setFont('Helvetica', 7)
        canvas.drawString(44, 23, f'{title.title()} | {identifier}'[:90])
        canvas.drawRightString(A4[0] - 44, 23, f'Page {document.page}')
        canvas.restoreState()

    doc.build(story, onFirstPage=footer, onLaterPages=footer)
    return buffer.getvalue()


def render_html(context, kind):
    c = prepare(context)
    invoice = kind == 'invoice'
    title = 'Invoice' if invoice else 'Purchase Order'
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
