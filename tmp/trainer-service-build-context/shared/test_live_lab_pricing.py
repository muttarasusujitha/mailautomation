import unittest
from unittest.mock import patch
import pytest
from shared.live_lab_pricing import refresh_rates, _choose, PricingUnavailable, RESOURCES, automatic_pricing_selections


class LivePricingTests(unittest.TestCase):
    def inputs(self):
        return {'cloud_provider': 'aws', 'pricing_selections': {
            name: {'service': 'AmazonEC2', 'sku': name, 'rate_code': name}
            for name in RESOURCES}}

    def catalog(self, rate='0.12'):
        units = {'hour': 'Hrs', 'month': 'GB-Mo', 'gb': 'GB', 'minute': 'minutes', 'request': 'Requests'}
        return [({'SKU': n, 'RateCode': n, 'TermType': 'OnDemand', 'Currency': 'USD',
                  'StartingRange': '0', 'EndingRange': 'Inf', 'PricePerUnit': rate,
                  'Unit': units[u]}, 'https://pricing.us-east-1.amazonaws.com/test')
                for n, u in RESOURCES.items()]

    def test_provider_hardware_metadata_is_retained_with_rate(self):
        rows = self.catalog()
        for row, _ in rows:
            row.update({'Instance Type': 'test.small', 'vCPU': '2', 'Memory': '4 GiB',
                        'Operating System': 'Linux'})
        with patch('shared.live_lab_pricing._aws_catalog', return_value=rows):
            result = refresh_rates(self.inputs())
        spec = result['rate_card_overrides']['VM Light']['specifications']
        self.assertEqual(spec, {'instance_type': 'test.small', 'vcpu': '2', 'memory': '4 GiB', 'os': 'Linux'})

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

    def test_explicit_meter_can_use_bounded_first_tier_below_ceiling(self):
        values = self.inputs()
        values['pricing_selections']['Lambda GB-seconds'] = {
            'unit_key': 'Lambda-GB-Second', 'service': 'AWSLambda',
            'attributes': {'usageType': 'APS3-Lambda-GB-Second'},
            'first_tier_only': True,
        }
        values['additional_resource_usage'] = {'Lambda GB-seconds': 999}
        row = {'SKU': 'lambda', 'RateCode': 'lambda-rate', 'TermType': 'OnDemand',
               'Currency': 'USD', 'StartingRange': '0', 'EndingRange': '1000',
               'PricePerUnit': '0.00001', 'Unit': 'Lambda-GB-Second',
               'usageType': 'APS3-Lambda-GB-Second'}
        def catalog(service, _region):
            return [(row, 'https://pricing.example/lambda.csv')] if service == 'AWSLambda' else self.catalog()
        with patch('shared.live_lab_pricing._aws_catalog', side_effect=catalog):
            result = refresh_rates(values)
        rate = result['rate_card_overrides']['Lambda GB-seconds']
        self.assertEqual(rate['rate'], 0.00001)
        self.assertIn('below 1000 Lambda-GB-Second', rate['note'])

    def test_explicit_meter_first_tier_blocks_at_ceiling(self):
        values = self.inputs()
        values['pricing_selections']['Lambda GB-seconds'] = {
            'unit_key': 'Lambda-GB-Second', 'service': 'AWSLambda',
            'attributes': {'usageType': 'APS3-Lambda-GB-Second'},
            'first_tier_only': True,
        }
        values['additional_resource_usage'] = {'Lambda GB-seconds': 1000}
        row = {'SKU': 'lambda', 'RateCode': 'lambda-rate', 'TermType': 'OnDemand',
               'Currency': 'USD', 'StartingRange': '0', 'EndingRange': '1000',
               'PricePerUnit': '0.00001', 'Unit': 'Lambda-GB-Second',
               'usageType': 'APS3-Lambda-GB-Second'}
        def catalog(service, _region):
            return [(row, 'https://pricing.example/lambda.csv')] if service == 'AWSLambda' else self.catalog()
        with patch('shared.live_lab_pricing._aws_catalog', side_effect=catalog):
            with self.assertRaisesRegex(PricingUnavailable, 'first-tier ceiling'):
                refresh_rates(values)

    def test_unused_saved_service_meter_defaults_to_zero_for_quote(self):
        values = self.inputs()
        values['pricing_selections']['Lambda invocations'] = {
            'unit_key': 'Request', 'service': 'AWSLambda',
            'attributes': {'usageType': 'APS3-Request'},
            'covers_services': ['AWS Lambda'],
        }
        row = {'SKU': 'lambda-request', 'RateCode': 'lambda-request-rate',
               'TermType': 'OnDemand', 'Currency': 'USD', 'StartingRange': '0',
               'EndingRange': 'Inf', 'PricePerUnit': '0.0000002', 'Unit': 'Request',
               'usageType': 'APS3-Request'}
        def catalog(service, _region):
            return [(row, 'https://pricing.example/lambda.csv')] if service == 'AWSLambda' else self.catalog()
        with patch('shared.live_lab_pricing._aws_catalog', side_effect=catalog):
            result = refresh_rates(values)
        self.assertEqual(result['additional_resource_usage']['Lambda invocations'], 0)
        self.assertEqual(result['rate_card_overrides']['Lambda invocations']['rate'], 0.0000002)

    def test_unit_mismatch_blocks(self):
        with self.assertRaises(PricingUnavailable):
            _choose([{'unit': '1 Month', 'rate': 1}], 'VM', 'hour')

    def test_azure_fixed_disk_preserves_full_disk_price(self):
        selections = automatic_pricing_selections({}, {'cloud_provider': 'azure'})
        selections['Disk'] = {'meter_id': 'ed9e91d2-0f0c-4d55-b3dd-7f69d4708b22'}
        def lookup(selection, region, values=None):
            disk = selection == selections['Disk']
            return [{'rate': 6.4 if disk else .1, 'unit': '1/Month' if disk else '1 Hour',
                     'sku': 'test', 'dimension': 'test', 'source': 'https://prices.azure.com', 'effective_date': ''}]
        values = {'cloud_provider': 'azure', 'pricing_selections': selections}
        with patch('shared.live_lab_pricing._azure', side_effect=lookup):
            result = refresh_rates(values)
            self.assertEqual(result['disk_gb_per_node'], 32)
            self.assertAlmostEqual(result['rate_card_overrides']['Disk']['rate'] * 32, 6.4)
            values['disk_gb_per_node'] = 20
            with self.assertRaises(PricingUnavailable):
                refresh_rates(values)

    def test_azure_blob_automatic_meter_uses_current_bounded_first_tier(self):
        import io, json
        from shared.live_lab_pricing import _azure
        selections = automatic_pricing_selections({}, {
            'cloud_provider': 'azure',
            'lab_day_mapping': [{'object_storage_gb': 25}],
        })
        blob = selections['Storage']
        self.assertTrue(blob['first_tier_only'])
        items = []
        for tier, price in ((0, .02), (51200, .0192), (512000, .0184)):
            items.append({
                'currencyCode': 'USD', 'armRegionName': 'centralindia',
                'type': 'Consumption', 'meterId': blob['meter_id'],
                'productName': blob['product_name'], 'meterName': blob['meter_name'],
                'effectiveStartDate': '2026-01-01T00:00:00Z',
                'tierMinimumUnits': tier, 'retailPrice': price,
                'unitOfMeasure': '1 GB/Month', 'skuId': f'tier-{tier}',
            })
        from unittest.mock import patch
        with patch('shared.live_lab_pricing.urlopen', return_value=io.BytesIO(
                json.dumps({'Items': items, 'NextPageLink': None}).encode())):
            result = _azure(blob, 'centralindia', {
                'lab_day_mapping': [{'object_storage_gb': 25}], 'storage_gb': 25,
            })
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]['rate'], .02)
        self.assertIn('below 51200 GB', result[0]['note'])
        with patch('shared.live_lab_pricing.urlopen', return_value=io.BytesIO(
                json.dumps({'Items': items, 'NextPageLink': None}).encode())):
            with self.assertRaises(PricingUnavailable):
                _azure(blob, 'centralindia', {
                    'lab_day_mapping': [{'object_storage_gb': 51200}], 'storage_gb': 51200,
                })

    def test_explicit_s3_first_tier_is_bounded_by_all_allocations(self):
        values = self.inputs()
        values['pricing_selections']['Storage'].update(service='AmazonS3', first_tier_only=True)
        rows = self.catalog()
        next(row for row, _ in rows if row['SKU'] == 'Storage')['EndingRange'] = '100'
        values['lab_day_mapping'] = [{'object_storage_gb': 40}, {'object_storage_gb': 50}]
        def catalog(service, region):
            return [(row, url) for row, url in rows if (row['SKU'] == 'Storage') == (service == 'AmazonS3')]
        with patch('shared.live_lab_pricing._aws_catalog', side_effect=catalog):
            result = refresh_rates(values)
            self.assertIn('at most 100 GB', result['rate_card_overrides']['Storage']['note'])
            values['lab_day_mapping'].append({'object_storage_gb': 11})
            with self.assertRaises(PricingUnavailable):
                refresh_rates(values)

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


