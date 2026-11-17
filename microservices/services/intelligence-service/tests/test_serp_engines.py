import asyncio
import base64
from datetime import datetime, timedelta, timezone
from urllib.parse import quote

from app.clients.serp_engines import (
    ENGINES, Engine, EngineHealth, canonical_profile_url, ddg_next_form, fetch_results_page,
    harvest_profiles, looks_blocked, unwrap_link,
)


def test_unwraps_engine_redirect_links_without_opening_them():
    target = 'https://in.linkedin.com/in/ravi-kumar'
    assert unwrap_link(f'//duckduckgo.com/l/?uddg={quote(target, safe="")}&rut=x') == target
    encoded = base64.b64encode(target.encode()).decode().rstrip('=')
    assert unwrap_link(f'https://www.bing.com/ck/a?!&&p=abc&u=a1{encoded}&ntb=1') == target
    yahoo = f'https://r.search.yahoo.com/_ylt=Awr/RV=2/RE=1/RO=10/RU={quote(target, safe="")}/RK=2/RS=x-'
    assert unwrap_link(yahoo) == target
    assert unwrap_link('/url?q=' + quote(target, safe=''), 'www.example.com') == target
    assert unwrap_link('javascript:void(0)') == ''


def test_canonical_profile_url_keeps_only_person_profiles():
    assert canonical_profile_url('https://in.linkedin.com/in/Ravi-Kumar-123/?trk=x') == 'https://www.linkedin.com/in/Ravi-Kumar-123'
    assert canonical_profile_url('http://linkedin.com/in/asha/details/skills') == 'https://www.linkedin.com/in/asha'
    assert canonical_profile_url('https://www.linkedin.com/company/acme') == ''
    assert canonical_profile_url('https://www.linkedin.com/in/') == ''
    assert canonical_profile_url('https://evil.example.com/in/ravi') == ''


BING_PAGE = b'''<html><body><ol id="b_results">
<li class="b_algo"><h2><a href="https://in.linkedin.com/in/ravi-python">Ravi Kumar - Python Corporate Trainer - Freelance | LinkedIn</a></h2>
<div class="b_caption"><cite>in.linkedin.com &rsaquo; ravi-python</cite><p>Python and Django corporate trainer with 12 years of experience in Bangalore.</p></div></li>
<li class="b_algo"><h2><a href="https://www.naukri.com/python-jobs">Python jobs</a></h2><p>Apply now</p></li>
<li class="b_algo"><h2><a href="https://www.linkedin.com/in/asha-data">Asha Rao - Technical Trainer | LinkedIn</a></h2>
<p class="b_lineclamp2">Technical trainer for Python, data science and machine learning.</p></li>
</ol><script>var captcha = 1;</script></body></html>'''


def test_harvests_titles_and_snippets_from_a_bing_page():
    rows, links = harvest_profiles(BING_PAGE, 'www.bing.com')
    assert links == 2
    assert [row['url'] for row in rows] == ['https://www.linkedin.com/in/ravi-python', 'https://www.linkedin.com/in/asha-data']
    assert rows[0]['title'].startswith('Ravi Kumar - Python Corporate Trainer')
    assert 'Django corporate trainer' in rows[0]['snippet']
    assert 'Apply now' not in rows[0]['snippet']
    assert 'machine learning' in rows[1]['snippet']


def test_harvests_duckduckgo_and_yahoo_style_markup():
    ddg = ('<div class="result"><h2 class="result__title"><a class="result__a" href="//duckduckgo.com/l/?uddg='
           + quote('https://www.linkedin.com/in/meena-aws', safe='')
           + '">Meena - AWS Trainer</a></h2><a class="result__snippet">AWS certified trainer, corporate training.</a></div>')
    rows, _ = harvest_profiles(ddg, 'html.duckduckgo.com')
    assert rows[0]['url'] == 'https://www.linkedin.com/in/meena-aws'
    assert rows[0]['title'] == 'Meena - AWS Trainer'
    yahoo = ('<div class="algo"><h3><a href="https://r.search.yahoo.com/x/RU='
             + quote('https://in.linkedin.com/in/john-sap', safe='')
             + '/RK=2/RS=y">John - SAP FICO Trainer</a></h3><div class="compText"><p>SAP FICO corporate trainer.</p></div></div>')
    rows, _ = harvest_profiles(yahoo, 'search.yahoo.com')
    assert rows == [{'url': 'https://www.linkedin.com/in/john-sap', 'title': 'John - SAP FICO Trainer',
                     'snippet': 'SAP FICO corporate trainer.', 'content': 'John - SAP FICO Trainer SAP FICO corporate trainer.'}]


