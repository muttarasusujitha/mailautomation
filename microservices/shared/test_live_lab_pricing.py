import unittest
from unittest.mock import patch
from shared.live_lab_pricing import refresh_rates, _choose, PricingUnavailable, RESOURCES, automatic_pricing_selections


class LivePricingTests(unittest.TestCase):
    def inputs(self):
        return {'cloud_provider': 'aws', 'pricing_selections': {
            name: {'service': 'AmazonEC2', 'sku': name, 'rate_code': name}
            for name in RESOURCES}}

    def catalog(self, rate='0.12'):
        units = {'hour': 'Hrs', 'month': 'GB-Mo', 'gb': 'GB', 'minute': 'minutes'}
        return [({'SKU': n, 'RateCode': n, 'TermType': 'OnDemand', 'Currency': 'USD',
                  'StartingRange': '0', 'EndingRange': 'Inf', 'PricePerUnit': rate,
                  'Unit': units[u]}, 'https://pricing.us-east-1.amazonaws.com/test')
                for n, u in RESOURCES.items()]

    def test_refresh_fetches_again_and_overwrites_submitted_rates(self):
        values = self.inputs()
        values['vm_profile_rates'] = {'Light': 999, 'Heavy': 999}
        with patch('shared.live_lab_pricing._aws_catalog', side_effect=[self.catalog(), self.catalog('0.15')]) as fetch:
            first = refresh_rates(values)
            second = refresh_rates(values)
        self.assertEqual(fetch.call_count, 2)
        self.assertEqual(first['vm_profile_rates']['Light'], 0.12)
        self.assertEqual(second['vm_profile_rates']['Light'], 0.15)
        self.assertNotEqual(first['rate_snapshot_id'], second['rate_snapshot_id'])

    def test_missing_mapping_blocks_without_network(self):
        with patch('shared.live_lab_pricing._aws_catalog') as fetch:
            with self.assertRaises(PricingUnavailable):
                refresh_rates({'cloud_provider': 'aws'})
            fetch.assert_not_called()

    def test_automatic_baseline_prices_compute_and_marks_disabled_resources_not_billed(self):
        selections = automatic_pricing_selections({}, {'cloud_provider': 'aws'})
        values = {'cloud_provider': 'aws', 'pricing_selections': selections}
        catalog = self.catalog()
        compute_rows = [catalog[0], catalog[1]]
        for index, (row, _url) in enumerate(compute_rows):
            row.update({'Instance Type': 't3.medium' if index == 0 else 't3.xlarge',
                        'Operating System': 'Linux', 'Tenancy': 'Shared', 'MarketOption': 'OnDemand',
                        'CapacityStatus': 'Used', 'Pre Installed S/W': 'NA',
                        'License Model': 'No License required'})
        disk = dict(catalog[5][0])
        disk.update({'SKU': 'gp3', 'RateCode': 'gp3-hourly-capacity', 'Unit': 'GB-Mo',
                     'usageType': 'APS3-EBS:VolumeUsage.gp3'})
        compute_rows.append((disk, catalog[0][1]))
        with patch('shared.live_lab_pricing._aws_catalog', return_value=compute_rows):
            result = refresh_rates(values)
        self.assertGreater(result['rate_card_overrides']['VM']['rate'], 0)
        self.assertGreater(result['rate_card_overrides']['Disk']['rate'], 0)
        self.assertEqual(result['rate_card_overrides']['Storage']['sku'], 'NOT_BILLED')
        self.assertIn('Not enabled', result['rate_card_overrides']['Storage']['note'])

    def test_unexplained_zero_rate_is_rejected(self):
        values = self.inputs()
        values['pricing_selections']['Storage'] = {'auto_zero': True}
        with self.assertRaises(PricingUnavailable):
            refresh_rates(values)

    def test_ambiguous_rate_blocks(self):
        with patch('shared.live_lab_pricing._aws_catalog', return_value=self.catalog() * 2):
            with self.assertRaises(PricingUnavailable):
                refresh_rates(self.inputs())

    def test_tiered_rate_blocks(self):
        rows = self.catalog()
        rows[0][0]['EndingRange'] = '100'
        with patch('shared.live_lab_pricing._aws_catalog', return_value=rows):
            with self.assertRaises(PricingUnavailable):
                refresh_rates(self.inputs())

    def test_unit_mismatch_blocks(self):
        with self.assertRaises(PricingUnavailable):
            _choose([{'unit': '1 Month', 'rate': 1}], 'VM', 'hour')

    def test_outage_has_no_fallback(self):
        with patch('shared.live_lab_pricing._aws_catalog', side_effect=TimeoutError):
            with self.assertRaises(TimeoutError):
                refresh_rates(self.inputs())

    def test_attribute_selector_resolves_current_dimension(self):
        values = self.inputs()
        values['pricing_selections']['VM'] = {
            'service': 'AmazonEC2',
            'attributes': {'Instance Type': 't3.medium', 'Operating System': 'Linux'},
        }
        rows = self.catalog()
        vm = rows[0][0]
        vm.update({'Instance Type': 't3.medium', 'Operating System': 'Linux'})
        # A reservation dimension on the same product cannot make the hourly
        # rate ambiguous.
        reserved = dict(vm)
        reserved.update({'RateCode': 'reservation', 'TermType': 'Reserved', 'Unit': 'Hrs', 'PricePerUnit': '12'})
        with patch('shared.live_lab_pricing._aws_catalog', return_value=rows + [(reserved, rows[0][1])]):
            result = refresh_rates(values)
        self.assertEqual(result['rate_card_overrides']['VM']['rate'], 0.12)

if __name__ == '__main__':
    unittest.main()
