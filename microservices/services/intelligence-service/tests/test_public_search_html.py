import base64

from app.clients.public_search import parse_html


def _wrapped(url):
    token = base64.b64encode(url.encode()).decode().rstrip('=')
    return f'https://www.bing.com/ck/a?u=a1{token}&p=1'


def test_html_search_reads_wrapped_profile_links_without_opening_them():
    html = (
        f'<a href="{_wrapped("https://www.linkedin.com/in/ravi")}">Ravi Kumar</a>'
        f'<a href="{_wrapped("https://www.python.org/")}">Python</a>'
        f'<a href="{_wrapped("https://www.linkedin.com/learning/python")}">Learning</a>'
    ).encode()
    assert parse_html(html, 10) == [{
        'url': 'https://www.linkedin.com/in/ravi',
        'title': 'Ravi Kumar',
        'content': 'Ravi Kumar',
    }]


def test_html_search_extracts_only_allowed_linkedin_paths():
    html = b'<li class="b_algo"><h2><a href="https://www.linkedin.com/in/alice/?x=1">Alice</a></h2></li><a href="https://linkedin.com/jobs/1">Job</a><a href="https://linkedin.com.evil.test/in/x">Fake</a>'
    rows = parse_html(html, 10)
    assert rows == [{'url': 'https://www.linkedin.com/in/alice', 'title': 'Alice', 'content': 'Alice'}]
