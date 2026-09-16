"""Calculate generated lab workbooks before returning or attaching them."""
import io
from pathlib import Path
import shutil
import subprocess
import tempfile

import openpyxl


def recalculate_lab_workbook(content):
    executable = shutil.which('libreoffice') or shutil.which('soffice')
    if not executable:
        raise ValueError('Lab workbook calculation service is unavailable')
    with tempfile.TemporaryDirectory(prefix='lab-calc-') as directory:
        root = Path(directory)
        source = root / 'estimate.xlsx'
        source.write_bytes(content)
        output = root / 'calculated'
        output.mkdir()
        subprocess.run([
            executable, '-env:UserInstallation=' + (root / 'profile').as_uri(),
            '--headless', '--convert-to', 'xlsx', '--outdir', str(output), str(source),
        ], check=True, timeout=90, capture_output=True)
        result = (output / source.name).read_bytes()
    formulas = openpyxl.load_workbook(io.BytesIO(result), data_only=False)
    values = openpyxl.load_workbook(io.BytesIO(result), data_only=True)
    for sheet in formulas:
        for row in sheet:
            for cell in row:
                cached = values[sheet.title][cell.coordinate]
                if cached.data_type == 'e' or (cell.data_type == 'f' and cached.value is None):
                    raise ValueError(f'Lab calculation failed at {sheet.title}!{cell.coordinate}')
    return result