def test_fx_refresh_replaces_saved_rate_and_records_source():
    import io, json
    from datetime import datetime, timezone
    from shared.live_lab_pricing import refresh_exchange_rate
    data = {'base': 'USD', 'date': datetime.now(timezone.utc).date().isoformat(), 'rates': {'INR': 95.25}}
    with patch('shared.live_lab_pricing.urlopen', side_effect=lambda *a, **k: io.BytesIO(json.dumps(data).encode())) as get:
        first = refresh_exchange_rate({'fx_rate': 84})
        second = refresh_exchange_rate(first)
    assert get.call_count == 2
    assert second['fx_rate'] == 95.25
    assert second['fx_rate_source'].startswith('https://')
    assert second['fx_rate_date'].startswith(data['date'])
    assert second['fx_rate_fetched_at']


def test_fx_outage_does_not_reuse_saved_rate():
    import pytest
    from shared.live_lab_pricing import refresh_exchange_rate
    with patch('shared.live_lab_pricing.urlopen', side_effect=TimeoutError):
        with pytest.raises(PricingUnavailable):
            refresh_exchange_rate({'fx_rate': 84})


def test_fx_uses_dated_live_alternative_when_primary_is_unavailable():
    import io, json
    from datetime import datetime, timezone
    from shared.live_lab_pricing import refresh_exchange_rate
    data = {'result': 'success', 'base_code': 'USD',
            'time_last_update_unix': datetime.now(timezone.utc).timestamp(), 'rates': {'INR': 96.12}}
    with patch('shared.live_lab_pricing.urlopen', side_effect=[OSError('403'), io.BytesIO(json.dumps(data).encode())]):
        result = refresh_exchange_rate({'fx_rate': 84})
    assert result['fx_rate'] == 96.12
    assert result['fx_rate_source'] == 'https://open.er-api.com/v6/latest/USD'


