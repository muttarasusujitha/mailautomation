import pytest
from shared.lab_cost_inputs import validate_lab_pricing_coverage


def test_compute_only_quote_rejects_unpriced_disk_and_storage():
    with pytest.raises(ValueError, match='Disk'):
        validate_lab_pricing_coverage({'days': [{'topic': 'EC2 S3'}]}, {
            'pricing_selections': {'VM Light': {'sku': 'vm'}, 'Disk': {'auto_zero': True}},
        })


def test_unspecified_practical_environment_requires_mapping():
    with pytest.raises(ValueError, match='days: 1'):
        validate_lab_pricing_coverage({'days': [{'topic': 'Linux Fundamentals'}]}, {})


def test_explicit_local_environment_can_have_no_cloud_charges():
    validate_lab_pricing_coverage({'days': [{'topic': 'Docker Desktop local lab'}]}, {
        'egress_gb': 0, 'build_minutes': 0, 'monitoring_gb': 0,
    })


def test_explicit_mapping_requires_selected_vm_profile_rate():
    with pytest.raises(ValueError, match='VM Heavy'):
        validate_lab_pricing_coverage({'days': [{'topic': 'Linux Fundamentals'}]}, {
            'lab_day_mapping': {'1': {'vm_qty': 34, 'vm_profile': 'Heavy'}},
            'pricing_selections': {'VM Light': {'sku': 'light'}, 'Disk': {'sku': 'disk'}},
            'egress_gb': 0, 'build_minutes': 0, 'monitoring_gb': 0,
        })