def test_block_detection():
    assert looks_blocked(429, b'', 0)
    assert looks_blocked(202, b'<html></html>', 0)
    assert looks_blocked(200, b'<div class="anomaly-modal">confirm</div>', 0)
    assert looks_blocked(200, b'Our systems have detected unusual traffic', 0)
    assert not looks_blocked(200, BING_PAGE, 2)  # The word captcha in a script is not a block.
    assert not looks_blocked(200, b'<html>No results</html>', 0)


def test_reads_duckduckgo_next_page_form():
    page = b'''<form action="/html/" method="post"><input type="submit" value="Next" />
    <input type="hidden" name="q" value="python trainer"><input type="hidden" name="s" value="30">
    <input type="hidden" name="vqd" value="4-123"></form>'''
    url, fields = ddg_next_form(page, 'https://html.duckduckgo.com/html/')
    assert url == 'https://html.duckduckgo.com/html/'
    assert fields == {'q': 'python trainer', 's': '30', 'vqd': '4-123'}
    assert ddg_next_form(b'<form action="/html/"><input name="q" value="x"></form>', 'u') is None


def test_engine_health_backs_off_and_resets(tmp_path):
    health = EngineHealth(tmp_path / 'health.json')
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    first = health.record_block('bing', now)
    second = health.record_block('bing', now)
    assert first - now == timedelta(minutes=15)
    assert second - now == timedelta(minutes=30)
    reloaded = EngineHealth(tmp_path / 'health.json')
    assert reloaded.cooling_until('bing', now) == second
    assert reloaded.cooling_until('bing', second + timedelta(seconds=1)) is None
    reloaded.record_ok('bing')
    assert EngineHealth(tmp_path / 'health.json').cooling_until('bing', now) is None


class FakeFetcher:
    def __init__(self, http_reply, browser_reply=None):
        self.http_reply = http_reply
        self.browser_reply = browser_reply
        self.browser_calls = 0

    async def http(self, method, url, data=None):
        return self.http_reply

    @property
    def browser_available(self):
        return self.browser_reply is not None

    async def browser(self, url):
        self.browser_calls += 1
        return self.browser_reply


ENGINE = Engine('fake', 'Fake', 'www.bing.com', lambda q: 'https://www.bing.com/search?q=' + q)


def test_refused_page_is_rendered_in_the_headless_browser():
    fetcher = FakeFetcher((429, b''), (200, BING_PAGE))
    page = asyncio.run(fetch_results_page(ENGINE, fetcher, 'GET', 'https://www.bing.com/search?q=x'))
    assert page.status == 'ok' and page.via_browser and len(page.rows) == 2
    assert fetcher.browser_calls == 1


def test_refused_everywhere_is_reported_blocked():
    fetcher = FakeFetcher((200, b'<html>Please solve this captcha</html>'), (200, b'<html>captcha</html>'))
    page = asyncio.run(fetch_results_page(ENGINE, fetcher, 'GET', 'https://www.bing.com/search?q=x'))
    assert page.status == 'blocked'
    unreachable = asyncio.run(fetch_results_page(ENGINE, FakeFetcher((0, b'')), 'GET', 'u'))
    assert unreachable.status == 'error'


def test_every_engine_builds_search_urls():
    for engine in ENGINES:
        assert engine.first_url('python trainer').startswith('https://' + engine.host)
        if engine.page_url:
            assert engine.page_url('python trainer', 1) != engine.first_url('python trainer')


