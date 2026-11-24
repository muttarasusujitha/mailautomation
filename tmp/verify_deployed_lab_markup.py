"""Check deployed generator and actual recalculated totals, without sending mail."""
import io
import json
import math

import openpyxl
from app.routes.excel import _lab_cost_to_excel
from app.lab_recalculation import recalculate_lab_workbook

results = []
for markup in (None, 30, 15, 0):
    assumptions = dict(cloud_provider='aws', cloud_region='ap-south-1',
        participant_count=2, hours_per_day=3, fx_rate=90)
    if markup is not None:
        assumptions['clahan_margin_percent'] = markup
    raw = _lab_cost_to_excel({'title': 'Synthetic deployment check',
        'days': [{'focus_area': 'Linux', 'lab': 'Shell practice on AWS'}]}, assumptions)
    book = openpyxl.load_workbook(io.BytesIO(recalculate_lab_workbook(raw)), data_only=True)
    assert book.active.title == 'Lab Plan'
    quote = book['Client Estimate']
    subtotal = sum(quote[f'B{row}'].value for row in range(8, 12))
    expected_percent = 30 if markup is None else markup
    assert subtotal > 0
    assert math.isclose(quote['B12'].value, subtotal * (1 + expected_percent / 100))
    results.append({'configured_percent': markup, 'applied_percent': expected_percent, 'passed': True})
print(json.dumps(results))
