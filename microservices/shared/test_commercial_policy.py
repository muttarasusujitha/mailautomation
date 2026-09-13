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