def test_post_links_are_harvested_and_keyed_by_activity():
    from app.clients.serp_engines import canonical_post_url, post_key, with_params
    post = 'https://in.linkedin.com/posts/acme-learning_python-trainer-required-activity-7234567890123456789-AbCd?utm=x'
    feed = 'https://www.linkedin.com/feed/update/urn:li:activity:7234567890123456789/'
    assert canonical_post_url(post) == 'https://www.linkedin.com/posts/acme-learning_python-trainer-required-activity-7234567890123456789-AbCd'
    assert canonical_post_url(feed) == 'https://www.linkedin.com/feed/update/urn:li:activity:7234567890123456789'
    assert post_key(canonical_post_url(post)) == post_key(canonical_post_url(feed)) == 'linkedin:activity:7234567890123456789'
    assert canonical_post_url('https://www.linkedin.com/in/ravi') == ''
    assert canonical_post_url('https://www.linkedin.com/feed/') == ''
    body = (f'<li><h2><a href="{post}">Acme Learning on LinkedIn: Python trainer required</a></h2>'
            '<p>We are looking for a freelance Python trainer for a 5-day batch. Mail hr@acme.in</p></li>'
            '<li><h2><a href="https://www.linkedin.com/in/ravi">Ravi - Python Trainer</a></h2></li>').encode()
    rows, links = harvest_profiles(body, 'www.bing.com', kind='post')
    assert links == 1 and rows[0]['url'].endswith('-AbCd')
    assert 'freelance Python trainer' in rows[0]['snippet']
    assert with_params('https://x.test/s?q=a', {'df': 'm'}) == 'https://x.test/s?q=a&df=m'
    assert with_params('https://x.test/s?q=a', {}) == 'https://x.test/s?q=a'


def test_engines_with_date_filters_define_week_and_month():
    for engine in ENGINES:
        if engine.recent:
            assert set(engine.recent) == {'week', 'month'}


YAHOO_PAGE = ('<div class="dd algo algo-sr"><div class="compTitle options-toggle">'
              '<h3 class="title"><a href="https://r.search.yahoo.com/_ylt=x/RV=2/RU='
              + quote('https://in.linkedin.com/in/ravi-k-1234', safe='')
              + '/RK=2/RS=y-"><span class="d-ib p-abs">in.linkedin.com › in › ravi-k-1234</span>'
              'Ravi K - Python Corporate Trainer - Freelance | LinkedIn</a></h3>'
              '<div class="action-menu"><a href="https://cc.bingj.com/cache.aspx?d=1">Cached</a></div></div>'
              '<div class="compText aAbs"><p><span class="fc-falcon">Python and Django trainer for corporate batches in Pune.</span></p></div></div>'
              '<div class="dd algo"><h3><a href="https://www.naukri.com/python-trainer-jobs">Python Trainer Jobs in Pune - Naukri</a></h3>'
              '<p>Apply to 120 jobs</p></div>')


def test_yahoo_breadcrumb_and_cached_link_do_not_hide_title_or_snippet():
    rows, links = harvest_profiles(YAHOO_PAGE, 'search.yahoo.com')
    assert links == 1
    assert rows[0]['url'] == 'https://www.linkedin.com/in/ravi-k-1234'
    assert rows[0]['title'] == 'Ravi K - Python Corporate Trainer - Freelance | LinkedIn'
    assert rows[0]['snippet'] == 'Python and Django trainer for corporate batches in Pune.'
    assert 'Apply to 120 jobs' not in rows[0]['snippet']


def test_breadcrumb_only_title_falls_back_to_link_label():
    page = ('<h3><a aria-label="Asha Rao - AWS Trainer" href="https://www.linkedin.com/in/asha-rao">'
            'linkedin.com › in › asha-rao</a></h3>')
    rows, _ = harvest_profiles(page, 'search.yahoo.com')
    assert rows[0]['title'] == 'Asha Rao - AWS Trainer'
