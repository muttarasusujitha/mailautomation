from app.routes.requirements import _merge_pipeline_state

def test_shortlist_refresh_preserves_handoff_progress():
    old = {'client_slots_sent': True, 'client_slots_email_id': 'EMAIL-1', 'slot_status': 'confirmed_by_client', 'client_handoff_package_id': 'PKG-1', 'slot_reply_text': 'selected slot'}
    merged = _merge_pipeline_state({'trainer_id': 'T-1'}, old)
    for key, value in old.items():
        assert merged[key] == value
