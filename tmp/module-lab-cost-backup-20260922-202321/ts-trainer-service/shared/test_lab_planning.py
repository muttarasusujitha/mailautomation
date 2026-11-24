import asyncio
import json
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock
from shared.lab_planning import plan_resources, validate_mapping


class PlanningTests(unittest.TestCase):
    def setUp(self):
        self.row = dict(vm_qty=20, vm_profile='Heavy', k8s_control_plane=0,
                        k8s_worker_nodes=0, managed_db=0, object_storage_gb=0, active_days=1)

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
