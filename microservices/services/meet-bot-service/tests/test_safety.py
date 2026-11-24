from app.safety import valid_meet_link


def test_only_allowlisted_https_meet_links_are_accepted():
    allowed = "meet.google.com"
    assert valid_meet_link("https://meet.google.com/abc-defg-hij", allowed)
    assert not valid_meet_link("http://meet.google.com/abc-defg-hij", allowed)
    assert not valid_meet_link("https://meet.google.com.attacker.example/abc", allowed)
    assert not valid_meet_link("https://example.com/meeting", allowed)
