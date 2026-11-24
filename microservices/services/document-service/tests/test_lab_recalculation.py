import io
import shutil

import openpyxl
import pytest

from app.lab_recalculation import final_estimated_cost, recalculate_lab_workbook
from app.lab_sheet import combine_lab_estimates
from app.routes.excel import _lab_cost_to_excel


def test_final_estimated_cost_reads_calculated_total():
    book = openpyxl.Workbook()
    sheet = book.active
    sheet.title = "Client Estimate"
    sheet["A12"] = "Final estimated cost"
    sheet["B12"] = 1234.5
    content = io.BytesIO()
    book.save(content)
    assert final_estimated_cost(content.getvalue()) == 1234.5


def test_calculator_unavailable_blocks_delivery(monkeypatch):
    monkeypatch.setattr(shutil, 'which', lambda name: None)
    with pytest.raises(ValueError, match='unavailable'):
        recalculate_lab_workbook(b'not used')


@pytest.mark.skipif(not shutil.which('libreoffice'), reason='Requires production calculator')
def test_real_aws_and_azure_totals_survive_combination():
    inputs = []
    expected = []
    for provider, region in [('aws', 'ap-south-1'), ('azure', 'centralindia')]:
        raw = _lab_cost_to_excel({'title': 'DevOps', 'days': [{'focus_area': 'Docker AWS cloud lab'}]}, {
            'cloud_provider': provider, 'cloud_region': region, 'participant_count': 20,
            'hours_per_day': 3, 'fx_rate': 95, 'vm_profile_rates': {'Light': .05, 'Heavy': .2},
        })
        calculated = recalculate_lab_workbook(raw)
        book = openpyxl.load_workbook(io.BytesIO(calculated), data_only=True)
        total = next(row[1].value for row in book['Client Estimate'] if row[0].value == 'Final estimated cost')
        assert isinstance(total, (int, float)) and total > 0
        expected.append(total)
        inputs.append((provider, calculated))
    combined = recalculate_lab_workbook(combine_lab_estimates(inputs))
    book = openpyxl.load_workbook(io.BytesIO(combined), data_only=True)
    actual = [row[1].value for row in book.active if row[0].value == 'Final estimated cost']
    assert actual == pytest.approx(expected)
