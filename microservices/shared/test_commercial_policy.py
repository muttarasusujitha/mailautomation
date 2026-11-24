import pytest
from shared.commercial_policy import margin_percent, proposal_offer


def test_confirmed_always_retains_thirty_percent():
    assert margin_percent({'batch_flow': 'confirmed', 'clahan_margin_percent': 25}) == 30


@pytest.mark.parametrize('tier,rate,client_total', [('standard', 14000, 91000), ('advanced', 15000, 98000), ('specialist', 16000, 104000)])
def test_proposal_week_is_one_total(tier, rate, client_total):
    offer = proposal_offer({'batch_flow': 'proposal', 'duration_days': 5,
                            'clahan_skill_tier': tier, 'clahan_margin_percent': 25})
    assert offer['trainer_amount'] == rate * 5
    assert offer['client_amount'] == client_total
    assert offer['basis'] == 'total engagement'


@pytest.mark.parametrize('rate', [13999, 16001, 17000])
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
    text = trainer_commercial_text({'batch_flow': 'proposal', 'duration_days': 20, 'clahan_skill_tier': 'specialist'})
    assert 'INR 16,000 per training day x 20 training days = INR 320,000 total commercial' in text


@pytest.mark.parametrize('req,expected', [
    ({'budget_per_day': 20000}, 'INR 14,000 per training day'),
    ({'budget_total': 100000}, 'INR 70,000 total commercial'),
    ({'batch_flow': 'proposal'}, 'INR 14,000 per training day'),
])
def test_missing_duration_shows_only_known_amount(req, expected):
    from shared.commercial_policy import trainer_commercial_text
    assert trainer_commercial_text(req) == expected + ', inclusive of applicable TDS'


def test_combined_client_budget_splits_lab_before_trainer_share():
    from shared.commercial_policy import commercial_breakdown, trainer_offer
    requirement = {
        'budget_total': 100000,
        'lab_client_price': 30000,
        'client_budget_includes_lab': True,
    }
    split = commercial_breakdown(requirement)
    assert split == {
        'training_client_amount': 70000.0,
        'lab_client_amount': 30000.0,
        'total_client_amount': 100000.0,
        'trainer_amount': 49000.0,
        'clahan_training_margin_amount': 21000.0,
        'budget_includes_lab': True,
        'needs_lab_price': False,
        'invalid': False,
    }
    assert trainer_offer(requirement)['total'] == 49000.0


def test_combined_budget_waits_for_lab_workbook_price():
    from shared.commercial_policy import commercial_breakdown
    split = commercial_breakdown({
        'budget_total': 100000,
        'requirement_source_text': 'Our INR 100,000 budget includes the lab workbook too.',
    })
    assert split['budget_includes_lab'] is True
    assert split['needs_lab_price'] is True
