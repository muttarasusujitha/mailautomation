import pytest
from shared.commercial_policy import margin_percent, proposal_offer


def test_confirmed_always_retains_thirty_percent():
    assert margin_percent({'batch_flow': 'confirmed', 'clahan_margin_percent': 25}) == 30


@pytest.mark.parametrize('tier,rate', [('standard', 14000), ('advanced', 15000), ('specialist', 16000)])
def test_proposal_week_is_one_total(tier, rate):
    offer = proposal_offer({'batch_flow': 'proposal', 'duration_days': 5,
                            'clahan_skill_tier': tier, 'clahan_margin_percent': 25})
    assert offer['trainer_amount'] == rate * 5
    assert offer['client_amount'] == round(rate * 5 / .75, 2)
    assert offer['basis'] == 'total engagement'


@pytest.mark.parametrize('rate', [13000, 17000])
def test_proposal_rejects_out_of_range_offer(rate):
    with pytest.raises(ValueError):
        proposal_offer({'clahan_offer_per_day': rate})


def test_unknown_duration_does_not_invent_package_total():
    assert proposal_offer({'batch_flow': 'proposal'})['basis'] == 'per training day'



@pytest.mark.parametrize('days,rate', [(3, 9000), (4, 10000), (5, 10000),
    (10, 10000), (5, 11999), (5, 12000), (3, 13000), (10, 13000), (3, 13001), (10, 14000)])
@pytest.mark.parametrize('budget_kind', ['daily', 'total'])
def test_trainer_display_threshold(days, rate, budget_kind):
    from shared.commercial_policy import trainer_offer, trainer_commercial_text
    req = {'batch_flow': 'confirmed', 'duration_days': days}
    req['budget_total' if budget_kind == 'total' else 'budget_per_day'] = (
        rate * days / .7 if budget_kind == 'total' else rate / .7)
    offer = trainer_offer(req)
    assert offer['daily_rate'] == pytest.approx(rate)
    assert offer['total'] == pytest.approx(rate * days)
    text = trainer_commercial_text(req)
    if rate > 13000:
        assert f"INR {rate:,} per training day x {days} training days" in text
    else:
        assert "per training day" not in text
        assert "training days =" not in text
    assert f"INR {rate * days:,} total commercial" in text


def test_proposal_shows_daily_and_total():
    from shared.commercial_policy import trainer_commercial_text
    text = trainer_commercial_text({'batch_flow': 'proposal', 'duration_days': 20})
    assert 'INR 14,000 per training day x 20 training days = INR 280,000 total commercial' in text


@pytest.mark.parametrize('req,expected', [
    ({'budget_per_day': 20000}, 'INR 14,000 per training day'),
    ({'budget_total': 100000}, 'INR 70,000 total commercial'),
    ({'batch_flow': 'proposal'}, 'INR 14,000 per training day'),
])
def test_missing_duration_shows_only_known_amount(req, expected):
    from shared.commercial_policy import trainer_commercial_text
    assert trainer_commercial_text(req) == expected + ', inclusive of applicable TDS'
