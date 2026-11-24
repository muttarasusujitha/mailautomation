import pytest
from shared.document_amounts import calculate_document


def test_stale_line_amount_is_replaced_and_paise_round_half_up():
    result = calculate_document([{'description': 'Training', 'quantity': 3, 'rate': '10.005', 'amount': 999}], gst_rate=18)
    assert result['subtotal'] == 30.02
    assert result['gst_amount'] == 5.40
    assert result['grand_total'] == 35.42


def test_agreed_package_total_is_not_changed_by_daily_rounding():
    result = calculate_document([], 100, 0, duration=3)
    assert result['items'][0]['quantity'] == 1
    assert result['grand_total'] == 100


@pytest.mark.parametrize('value', [-1, float('nan'), float('inf')])
def test_invalid_amounts_cannot_be_issued(value):
    with pytest.raises(ValueError):
        calculate_document([{'description': 'Training', 'quantity': 1, 'rate': value}])


def test_empty_document_cannot_be_issued():
    with pytest.raises(ValueError):
        calculate_document([], 0)


def test_azure_size_is_preserved_until_selected_sku_validation():
    from shared.live_lab_pricing import automatic_pricing_selections
    values = {'cloud_provider': 'azure', 'disk_gb_per_node': 100, 'lab_day_mapping': [{'vm_qty': 1}]}
    automatic_pricing_selections({}, values)
    assert values['disk_gb_per_node'] == 100
