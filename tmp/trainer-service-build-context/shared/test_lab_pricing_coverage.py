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


def test_generic_vm_word_does_not_create_azure_provider_mismatch_for_aws():
    from shared.lab_architecture import architecture_summary
    toc = {'days': [{'topic': 'AWS EC2 Linux VM lab'}]}
    summary = architecture_summary(toc, 'aws')
    assert 'provider mismatch: Azure Virtual Machines requires its matching cloud provider' not in summary['unpriced_services']
    assert 'Amazon EC2' in summary['days'][0]['services']


def test_azure_selected_provider_can_map_unqualified_virtual_machines():
    from shared.lab_architecture import architecture_summary
    summary = architecture_summary({'days': [{'topic': 'Virtual Machines lab'}]}, 'azure')
    assert 'Azure Virtual Machines' in summary['days'][0]['services']


def test_rds_does_not_get_misclassified_as_aurora_or_azure_postgres():
    from shared.lab_architecture import architecture_summary
    toc = {'days': [{'topic': 'Terraform AWS', 'lab_task': 'Provision EC2 and RDS'}]}
    aws = architecture_summary(toc, 'aws')
    azure = architecture_summary(toc, 'azure')
    assert 'Amazon Aurora' not in aws['unpriced_services']
    assert 'Azure Database for PostgreSQL/MySQL' not in azure['unpriced_services']


def test_generic_api_gateway_pattern_does_not_require_cloud_meter():
    from shared.lab_architecture import architecture_summary
    result = architecture_summary({'days': [{
        'topic': 'Microservices with Spring Cloud',
        'subtopics': ['API Gateway Pattern', 'Service Discovery'],
    }]}, 'aws')
    assert 'Amazon API Gateway' not in result['unpriced_services']


def test_generic_monitoring_and_rabbitmq_do_not_create_aws_meter_requirements():
    from shared.lab_architecture import architecture_summary
    for topic in (
        {'topic': 'Monitoring - Prometheus & Grafana',
         'lab_task': 'Set up cluster monitoring with dashboards and alerts'},
        {'topic': 'Microservices with Python', 'tools': ['RabbitMQ'],
         'lab_task': 'Build services using a message queue'},
    ):
        result = architecture_summary({'days': [topic]}, 'aws')
        assert 'Amazon CloudWatch' not in result['unpriced_services']
        assert 'Amazon SQS/SNS' not in result['unpriced_services']


def test_aws_networking_topic_does_not_infer_azure_dns_or_load_balancer():
    from shared.lab_architecture import architecture_summary
    topic = {'topic': 'Networking in AWS', 'tools': ['VPC', 'Route 53'],
             'subtopics': ['Load Balancers', 'DNS']}
    result = architecture_summary({'days': [topic]}, 'azure')
    assert 'Azure DNS' not in result['unpriced_services']
    assert 'Azure Load Balancer' not in result['unpriced_services']


