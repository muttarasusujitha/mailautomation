from app.clients.public_search import parse_html


def test_html_search_extracts_only_allowed_linkedin_paths():
    html = b'<li class="b_algo"><h2><a href="https://www.linkedin.com/in/alice/?x=1">Alice</a></h2></li><a href="https://linkedin.com/jobs/1">Job</a><a href="https://linkedin.com.evil.test/in/x">Fake</a>'
    rows = parse_html(html, 10)
    assert rows == [{'url': 'https://www.linkedin.com/in/alice', 'title': 'Alice', 'content': 'Alice'}]
