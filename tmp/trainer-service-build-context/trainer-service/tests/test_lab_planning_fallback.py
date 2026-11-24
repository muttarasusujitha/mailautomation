import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException
from app.routes import toc_extended as route


def test_optional_metered_usage_defaults_to_zero_until_the_scope_requires_it():
    payload = route.LabCostRequest()
    assert (payload.egress_gb, payload.build_minutes, payload.monitoring_gb) == (0, 0, 0)


def test_additional_meter_usage_is_accepted_and_forwarded_to_document_service(monkeypatch):
    import asyncio
    from unittest.mock import AsyncMock
    from types import SimpleNamespace

    payload = route.LabCostRequest(
        toc={'domain': 'AWS Lambda', 'days': [{'topic': 'AWS Lambda'}]},
        cloud_provider='aws', cloud_region='ap-south-1', participant_count=1,
        pricing_selections={'Lambda invocations': {'unit_key': 'request'}},
        additional_resource_usage={'Lambda invocations': 1000},
        lab_generation_mode='template', lab_day_mapping=[{
            'vm_qty': 0, 'vm_profile': 'None', 'k8s_control_plane': 0,
            'k8s_worker_nodes': 0, 'managed_db': 0, 'object_storage_gb': 0,
            'active_days': 1,
        }],
    )
    response = SimpleNamespace(status_code=200, content=b'workbook', headers={
        'X-Lab-Cost-Quote-ID': 'test-quote',
        'X-Lab-Cost-Quote-Valid-Until': '2026-10-01T00:00:00+00:00',
        'X-Lab-Cost-Pricing-Status': 'live_verified',
    })
    client = SimpleNamespace(post=AsyncMock(return_value=response))
    async_client = MagicMock()
    async_client.__aenter__ = AsyncMock(return_value=client)
    async_client.__aexit__ = AsyncMock(return_value=False)
    monkeypatch.setattr(route.httpx, 'AsyncClient', lambda **kwargs: async_client)
    db = {'lab_cost_quotes': SimpleNamespace(insert_one=AsyncMock())}
    result = asyncio.run(route.generate_toc_lab_cost(payload, db))
    assert result.body == b'workbook'
    assumptions = client.post.await_args.kwargs['json']['assumptions']
    assert assumptions['additional_resource_usage'] == {'Lambda invocations': 1000}


@pytest.mark.parametrize('mode', ['ai', None])
@pytest.mark.parametrize('failure', [RuntimeError('credit_balance_exhausted'), ValueError('Invalid AI resource mapping')])
def test_ai_failure_uses_template_and_reaches_document_service(monkeypatch, failure, mode):
    import openai
    planner = MagicMock()
    planner.__aenter__ = AsyncMock(return_value=planner)
    planner.__aexit__ = AsyncMock(return_value=False)
    planner.responses.create = AsyncMock(side_effect=failure)
    monkeypatch.setattr(openai, 'AsyncOpenAI', lambda **kwargs: planner, raising=False)

    response = SimpleNamespace(status_code=200, content=b'workbook', headers={
        'X-Lab-Cost-Quote-ID': 'test-quote',
        'X-Lab-Cost-Quote-Valid-Until': '2026-10-01T00:00:00+00:00',
        'X-Lab-Cost-Pricing-Status': 'live_verified',
    })
    document = MagicMock()
    document.__aenter__ = AsyncMock(return_value=document)
    document.__aexit__ = AsyncMock(return_value=False)
    document.post = AsyncMock(return_value=response)
    monkeypatch.setattr(route.httpx, 'AsyncClient', lambda **kwargs: document)
    db = {'lab_cost_quotes': SimpleNamespace(insert_one=AsyncMock())}
    payload = route.LabCostRequest(toc={'domain': 'Linux', 'days': [{'lab': 'Linux shell'}]},
        lab_generation_mode=mode, cloud_provider='aws', cloud_region='ap-south-1', participant_count=20,
        lab_day_setups=['individual'], local_costs_status='covered', license_costs_status='not_required')
    result = asyncio.run(route.generate_toc_lab_cost(payload, db))
    assert result.body == b'workbook'
    assumptions = document.post.call_args.kwargs['json']['assumptions']
    assert assumptions['lab_generation_mode'] == 'template'
    assert assumptions['lab_day_mapping'][0]['vm_qty'] == 20
    assert assumptions['lab_day_setups'] == ['individual']
    assert assumptions['local_costs_status'] == 'covered'
    assert assumptions['license_costs_status'] == 'not_required'
    db['lab_cost_quotes'].insert_one.assert_awaited_once()


def test_invalid_manual_mapping_still_requires_correction():
    payload = route.LabCostRequest(toc={'days': [{'lab': 'Linux'}]},
        lab_generation_mode='manual', lab_day_mapping=[], cloud_provider='aws',
        cloud_region='ap-south-1', participant_count=20)
    with pytest.raises(HTTPException) as error:
        asyncio.run(route.generate_toc_lab_cost(payload, {}))
    assert error.value.status_code == 422


