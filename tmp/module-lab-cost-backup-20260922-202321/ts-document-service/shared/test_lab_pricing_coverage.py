import pytest
from shared.lab_cost_inputs import validate_lab_pricing_coverage
from shared.lab_cost_inputs import lab_resources
from shared.lab_planning import default_cloud_mapping


@pytest.mark.parametrize('text', ['Coding standards', 'Azure Boards', 'Passwords and dashboards', 'Pipeline breaks'])
def test_ordinary_words_do_not_enable_managed_services(text):
    resources = lab_resources(text)
    assert not resources['database']
    assert not resources['k8s']


@pytest.mark.parametrize('text', ['AWS RDS', 'RDS: PostgreSQL', 'Azure SQL', 'Cloud SQL'])
def test_explicit_database_services_remain_billable(text):
    assert lab_resources(text)['database']


def test_standards_lab_passes_compute_only_pricing_coverage():
    toc = {'days': [{'topic': 'Linux coding standards and passwords'}]}
    mapping = default_cloud_mapping(toc, {'participant_count': 20})
    assert mapping[0]['managed_db'] == 0
    validate_lab_pricing_coverage(toc, {
        'lab_day_mapping': mapping,
        'pricing_selections': {'VM Light': {'sku': 'vm'}, 'Disk': {'sku': 'disk'}},
        'egress_gb': 0, 'build_minutes': 0, 'monitoring_gb': 0,
    })


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


def test_zero_mapping_cannot_hide_practical_lab_costs():
    with pytest.raises(ValueError, match='days: 1'):
        validate_lab_pricing_coverage({'days': [{'topic': 'Linux Docker AWS labs'}]}, {
            'lab_day_mapping': [{'vm_qty': 0, 'vm_profile': 'None', 'k8s_control_plane': 0,
                                 'k8s_worker_nodes': 0, 'managed_db': 0, 'object_storage_gb': 0}],
            'egress_gb': 0, 'build_minutes': 0, 'monitoring_gb': 0,
        })


def test_explicit_mapping_requires_selected_vm_profile_rate():
    with pytest.raises(ValueError, match='VM Heavy'):
        validate_lab_pricing_coverage({'days': [{'topic': 'Linux Fundamentals'}]}, {
            'lab_day_mapping': {'1': {'vm_qty': 34, 'vm_profile': 'Heavy'}},
            'pricing_selections': {'VM Light': {'sku': 'light'}, 'Disk': {'sku': 'disk'}},
            'egress_gb': 0, 'build_minutes': 0, 'monitoring_gb': 0,
        })