def test_provider_name_alone_does_not_require_every_service_meter():
    from shared.live_lab_pricing import RESOURCES
    toc = {'days': [{'topic': 'AWS EC2 Linux VM lab'}]}
    mapping = default_cloud_mapping(toc, {'participant_count': 1, 'cloud_provider': 'aws'})
    selections = {name: {'auto_zero': True, 'not_enabled_reason': 'not used'} for name in RESOURCES}
    selections['VM Light'] = {'sku': 'configured'}
    selections['Disk'] = {'sku': 'configured'}
    validate_lab_pricing_coverage(toc, {
        'cloud_provider': 'aws', 'lab_day_mapping': mapping,
        'pricing_selections': selections,
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


def test_generic_kubernetes_maps_to_local_worker_cluster():
    from shared.lab_architecture import architecture_summary
    toc = {'days': [{'topic': 'Kubernetes fundamentals and kubectl practice'}]}
    mapping = default_cloud_mapping(toc, {'participant_count': 8, 'cloud_provider': 'aws'})
    assert mapping[0]['vm_qty'] == 8
    assert mapping[0]['k8s_control_plane'] == 0
    assert mapping[0]['k8s_worker_nodes'] == 0
    assert 'local Kubernetes cluster' in architecture_summary(toc, 'aws')['days'][0]['plan']


def test_architecture_summary_carries_tools_and_hands_on_experiment():
    from shared.lab_architecture import architecture_summary
    summary = architecture_summary({'days': [{
        'topic': 'Kubernetes Fundamentals',
        'tools': ['kubectl', 'minikube', 'k9s'],
        'lab_task': 'Deploy a microservices app with Ingress',
    }]}, 'aws')
    day = summary['days'][0]
    assert day['tools'] == ['kubectl', 'minikube', 'k9s']
    assert day['experiment'] == 'Deploy a microservices app with Ingress'
    assert 'local Minikube/Kind cluster' in day['plan']


def test_ambiguous_cloud_capstone_is_blocked_until_services_are_named():
    toc = {'days': [{'topic': 'Cloud Capstone Project',
                     'tools': ['All Cloud Tools'], 'lab_task': 'Deploy a cloud solution'}]}
    mapping = default_cloud_mapping(toc, {'participant_count': 2, 'cloud_provider': 'aws'})
    with pytest.raises(ValueError, match='specify provider, named services, and resource quantities'):
        validate_lab_pricing_coverage(toc, {
            'cloud_provider': 'aws', 'lab_day_mapping': mapping,
            'pricing_selections': {}, 'egress_gb': 0, 'build_minutes': 0,
            'monitoring_gb': 0,
        })


def test_additional_meter_components_can_cover_an_unsupported_service_explicitly():
    from shared.live_lab_pricing import RESOURCES
    toc = {'days': [{'topic': 'AWS Lambda hands-on'}]}
    mapping = [{'vm_qty': 0, 'vm_profile': 'None', 'k8s_control_plane': 0,
                'k8s_worker_nodes': 0, 'managed_db': 0, 'object_storage_gb': 0,
                'storage_put_requests': 0, 'storage_get_requests': 0, 'active_days': 1}]
    selections = {name: {'auto_zero': True, 'not_enabled_reason': 'not used'}
                  for name in RESOURCES}
    selections.update({
        'Lambda invocations': {'unit_key': 'request', 'covers_services': ['AWS Lambda'],
                               'service': 'AWSLambda', 'attributes': {'usageType': 'APS3-Lambda-Requests'}},
        'Lambda GB-seconds': {'unit_key': 'GB-Second', 'covers_services': ['AWS Lambda'],
                              'service': 'AWSLambda', 'attributes': {'usageType': 'APS3-Lambda-GB-Second'}},
    })
    validate_lab_pricing_coverage(toc, {
        'cloud_provider': 'aws', 'lab_day_mapping': mapping, 'pricing_selections': selections,
        'additional_resource_usage': {'Lambda invocations': 1000, 'Lambda GB-seconds': 64},
        'egress_gb': 0, 'build_minutes': 0, 'monitoring_gb': 0,
    })


def test_saved_meter_for_unused_service_does_not_block_other_topic():
    from shared.live_lab_pricing import RESOURCES
    toc = {'days': [{'topic': 'AWS EC2 Linux VM lab'}]}
    mapping = default_cloud_mapping(toc, {'participant_count': 1, 'cloud_provider': 'aws'})
    selections = {name: {'sku': 'configured'} for name in RESOURCES}
    selections.update({
        'Lambda invocations': {'unit_key': 'Request', 'covers_services': ['AWS Lambda'], 'service': 'AWSLambda',
                               'attributes': {'usageType': 'APS3-Request'}},
        'Lambda GB-seconds': {'unit_key': 'Lambda-GB-Second', 'covers_services': ['AWS Lambda'],
                              'service': 'AWSLambda', 'attributes': {'usageType': 'APS3-Lambda-GB-Second'}},
    })
    validate_lab_pricing_coverage(toc, {
        'cloud_provider': 'aws', 'lab_day_mapping': mapping, 'pricing_selections': selections,
        'egress_gb': 0, 'build_minutes': 0, 'monitoring_gb': 0,
    })


def test_live_pricing_blocks_missing_or_zero_required_service_meter_usage():
    from shared.live_lab_pricing import RESOURCES, PricingUnavailable, refresh_rates
    values = {'cloud_provider': 'aws', 'toc': {'days': [{'topic': 'AWS Lambda hands-on'}]},
              'pricing_selections': {name: {'auto_zero': True, 'not_enabled_reason': 'not used'}
                                     for name in RESOURCES}}
    values['pricing_selections'].update({
        'Lambda invocations': {'unit_key': 'request', 'service': 'AWSLambda',
                               'attributes': {'usageType': 'APS3-Lambda-Requests'}},
        'Lambda GB-seconds': {'unit_key': 'GB-Second', 'service': 'AWSLambda',
                              'attributes': {'usageType': 'APS3-Lambda-GB-Second'}},
    })
    with pytest.raises(PricingUnavailable, match='supply quantities'):
        refresh_rates({**values, 'additional_resource_usage': {'Lambda invocations': 1000}})
    with pytest.raises(PricingUnavailable, match='positive billed usage'):
        refresh_rates({**values, 'additional_resource_usage': {
            'Lambda invocations': 1000, 'Lambda GB-seconds': 0,
        }})


def test_live_pricing_requires_meter_selectors_for_every_named_catalog_service():
    from shared.live_lab_pricing import RESOURCES, PricingUnavailable, refresh_rates
    values = {
        'cloud_provider': 'aws',
        'toc': {'days': [{'topic': 'AWS serverless', 'tools': ['Lambda'],
                         'lab_task': 'Build Lambda with Step Functions'}]},
        'lab_day_mapping': [{'vm_qty': 1, 'vm_profile': 'Light', 'k8s_control_plane': 0,
                             'k8s_worker_nodes': 0, 'managed_db': 0, 'object_storage_gb': 0,
                             'active_days': 1}],
        'pricing_selections': {name: {'auto_zero': True, 'not_enabled_reason': 'not used'}
                               for name in RESOURCES},
    }
    with pytest.raises(PricingUnavailable, match='configure pricing selectors'):
        refresh_rates(values)


def test_explicit_eks_and_aks_map_paid_cluster_control_planes():
    from shared.lab_architecture import architecture_summary
    from shared.live_lab_pricing import automatic_pricing_selections
    for provider, title in (('aws', 'Amazon EKS'), ('azure', 'Azure Kubernetes Service AKS')):
        toc = {'days': [{'topic': f'{title} cluster deployment'}]}
        mapping = default_cloud_mapping(toc, {'participant_count': 3, 'cloud_provider': provider})
        assert mapping[0]['k8s_control_plane'] == 1
        assert mapping[0]['k8s_worker_nodes'] == 1
        selections = automatic_pricing_selections(toc, {
            'cloud_provider': provider, 'lab_day_mapping': mapping,
        })
        if provider == 'aws':
            assert selections['Kubernetes control plane']['service'] == 'AmazonEKS'
        else:
            assert selections['Kubernetes control plane']['auto_zero'] is True
        assert 'managed cluster' in architecture_summary(toc, provider)['days'][0]['plan']


def test_gke_maps_to_shared_gcp_cluster_and_preserves_topic_tools():
    from shared.lab_architecture import architecture_summary
    toc = {'days': [{'topic': 'GCP Core Services', 'tools': ['gcloud CLI'],
                     'lab_task': 'Deploy a sample workload on GCP with GKE'}]}
    mapping = default_cloud_mapping(toc, {'participant_count': 4, 'cloud_provider': 'gcp'})
    assert mapping[0]['k8s_control_plane'] == 1
    assert mapping[0]['k8s_worker_nodes'] == 1
    summary = architecture_summary(toc, 'gcp')['days'][0]
    assert 'GKE control plane plus worker nodes' in summary['plan']
    assert summary['tools'] == ['gcloud CLI']


def test_named_database_or_blob_cannot_be_hidden_by_another_mapped_resource():
    from shared.live_lab_pricing import RESOURCES
    for topic, field in (
        ('Amazon Aurora PostgreSQL', 'managed_db'),
        ('Azure Database for PostgreSQL', 'managed_db'),
        ('Azure Blob', 'object_storage_gb'),
    ):
        mapping = {'vm_qty': 2, 'vm_profile': 'Light', 'k8s_control_plane': 0,
                   'k8s_worker_nodes': 0, 'managed_db': 0, 'object_storage_gb': 0,
                   'active_days': 1}
        selections = {name: {'sku': 'configured'} for name in RESOURCES}
        selections['Managed database'] = {'sku': 'configured'}
        selections['Storage'] = {'sku': 'configured'}
        with pytest.raises(ValueError, match='explicitly named cloud service|supported metered cost model'):
            validate_lab_pricing_coverage(
                {'days': [{'topic': topic}]},
                {'cloud_provider': 'azure' if topic.startswith('Azure') else 'aws',
                 'lab_day_mapping': [mapping], 'pricing_selections': selections,
                 'egress_gb': 0, 'build_minutes': 0, 'monitoring_gb': 0},
            )


def test_named_eks_cannot_hide_missing_worker_nodes_behind_a_control_plane():
    from shared.live_lab_pricing import RESOURCES
    mapping = {'vm_qty': 2, 'vm_profile': 'Heavy', 'k8s_control_plane': 1,
               'k8s_worker_nodes': 0, 'managed_db': 0, 'object_storage_gb': 0,
               'active_days': 1}
    selections = {name: {'sku': 'configured'} for name in RESOURCES}
    with pytest.raises(ValueError, match='explicitly named cloud service'):
        validate_lab_pricing_coverage(
            {'days': [{'topic': 'Amazon EKS cluster lab'}]},
            {'cloud_provider': 'aws', 'lab_day_mapping': [mapping],
             'pricing_selections': selections, 'egress_gb': 0,
             'build_minutes': 0, 'monitoring_gb': 0},
        )


def test_database_quote_requires_metered_database_storage():
    from shared.live_lab_pricing import RESOURCES
    mapping = {'vm_qty': 0, 'vm_profile': 'None', 'k8s_control_plane': 0,
               'k8s_worker_nodes': 0, 'managed_db': 1, 'object_storage_gb': 0,
               'active_days': 1}
    selections = {name: {'sku': 'configured'} for name in RESOURCES}
    selections.pop('Managed database storage')
    with pytest.raises(ValueError, match='Managed database storage'):
        validate_lab_pricing_coverage(
            {'days': [{'topic': 'Amazon RDS MySQL'}]},
            {'cloud_provider': 'aws', 'lab_day_mapping': [mapping],
             'pricing_selections': selections, 'egress_gb': 0,
             'build_minutes': 0, 'monitoring_gb': 0},
        )


def test_object_storage_mapping_requires_request_quantities():
    from shared.live_lab_pricing import RESOURCES
    mapping = {'vm_qty': 0, 'vm_profile': 'None', 'k8s_control_plane': 0,
               'k8s_worker_nodes': 0, 'managed_db': 0, 'object_storage_gb': 25,
               'active_days': 1}
    selections = {name: {'sku': 'configured'} for name in RESOURCES}
    mapping.update(storage_put_requests=25, storage_get_requests=250)
    validate_lab_pricing_coverage(
            {'days': [{'topic': 'Azure Blob Storage'}]},
            {'cloud_provider': 'azure', 'lab_day_mapping': [mapping],
             'pricing_selections': selections, 'egress_gb': 0,
             'build_minutes': 0, 'monitoring_gb': 0},
        )
