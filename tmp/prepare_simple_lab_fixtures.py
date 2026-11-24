"""Build regression fixtures with the current application generator."""
import importlib.util
from pathlib import Path
import shutil
import sys

root = Path(__file__).resolve().parents[1]
service = root / 'mailautomation/microservices/services/document-service'
sys.path[:0] = [str(service), str(root / 'mailautomation/microservices')]
spec = importlib.util.spec_from_file_location('lab_fixture_tests', service / 'tests/test_lab_plan.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
from app.lab_sheet import combine_lab_estimates

destination = root / 'tmp/lab-layout-check-20260921'
destination.mkdir(exist_ok=True)
estimates = []
for provider in ('aws', 'azure'):
    content = module.sample_estimate(provider)
    (destination / f'{provider}.xlsx').write_bytes(content)
    estimates.append((provider, content))
(destination / 'combined.xlsx').write_bytes(combine_lab_estimates(estimates))
shutil.copy2(service / 'app/lab_recalculation.py', destination)
shutil.copy2(root / 'tmp/verify_simple_lab_layout.py', destination)
print(destination)