def test_gcp_live_public_catalog_requires_environment_key(monkeypatch):
    import pytest
    from shared.live_lab_pricing import _gcp_catalog
    monkeypatch.delenv('GCP_BILLING_CATALOG_API_KEY', raising=False)
    with pytest.raises(PricingUnavailable, match='GCP_BILLING_CATALOG_API_KEY'):
        next(_gcp_catalog('service-id-123', 'asia-south1'))


def test_gcp_api_key_is_sent_in_header_not_url(monkeypatch):
    import io, json
    from shared.live_lab_pricing import _gcp_catalog
    monkeypatch.setenv('GCP_BILLING_CATALOG_API_KEY', 'do-not-log-this-key')
    observed = {}
    def fake_open(request, timeout):
        observed['url'] = request.full_url
        observed['key_header'] = request.get_header('X-goog-api-key')
        return io.BytesIO(json.dumps({'skus': [{'skuId': 'sku1',
            'serviceRegions': ['asia-south1']}]}).encode())
    monkeypatch.setattr('shared.live_lab_pricing.urlopen', fake_open)
    rows = list(_gcp_catalog('service-id-123', 'asia-south1'))
    assert len(rows) == 1
    assert 'do-not-log-this-key' not in observed['url']
    assert observed['key_header'] == 'do-not-log-this-key'


