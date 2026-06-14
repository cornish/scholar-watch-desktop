"""Tests for the cited-by HTML parsing + CAPTCHA detection (no browser, no network)."""

from scholar_watch.browser_fetcher import (
    looks_like_captcha,
    parse_citing_html,
    parse_gs_a,
)

# A trimmed-down version of a real Scholar "Cited by" results page.
RESULTS_HTML = """
<div id="gs_res_ccl">
  <div class="gs_r gs_or gs_scl"><div class="gs_ri">
    <h3 class="gs_rt"><a href="http://example.com/p1">[HTML] Deep learning for rectal cancer staging</a></h3>
    <div class="gs_a">J Smith, A Jones - Nature Medicine, 2026 - nature.com</div>
  </div></div>
  <div class="gs_r gs_or gs_scl"><div class="gs_ri">
    <h3 class="gs_rt"><a href="http://example.com/p2">A second citing study without a year here</a></h3>
    <div class="gs_a">L Zhang - bioRxiv - biorxiv.org</div>
  </div></div>
  <div class="gs_r gs_or gs_scl"><div class="gs_ri">
    <h3 class="gs_rt">No-link citation entry, 2024</h3>
    <div class="gs_a">M Brown, K White - J Pathology, 2024 - wiley.com</div>
  </div></div>
</div>
"""

CAPTCHA_HTML = """
<html><head><title>Google Scholar</title></head>
<body><div id="gs_captcha_ccl"></div>
<p>Please show you're not a robot</p></body></html>
"""


def test_parse_gs_a_full():
    authors, venue, year = parse_gs_a("J Smith, A Jones - Nature Medicine, 2026 - nature.com")
    assert authors == "J Smith, A Jones"
    assert venue == "Nature Medicine"
    assert year == 2026


def test_parse_gs_a_no_year():
    authors, venue, year = parse_gs_a("L Zhang - bioRxiv - biorxiv.org")
    assert authors == "L Zhang"
    assert venue == "bioRxiv"
    assert year is None


def test_parse_gs_a_empty():
    assert parse_gs_a("") == (None, None, None)


def test_parse_citing_html():
    rows = parse_citing_html(RESULTS_HTML)
    assert len(rows) == 3

    assert rows[0]["title"] == "Deep learning for rectal cancer staging"  # [HTML] tag stripped
    assert rows[0]["url"] == "http://example.com/p1"
    assert rows[0]["authors"] == "J Smith, A Jones"
    assert rows[0]["venue"] == "Nature Medicine"
    assert rows[0]["year"] == 2026

    assert rows[1]["year"] is None
    assert rows[2]["url"] is None  # no anchor


def test_parse_citing_html_limit():
    assert len(parse_citing_html(RESULTS_HTML, limit=2)) == 2


def test_looks_like_captcha():
    assert looks_like_captcha(CAPTCHA_HTML) is True
    assert looks_like_captcha(RESULTS_HTML) is False  # real results aren't a captcha
    assert looks_like_captcha("") is False
