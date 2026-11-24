import unittest

from shared.ai_pricing import resolve_ai_cost


class AIPricingTests(unittest.TestCase):
    def test_exact_approved_evidence_calculates_cost(self):
        result = resolve_ai_cost(
            {'provider': 'OpenAI', 'model': 'example-model', 'input_tokens': 2_000_000,
             'output_tokens': 500_000, 'gpu_hours': 1},
            [{'provider': 'openai', 'model': 'example-model', 'approved': True,
              'input_per_million': 2, 'output_per_million': 8, 'gpu_per_hour': 3,
              'source_url': 'https://example.com/pricing', 'effective_date': '2026-01-01'}])
        self.assertEqual(result['status'], 'rag_manual_approved')
        self.assertEqual(result['total_usd'], 11)

    def test_unapproved_or_missing_evidence_never_invents_price(self):
        result = resolve_ai_cost({'provider': 'openai', 'model': 'x'},
                                 [{'provider': 'openai', 'model': 'x', 'approved': False}])
        self.assertEqual(result['status'], 'ai_pricing_missing')
        self.assertIsNone(result['total_usd'])


if __name__ == '__main__':
    unittest.main()
