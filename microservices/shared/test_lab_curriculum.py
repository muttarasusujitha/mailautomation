from shared.lab_curriculum import cloud_lab_text, lab_setup_kind
from shared.lab_planning import default_cloud_mapping


def test_mixed_day_keeps_cloud_module_and_participants_not_module_count():
    day = {'modules': [
        {'title': 'Local containers', 'lab': 'Docker Desktop on local machine'},
        {'title': 'Cloud server', 'lab': 'Build Linux server on AWS EC2'},
        {'title': 'Cloud deployment', 'lab': 'Deploy application on AWS EC2'},
    ]}
    mapping = default_cloud_mapping({'days': [day]}, {'participant_count': 12})[0]
    assert mapping['vm_qty'] == 12
    assert mapping['active_days'] == 1
    assert lab_setup_kind(day) == 'mixed'
    assert 'ec2' in cloud_lab_text(day)
    assert 'docker desktop' not in cloud_lab_text(day)


def test_local_module_does_not_add_managed_services_to_cloud_module():
    day = {'modules': [
        {'lab': 'Local machine simulation of AWS EKS and RDS'},
        {'lab': 'Build Linux server on AWS EC2'},
    ]}
    mapping = default_cloud_mapping({'days': [day]}, {'participant_count': 5})[0]
    assert mapping['vm_qty'] == 5
    assert mapping['k8s_control_plane'] == mapping['managed_db'] == 0


def test_metadata_is_not_billable_scope():
    day = {'modules': [{'lab': 'Docker Desktop on local machine'}], 'review_warnings': ['Consider AWS EC2 and RDS']}
    assert cloud_lab_text(day) == ''
    assert default_cloud_mapping({'days': [day]}, {'participant_count': 20})[0]['vm_qty'] == 0


def test_day_local_override_applies_to_all_modules():
    day = {'lab_setup': 'local', 'modules': [{'lab': 'AWS EC2 simulation'}]}
    assert cloud_lab_text(day) == ''
