"""Isolated formula verification using the document container's calculator."""
import io
import json
import math
from pathlib import Path
import subprocess

import fitz
import openpyxl

from lab_recalculation import recalculate_lab_workbook

root = Path(__file__).resolve().parent
totals = {}
for provider in ('aws', 'azure'):
    raw = (root / f'{provider}.xlsx').read_bytes()
    calculated = recalculate_lab_workbook(raw)
    (root / f'{provider}-calculated.xlsx').write_bytes(calculated)
    book = openpyxl.load_workbook(io.BytesIO(calculated), data_only=True)
    plan, quote = book['Lab Plan'], book['Client Estimate']
    assert plan['F8'].value == 6
    assert plan['G9'].value == 0
    assert math.isclose(plan['G10'].value + plan['G11'].value, quote['B8'].value)
    assert math.isclose(plan['G19'].value, quote['B12'].value)
    assert math.isclose(plan['G20'].value, quote['B12'].value / 10)
    assert plan['C9'].value == '=1+1'
    totals[provider] = plan['G19'].value

combined = recalculate_lab_workbook((root / 'combined.xlsx').read_bytes())
(root / 'combined-calculated.xlsx').write_bytes(combined)
sheet = openpyxl.load_workbook(io.BytesIO(combined), data_only=True).active
actual = [row[6].value for row in sheet if row[0].value == 'Priced lab subtotal - incomplete estimate']
assert len(actual) == 2
assert all(math.isclose(value, expected) for value, expected in zip(actual, totals.values()))
assert sum(cell.value == '=1+1' for row in sheet for cell in row) == 2

# Render the generated output for visual QA without changing its layout.
subprocess.run(['libreoffice', '-env:UserInstallation=' + (root / 'pdf-profile').as_uri(),
    '--headless', '--convert-to', 'pdf', '--outdir', str(root), str(root / 'aws-calculated.xlsx')],
    check=True, capture_output=True, timeout=90)
pdf = fitz.open(root / 'aws-calculated.pdf')
for page_index in range(min(2, len(pdf))):
    pdf[page_index].get_pixmap(matrix=fitz.Matrix(1.2, 1.2)).save(root / f'preview-{page_index + 1}.png')
print(json.dumps({'formula_checks': 'passed', 'combined_reconciliation': 'passed',
    'synthetic_test_totals': totals, 'pdf_pages': len(pdf)}))
