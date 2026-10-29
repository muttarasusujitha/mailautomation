"""Fixed architecture scenarios; expected quantities are not provider quotes."""
import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from shared.lab_planning import default_cloud_mapping, plan_resources, resource_context


def resources(**overrides):
    return dict(dict(vm_qty=12, vm_profile='Light', k8s_control_plane=0,
                     k8s_worker_nodes=0, managed_db=0, object_storage_gb=0,
                     storage_put_requests=0, storage_get_requests=0, active_days=1), **overrides)


def run_plan(day, row, **assumptions):
    client = SimpleNamespace(responses=SimpleNamespace(create=AsyncMock(
        return_value=SimpleNamespace(output_text=json.dumps({'days': [row]})))))
    return asyncio.run(plan_resources('ai', {'days': [day]},
        dict(dict(participant_count=12, cloud_provider='aws', hours_per_day=6), **assumptions),
        client, 'test', native_schema=True))


@pytest.mark.parametrize('lab,row,message', [
    ('Create AWS EC2 servers', resources(vm_qty=0, vm_profile='None'), 'Amazon EC2'),
    ('Deploy on Amazon EKS', resources(), 'Amazon EKS'),
    ('Create an Amazon RDS database', resources(), 'Amazon RDS'),
    ('Upload objects to Amazon S3', resources(), 'Amazon S3'),
    ('Linux shell', resources(k8s_worker_nodes=2), 'control plane and workers'),
    ('Linux shell', resources(k8s_control_plane=2, k8s_worker_nodes=1), 'at least one worker'),
    ('Linux shell', resources(storage_get_requests=100), 'object-storage allocation'),
    ('Linux shell', resources(active_days=5), 'TOC duration'),
    ('Run minikube on AWS EC2', resources(), 'Heavy profile'),
])
def test_contradictory_ai_architectures_are_rejected(lab, row, message):
    with pytest.raises(ValueError, match=message):
        run_plan({'lab': lab}, row)


def test_individual_vm_labs_cannot_underallocate_participants():
    with pytest.raises(ValueError, match='one VM per participant'):
        run_plan({'lab': 'AWS EC2'}, resources(vm_qty=1), lab_setup='individual')


@pytest.mark.parametrize('provider,lab', [
    ('aws', 'Deploy on Amazon EKS using Amazon RDS and Amazon S3'),
    ('azure', 'Deploy on AKS using Azure SQL and Azure Blob Storage'),
    ('gcp', 'Deploy on GKE using Google Cloud SQL and Google Cloud Storage'),
])
def test_complete_managed_architectures_pass(provider, lab):
    row = resources(k8s_control_plane=1, k8s_worker_nodes=2, managed_db=1,
                    object_storage_gb=10, storage_put_requests=12, storage_get_requests=120)
    assert run_plan({'lab': lab}, row, cloud_provider=provider) == [row]


def test_local_simulation_is_not_treated_as_billable_managed_services():
    row = resources(vm_qty=0, vm_profile='None')
    assert run_plan({'lab': 'Simulate AWS EKS and RDS on local machine'}, row) == [row]


def test_known_local_scope_never_calls_a_model_for_cloud_quantities():
    client = SimpleNamespace(responses=SimpleNamespace(create=AsyncMock(
        side_effect=AssertionError('No model needed for explicit local delivery'))))
    rows = asyncio.run(plan_resources('ai', {'days': [{'lab': 'AWS EKS simulation'}]},
        {'participant_count': 12, 'cloud_provider': 'aws', 'lab_setup': 'local'}, client, 'test'))
    assert rows == [resources(vm_qty=0, vm_profile='None')]
    client.responses.create.assert_not_called()


def test_shared_setup_and_per_day_overrides_change_template_vm_quantity():
    toc = {'days': [{'lab': 'AWS EC2'}, {'lab': 'AWS EC2'}, {'lab': 'AWS EC2'}]}
    rows = default_cloud_mapping(toc, {'participant_count': 12, 'lab_setup': 'shared',
                                      'lab_day_setups': {'2': 'individual', '3': 'local'}})
    assert [row['vm_qty'] for row in rows] == [1, 12, 0]
    assert all('lab_setup' not in day for day in toc['days'])


def test_shared_ai_vm_and_multi_day_entry_are_valid():
    row = resources(vm_qty=1, active_days=3)
    assert run_plan({'lab': 'AWS EC2', 'duration_days': 3}, row, lab_setup='shared') == [row]


def test_resource_context_preserves_module_scope_without_review_metadata():
    day = {'day': 1, 'lab_setup': 'mixed', 'duration_days': 2,
           'acceptance_checks': [{'evidence': 'Example only: Amazon RDS'}],
           'modules': [{'lab': 'Use AWS EC2', 'lab_setup': 'individual', 'review_warnings': ['Amazon S3']}]}
    assert resource_context(day) == {'day': 1, 'lab_setup': 'mixed', 'duration_days': 2,
                                    'modules': [{'lab': 'Use AWS EC2', 'lab_setup': 'individual'}]}
    assert 'acceptance_checks' in day


@pytest.mark.parametrize('storage,expected_put,expected_get', [(0, 0, 0), (5, 24, 84)])
def test_ai_request_counts_are_calculated_from_usage_assumptions(storage, expected_put, expected_get):
    row = resources(object_storage_gb=storage, active_days=3)
    for field in ('storage_put_requests', 'storage_get_requests'):
        row.pop(field)
    result = run_plan({'lab': 'AWS EC2', 'duration_days': 3}, row,
                      storage_put_requests_per_participant_day=2,
                      storage_get_requests_per_participant_day=7)[0]
    # Counts are per day. Duration is applied once by the cost engine.
    assert result['storage_put_requests'] == expected_put
    assert result['storage_get_requests'] == expected_get


def test_model_cannot_override_explicit_request_usage_assumptions():
    with pytest.raises(ValueError, match='conflicts with supplied usage assumptions'):
        run_plan({'lab': 'Amazon S3'}, resources(object_storage_gb=5,
                 storage_put_requests=100, storage_get_requests=200))