def test_gcp_exact_sku_rates_refresh_for_all_configured_resources(monkeypatch):
    from shared.live_lab_pricing import _gcp_catalog
    monkeypatch.setenv('GCP_BILLING_CATALOG_API_KEY', 'test-key')
    selections = {name: {'service_id': 'service-id-123', 'sku_id': name}
                  for name in RESOURCES}
    expected_unit = {
        'hour': 'hour', 'month': 'gibibyte month', 'gb': 'gibibyte',
        'minute': 'minute', 'request': 'request',
    }
    rows = []
    for name, unit_key in RESOURCES.items():
        rows.append(({
            'skuId': name, 'description': name, 'serviceRegions': ['asia-south1'],
            'category': {'usageType': 'OnDemand'},
            'pricingInfo': [{
                'effectiveTime': '2025-01-01T00:00:00Z',
                'pricingExpression': {
                    'usageUnitDescription': expected_unit[unit_key],
                    'aggregationInfo': {'level': 'ACCOUNT', 'interval': 'MONTHLY'},
                    'baseUnitConversionFactor': 1,
                    'tieredRates': [{'startUsageAmount': 0, 'unitPrice': {
                        'currencyCode': 'USD', 'units': '1', 'nanos': 500000000,
                    }}],
                },
            }],
        }, 'https://cloudbilling.googleapis.com/v1/services/service-id-123/skus'))
    monkeypatch.setattr('shared.live_lab_pricing._gcp_catalog', lambda service, region: iter(rows))
    result = refresh_rates({'cloud_provider': 'gcp', 'pricing_selections': selections})
    assert result['rate_card_overrides']['VM']['rate'] == 1.5
    assert result['rate_card_overrides']['Storage']['unit'] == 'GB-Mo'
    assert result['rate_card_overrides']['Object storage PUT requests']['unit'] == 'Requests'
    assert result['pricing_status'] == 'provider_api_verified_public_retail'


def test_gcp_custom_meter_unit_and_aggregation_must_be_configured():
    from shared.live_lab_pricing import _gcp_rate, PricingUnavailable
    sku = {'skuId': 'gcp-custom', 'pricingInfo': [{
        'effectiveTime': '2025-01-01T00:00:00Z',
        'pricingExpression': {
            'usageUnitDescription': 'seconds', 'baseUnitConversionFactor': 1,
            'aggregationInfo': {'level': 'PROJECT', 'interval': 'DAILY'},
            'tieredRates': [{'startUsageAmount': 0, 'unitPrice': {
                'currencyCode': 'USD', 'units': '1', 'nanos': 0,
            }}],
        },
    }]}
    row = _gcp_rate(sku, {}, 'seconds', 'https://example.com/catalog')
    assert row['unit'] == 'seconds'
    sku['pricingInfo'][0]['pricingExpression']['aggregationInfo']['level'] = 'REGION'
    with pytest.raises(PricingUnavailable, match='aggregation scope'):
        _gcp_rate(sku, {}, 'seconds', 'https://example.com/catalog')


def test_gcp_catalog_v1_aggregation_field_name_is_accepted():
    from shared.live_lab_pricing import _gcp_rate
    sku = {'skuId': 'gcp-v1', 'pricingInfo': [{
        'effectiveTime': '2025-01-01T00:00:00Z',
        'pricingExpression': {
            'usageUnitDescription': 'hour', 'baseUnitConversionFactor': 1,
            'aggregationInfo': {'aggregationLevel': 'ACCOUNT', 'aggregationInterval': 'MONTHLY'},
            'tieredRates': [{'startUsageAmount': 0, 'unitPrice': {
                'currencyCode': 'USD', 'units': '1', 'nanos': 0,
            }}],
        },
    }]}
    assert _gcp_rate(sku, {}, 'hour', 'https://example.com/catalog')['unit'] == 'Hrs'


