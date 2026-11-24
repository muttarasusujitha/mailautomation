import asyncio
import json
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock
from shared.lab_planning import local_only_delivery, plan_resources, validate_mapping


class PlanningTests(unittest.TestCase):
    def setUp(self):
        self.row = dict(vm_qty=20, vm_profile='Heavy', k8s_control_plane=0,
                        k8s_worker_nodes=0, managed_db=0, object_storage_gb=0,
                        storage_put_requests=0, storage_get_requests=0, active_days=1)

    def test_manual_preserves_quantities_without_calling_llm(self):
        client = SimpleNamespace(responses=SimpleNamespace(create=AsyncMock()))
        result = asyncio.run(plan_resources('manual', {'days': [{}]},
                                           {'lab_day_mapping': [self.row]}, client))
        self.assertEqual(result, [self.row])
        client.responses.create.assert_not_called()

    def test_ai_result_is_validated(self):
        client = SimpleNamespace(responses=SimpleNamespace(create=AsyncMock(
            return_value=SimpleNamespace(output_text=json.dumps({'days': [self.row]})))))
        result = asyncio.run(plan_resources('ai', {'days': [{}]},
            dict(participant_count=20, cloud_provider='aws', hours_per_day=4), client, 'test'))
        self.assertEqual(result, [self.row])
        client.responses.create.assert_awaited_once()

    def test_template_fallback_maps_cloud_and_local_days_without_ai(self):
        client = SimpleNamespace(responses=SimpleNamespace(create=AsyncMock()))
        result = asyncio.run(plan_resources('template', {'days': [
            {'lab': 'Linux shell practice on AWS'},
            {'lab': 'Docker Desktop on local machine'},
        ]}, dict(participant_count=20, cloud_provider='aws', hours_per_day=4), client))
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0]['vm_qty'], 20)
        self.assertEqual(result[1]['vm_qty'], 0)
        self.assertEqual(result[1]['vm_profile'], 'None')
        client.responses.create.assert_not_called()

    def test_missing_days_and_formula_quantities_are_rejected(self):
        with self.assertRaises(ValueError):
            validate_mapping([], 1)
        with self.assertRaises(ValueError):
            validate_mapping([dict(self.row, vm_qty='=20*2')], 1)

    def test_model_cannot_supply_rates(self):
        with self.assertRaises(ValueError):
            validate_mapping([dict(self.row, rate=0.01)], 1)

    def test_request_local_setup_overrides_cloud_keywords_without_mutation(self):
        toc = {'days': [{'lab': 'Linux on AWS'}]}
        result = asyncio.run(plan_resources('template', toc, {'participant_count': 20, 'lab_setup': 'local'}))
        self.assertEqual(result[0]['vm_qty'], 0)
        self.assertNotIn('lab_setup', toc['days'][0])

    def test_local_delivery_is_detected_from_request_setup(self):
        toc = {'days': [{'lab': 'Linux shell practice on AWS'}]}
        planned, is_local = local_only_delivery(toc, {'lab_setup': 'local'})
        self.assertTrue(is_local)
        self.assertEqual(planned['days'][0]['lab_setup'], 'local')
        self.assertNotIn('lab_setup', toc['days'][0])

    def test_local_manual_cloud_mapping_is_rejected(self):
        with self.assertRaisesRegex(ValueError, 'local-only'):
            asyncio.run(plan_resources('manual', {'days': [{'lab': 'Linux'}]},
                {'lab_setup': 'local', 'lab_day_mapping': [self.row]}))

    def test_empty_course_and_incomplete_setup_list_are_rejected(self):
        for toc, assumptions in [({'days': []}, {}),
                ({'days': [{}, {}]}, {'lab_day_setups': ['local']})]:
            with self.assertRaises(ValueError):
                asyncio.run(plan_resources('template', toc, assumptions))