@pytest.mark.parametrize('underallocated', [False, True])
def test_ollama_lab_mode_uses_selected_provider_and_validates_sizing(monkeypatch, underallocated):
    import json
    import openai
    from app import ollama_client

    monkeypatch.setattr(route.settings, 'AI_PROVIDER', 'ollama')
    monkeypatch.setattr(route.settings, 'OLLAMA_MODEL', 'selected-local-model')
    row = dict(vm_qty=1 if underallocated else 12, vm_profile='Light',
               k8s_control_plane=0, k8s_worker_nodes=0, managed_db=0,
               object_storage_gb=0, storage_put_requests=0, storage_get_requests=0, active_days=1)
    create = AsyncMock(return_value=SimpleNamespace(output_text=json.dumps({'days': [row]})))
    monkeypatch.setattr(ollama_client, 'OllamaClient', lambda *args, **kwargs:
                        SimpleNamespace(responses=SimpleNamespace(create=create)))
    openai_factory = MagicMock(side_effect=AssertionError('Ollama mode must not call OpenAI'))
    monkeypatch.setattr(openai, 'AsyncOpenAI', openai_factory, raising=False)
    response = SimpleNamespace(status_code=200, content=b'workbook', headers={
        'X-Lab-Cost-Quote-ID': 'test-quote',
        'X-Lab-Cost-Quote-Valid-Until': '2026-10-01T00:00:00+00:00',
        'X-Lab-Cost-Pricing-Status': 'live_verified',
    })
    document = MagicMock()
    document.__aenter__ = AsyncMock(return_value=document)
    document.__aexit__ = AsyncMock(return_value=False)
    document.post = AsyncMock(return_value=response)
    monkeypatch.setattr(route.httpx, 'AsyncClient', lambda **kwargs: document)
    payload = route.LabCostRequest(toc={'days': [{'lab': 'Provision AWS EC2'}]},
        lab_generation_mode='ai', lab_setup='individual', cloud_provider='aws',
        cloud_region='ap-south-1', participant_count=12)
    asyncio.run(route.generate_toc_lab_cost(payload, {'lab_cost_quotes': SimpleNamespace(insert_one=AsyncMock())}))
    create.assert_awaited_once()
    openai_factory.assert_not_called()
    assert create.await_args.kwargs['model'] == 'selected-local-model'
    assert create.await_args.kwargs['native_schema'] is True
    assumptions = document.post.await_args.kwargs['json']['assumptions']
    assert assumptions['lab_generation_mode'] == ('template' if underallocated else 'ai')
    assert assumptions['lab_day_mapping'][0]['vm_qty'] == 12


def test_omitted_mode_does_not_relabel_automatic_mapping_as_manual(monkeypatch):
    response = SimpleNamespace(status_code=200, content=b'workbook', headers={
        'X-Lab-Cost-Quote-ID': 'test-quote',
        'X-Lab-Cost-Quote-Valid-Until': '2026-10-01T00:00:00+00:00',
        'X-Lab-Cost-Pricing-Status': 'live_verified',
    })
    document = MagicMock()
    document.__aenter__ = AsyncMock(return_value=document)
    document.__aexit__ = AsyncMock(return_value=False)
    document.post = AsyncMock(return_value=response)
    monkeypatch.setattr(route.httpx, 'AsyncClient', lambda **kwargs: document)
    db = {'lab_cost_quotes': SimpleNamespace(insert_one=AsyncMock())}
    payload = route.LabCostRequest(
        toc={'days': [{'lab': 'Linux shell'}]}, cloud_provider='aws',
        cloud_region='ap-south-1', participant_count=2,
    )

    result = asyncio.run(route.generate_toc_lab_cost(payload, db))

    assert result.body == b'workbook'
    assumptions = document.post.call_args.kwargs['json']['assumptions']
    assert assumptions['lab_generation_mode'] == 'template'
    assert assumptions['lab_day_mapping'][0]['vm_qty'] == 2


def test_local_delivery_zeros_default_cloud_usage(monkeypatch):
    response = SimpleNamespace(status_code=200, content=b'workbook', headers={
        'X-Lab-Cost-Quote-ID': 'test-quote',
        'X-Lab-Cost-Quote-Valid-Until': '2026-10-01T00:00:00+00:00',
        'X-Lab-Cost-Pricing-Status': 'live_verified',
    })
    document = MagicMock()
    document.__aenter__ = AsyncMock(return_value=document)
    document.__aexit__ = AsyncMock(return_value=False)
    document.post = AsyncMock(return_value=response)
    monkeypatch.setattr(route.httpx, 'AsyncClient', lambda **kwargs: document)
    db = {'lab_cost_quotes': SimpleNamespace(insert_one=AsyncMock())}
    payload = route.LabCostRequest(
        toc={'days': [{'lab': 'Linux shell practice on AWS'}]},
        lab_generation_mode='template', lab_setup='local', cloud_provider='aws',
        cloud_region='ap-south-1', participant_count=2,
    )
    asyncio.run(route.generate_toc_lab_cost(payload, db))
    request = document.post.call_args.kwargs['json']
    assumptions = request['assumptions']
    assert request['toc']['days'][0]['lab_setup'] == 'local'
    assert {key: assumptions[key] for key in ('storage_gb', 'egress_gb', 'build_minutes', 'monitoring_gb', 'k8s_worker_nodes')} == {
        'storage_gb': 0, 'egress_gb': 0, 'build_minutes': 0, 'monitoring_gb': 0, 'k8s_worker_nodes': 0,
    }