def test_catalog_validation_checks_custom_meter_prices_without_usage():
    values = LivePricingTests().inputs()
    values['pricing_selections']['Sample AWS meter'] = {
        'unit_key': 'request', 'service': 'AWSLambda',
        'attributes': {'usageType': 'APS3-Lambda-Requests'},
    }
    values['additional_resource_usage'] = {'Sample AWS meter': 0}
    values['catalog_validation_only'] = True
    rows = LivePricingTests().catalog()
    lambda_row = dict(rows[0][0])
    lambda_row.update({'SKU': 'lambda-req', 'RateCode': 'lambda-rates',
                       'Unit': 'Requests', 'usageType': 'APS3-Lambda-Requests'})

    def catalog(service, region):
        return rows if service == 'AmazonEC2' else [(lambda_row, 'https://pricing.example/aws-lambda')]

    with patch('shared.live_lab_pricing._aws_catalog', side_effect=catalog):
        result = refresh_rates(values)
    assert result['rate_card_overrides']['Sample AWS meter']['rate'] == .12


def test_aws_selector_discovery_returns_exact_live_catalog_ids_without_autoselecting():
    from shared.live_lab_pricing import discover_price_selectors
    rows = [
        ({'TermType': 'OnDemand', 'Currency': 'USD', 'StartingRange': '0',
          'EndingRange': 'Inf', 'Unit': 'Requests', 'PricePerUnit': '0.0000002',
          'SKU': 'lambda-sku-a', 'RateCode': 'lambda-rate-a', 'EffectiveDate': '2026-01-01',
          'Description': 'Lambda requests - Mumbai', 'usageType': 'APS3-Lambda-Requests'},
         'https://pricing.example/aws-lambda'),
        ({'TermType': 'OnDemand', 'Currency': 'USD', 'StartingRange': '0',
          'EndingRange': 'Inf', 'Unit': 'Requests', 'PricePerUnit': '0.0000003',
          'SKU': 'lambda-sku-b', 'RateCode': 'lambda-rate-b', 'EffectiveDate': '2026-01-01',
          'Description': 'Lambda requests alternate', 'usageType': 'APS3-Lambda-Requests-Alt'},
         'https://pricing.example/aws-lambda'),
    ]
    with patch('shared.live_lab_pricing._aws_catalog', return_value=iter(rows)):
        result = discover_price_selectors('aws', 'ap-south-1', 'Lambda requests',
                                          service_code='AWSLambda', limit=5)
    assert result['is_discovery_only'] is True
    assert [item['sku'] for item in result['candidates']] == ['lambda-sku-a', 'lambda-sku-b']
    assert result['candidates'][0]['rate_code'] == 'lambda-rate-a'
    assert result['candidates'][0]['unit'] == 'Requests'


def test_custom_live_meter_is_resolved_from_provider_catalog():
    values = LivePricingTests().inputs()
    values['pricing_selections']['Lambda invocations'] = {
        'unit_key': 'request', 'service': 'AWSLambda',
        'attributes': {'usageType': 'APS3-Lambda-Requests'},
    }
    values['additional_resource_usage'] = {'Lambda invocations': 1000}
    rows = LivePricingTests().catalog()
    lambda_row = dict(rows[0][0])
    lambda_row.update({'SKU': 'lambda-req', 'RateCode': 'lambda-rates',
                       'Unit': 'Requests', 'usageType': 'APS3-Lambda-Requests'})
    def catalog(service, region):
        return rows if service == 'AmazonEC2' else [(lambda_row, 'https://pricing.example/aws-lambda')]
    with patch('shared.live_lab_pricing._aws_catalog', side_effect=catalog):
        result = refresh_rates(values)
    assert result['rate_card_overrides']['Lambda invocations']['rate'] == .12
    assert result['additional_resource_usage']['Lambda invocations'] == 1000
