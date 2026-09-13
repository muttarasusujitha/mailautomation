import pytest
from app.routes.requirements import _commercial_options_for_trainer, _recommend_option

@pytest.mark.parametrize('budget,days,model', [(800000,40,'TOTAL_70_30'), (90000,10,'TOTAL_70_30'), (100000,10,'TOTAL_70_30')])
def test_authoritative_split(budget, days, model):
    selected = _recommend_option(_commercial_options_for_trainer({'budget':budget,'duration_days':days}, {'day_rate':999999}),20)
    assert selected['model'] == model
    assert selected['trainer_cost'] == pytest.approx(budget * .7)
    assert selected['clahan_gross_profit'] == pytest.approx(budget * .3)

@pytest.mark.parametrize('rate,tds', [(10,10500),(0,0)])
def test_tds_preserves_company_profit(rate,tds):
    option = _commercial_options_for_trainer({'budget':150000,'tds_rate':rate}, {})[0]
    assert option['tds'] == tds
    assert option['tds_base_amount'] == 105000
    assert option['clahan_gross_profit'] == 45000
    assert option['net_amount_after_tds'] == 105000 - tds

def test_explicit_days_override_calendar_span():
    option = _commercial_options_for_trainer({'budget':100000,'duration_days':5,'training_dates':'1 October 2026 to 10 October 2026'}, {})[0]
    assert option['duration_days'] == 5

def test_extra_costs_trigger_negotiation():
    selected = _recommend_option(_commercial_options_for_trainer({'budget':100000,'other_costs':15000},{}),20)
    assert selected['clahan_gross_profit'] == 15000
    assert selected['negotiation_required']

def test_missing_budget_does_not_generate_profit():
    assert _commercial_options_for_trainer({}, {'day_rate':12000}) == []


def test_written_training_days_override_calendar_span():
    option = _commercial_options_for_trainer({
        'budget': 100000, 'duration_text': '20 Training Days',
        'training_dates': '1 October 2026 to 31 October 2026',
    }, {})[0]
    assert option['duration_days'] == 20
