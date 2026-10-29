from shared.lab_planning import default_cloud_mapping


def test_34_learner_practical_days_have_vms_and_valid_profiles():
    mapping = default_cloud_mapping({'days': [
        {'topic': 'Linux Fundamentals'}, {'topic': 'Docker Fundamentals'},
        {'topic': 'Kubernetes Architecture'}, {'topic': 'Docker Desktop local machine'},
    ]}, {'participant_count': 34})
    assert [r['vm_qty'] for r in mapping] == [34, 34, 34, 0]
    assert [r['vm_profile'] for r in mapping] == ['Light', 'Heavy', 'Heavy', 'None']
    assert all(r['k8s_control_plane'] == 0 for r in mapping)


def test_managed_cluster_is_shared_not_multiplied_by_learners():
    row = default_cloud_mapping({'days': [{'topic': 'AWS EKS S3'}]}, {
        'participant_count': 34, 'k8s_worker_nodes': 2, 'storage_gb': 10,
    })[0]
    assert row['k8s_control_plane'] == 1
    assert row['k8s_worker_nodes'] == 2
    assert row['object_storage_gb'] == 10
