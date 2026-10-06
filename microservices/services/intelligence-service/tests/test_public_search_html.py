import base64
from datetime import datetime

from urllib.parse import quote

from app.clients.public_search import parse_ddg, parse_html
from app.clients.search_accuracy import select_accurate_profiles


def _wrapped(url):
    token = base64.b64encode(url.encode()).decode().rstrip('=')
    return f'https://www.bing.com/ck/a?u=a1{token}&p=1'


def _ddg(url):
    return f'//duckduckgo.com/l/?uddg={quote(url, safe="")}&rut=1'


def test_public_results_page_keeps_profile_links_and_drops_other_sites():
    html = (
        f'<a class="result__a" href="{_ddg("https://www.linkedin.com/in/ravi")}">Ravi Kumar</a>'
        f'<a class="result__snippet" href="{_ddg("https://www.linkedin.com/in/ravi")}">Python corporate trainer</a>'
        f'<a class="result__a" href="{_ddg("https://www.python.org/")}">Python</a>'
        f'<a class="result__snippet" href="{_ddg("https://www.python.org/")}">Python trainer</a>'
        f'<a class="result__a" href="{_ddg("https://www.naukri.com/python-trainer-hyderabad")}">Naukri Python</a>'
        f'<a class="result__snippet" href="{_ddg("https://www.naukri.com/python-trainer-hyderabad")}">Python corporate trainer</a>'
    ).encode()
    assert parse_ddg(html, 10) == [
        {'url': 'https://www.linkedin.com/in/ravi', 'title': 'Ravi Kumar', 'content': 'Python corporate trainer'},
        {'url': 'https://www.naukri.com/python-trainer-hyderabad', 'title': 'Naukri Python', 'content': 'Python corporate trainer'},
    ]


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


def test_heading_link_is_kept_when_the_site_icon_comes_first():
    year = datetime.utcnow().year
    html = (
        '<li class="b_algo"><div class="b_tpcn">'
        f'<a class="tilk" href="{_wrapped("https://www.python.org/")}"><cite><strong>python.org</strong></cite></a></div>'
        f'<h2><a href="{_wrapped("https://www.linkedin.com/in/ravi")}">Ravi Kumar</a></h2>'
        f'<div class="b_caption"><p class="b_lineclamp2">Python corporate trainer Hyderabad {year}</p></div></li>'
    ).encode()
    assert parse_html(html, 10) == [{
        'url': 'https://www.linkedin.com/in/ravi',
        'title': 'Ravi Kumar',
        'content': f'Python corporate trainer Hyderabad {year}',
    }]


def test_html_search_keeps_current_skill_profiles_and_their_snippets():
    year = datetime.utcnow().year
    html = (
        f'<li class="b_algo"><h2><a href="{_wrapped("https://www.linkedin.com/in/ravi")}">Ravi Kumar</a></h2>'
        f'<p>Python corporate trainer Hyderabad {year}</p></li>'
        f'<li class="b_algo"><h2><a href="{_wrapped("https://www.python.org/")}">Python</a></h2>'
        f'<p>Python trainer {year}</p></li>'
        f'<li class="b_algo"><h2><a href="{_wrapped("https://www.linkedin.com/in/old-trainer")}">Old Trainer</a></h2>'
        f'<p>Python corporate trainer since 2019</p></li>'
        f'<li class="b_algo"><h2><a href="{_wrapped("https://www.linkedin.com/in/java-dev")}">Java Person</a></h2>'
        f'<p>Java instructor corporate training {year}</p></li>'
        f'<li class="b_algo"><h2><a href="{_wrapped("https://www.naukri.com/python-trainer-hyderabad")}">Naukri Python</a></h2>'
        f'<p>Python corporate trainer {year}</p></li>'
        f'<li class="b_algo"><h2><a href="{_wrapped("https://www.linkedin.com/jobs/view/1")}">Job</a></h2>'
        f'<p>Python trainer required {year}</p></li>'
    ).encode()
    rows = parse_html(html, 10)
    assert rows[0]['content'] == f'Python corporate trainer Hyderabad {year}'
    kept = select_accurate_profiles(rows, 'Python')
    assert [row['url'] for row in kept] == [
        'https://www.linkedin.com/in/ravi',
        'https://www.naukri.com/python-trainer-hyderabad',
    ]


def test_html_search_extracts_only_allowed_linkedin_paths():
    html = b'<li class="b_algo"><h2><a href="https://www.linkedin.com/in/alice/?x=1">Alice</a></h2></li><a href="https://linkedin.com/jobs/1">Job</a><a href="https://linkedin.com.evil.test/in/x">Fake</a>'
    rows = parse_html(html, 10)
    assert rows == [{'url': 'https://www.linkedin.com/in/alice', 'title': 'Alice', 'content': 'Alice'}]
