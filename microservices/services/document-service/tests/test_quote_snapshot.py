import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException
from app.routes import excel
from shared import live_lab_pricing


def setup(monkeypatch):
    monkeypatch.setattr('shared.toc_quality.toc_delivery_error', lambda toc: '')
    monkeypatch.setattr('app.lab_recalculation.recalculate_lab_workbook', lambda raw: raw)
    monkeypatch.setattr(excel, '_lab_cost_to_excel', lambda toc, values: b'calculated workbook')
    db = {'lab_pricing_catalogs': SimpleNamespace(find_one=AsyncMock(return_value=None)),
          'lab_cost_rate_snapshots': SimpleNamespace(find_one=AsyncMock(return_value=None), insert_one=AsyncMock())}
    return db


def test_quote_refreshes_fx_and_saves_exact_snapshot(monkeypatch):
    db = setup(monkeypatch)
    def fx(values):
        assert 'fx_rate' not in values
        return dict(values, fx_rate=96, fx_rate_source='https://fx.example/current',
                    fx_rate_date='2026-09-16', fx_rate_fetched_at='2026-09-16T09:00:00+00:00')
    def cloud(values):
        assert values['fx_rate'] == 96
        assert values['participant_count'] == 29
        assert values['hours_per_day'] == 3
        assert values['lab_day_mapping'][0]['vm_qty'] == 29
        return dict(values, rate_snapshot_id='QUOTE-TEST', rate_checked_at='2026-09-16T09:00:00+00:00',
                    quote_valid_until='2026-09-23T09:00:00+00:00',
                    rate_card_overrides={}, pricing_status='provider_api_verified_public_retail')
    monkeypatch.setattr(live_lab_pricing, 'refresh_exchange_rate', fx)
    monkeypatch.setattr(live_lab_pricing, 'refresh_rates', cloud)
    response = asyncio.run(excel.export_toc_lab_cost_workbook({
        'toc': {'days': [{'focus_area': 'Docker lab'}]},
        'assumptions': {'fx_rate': 84, 'participant_count': 29,
                        'egress_gb': 0, 'build_minutes': 0, 'monitoring_gb': 0}}, db))
    saved = db['lab_cost_rate_snapshots'].insert_one.await_args.args[0]
    assert response.headers['X-Lab-Cost-Quote-ID'] == saved['quote_id']
    assert saved['assumptions']['fx_rate'] == 96
    assert saved['assumptions']['fx_rate_source'] == 'https://fx.example/current'
    assert saved['workbook_sha256']


def test_fx_failure_never_creates_snapshot_or_workbook(monkeypatch):
    db = setup(monkeypatch)
    def fail(values):
        raise live_lab_pricing.PricingUnavailable('FX unavailable')
    monkeypatch.setattr(live_lab_pricing, 'refresh_exchange_rate', fail)
    with pytest.raises(HTTPException):
        asyncio.run(excel.export_toc_lab_cost_workbook({
            'toc': {'days': [{'focus_area': 'Docker lab'}]},
            'assumptions': {'fx_rate': 84, 'egress_gb': 0, 'build_minutes': 0, 'monitoring_gb': 0}}, db))
    db['lab_cost_rate_snapshots'].insert_one.assert_not_awaited()
