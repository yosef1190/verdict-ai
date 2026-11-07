from verdict.search import build_search_url, parse_search_results

DUCKDUCKGO_HTML = """
<html><body>
  <div class="result results_links">
    <a class="result__a" href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fexample.com%2Farticle%3Futm_source%3Dnews">
      Example <b>Title</b>
    </a>
    <div class="result__snippet">A useful snippet.</div>
  </div>
  <div class="result results_links result--ad">
    <a class="result__a" href="https://ads.example.com/promo">Buy things</a>
    <div class="result__snippet">An advertisement.</div>
  </div>
  <div class="result results_links">
    <a class="result__a" href="https://duckduckgo.com/y.js?ad_provider=x">Internal</a>
    <div class="result__snippet">Internal link.</div>
  </div>
  <div class="result results_links">
    <a class="result__a" href="https://example.com/article?utm_source=news">Duplicate</a>
    <div class="result__snippet">Duplicate snippet.</div>
  </div>
</body></html>
"""

BING_HTML = """
<html><body>
  <ol id="b_results">
    <li class="b_algo">
      <h2><a href="https://example.org/page?utm_campaign=x">Bing Result</a></h2>
      <div class="b_caption"><p>Bing snippet.</p></div>
    </li>
    <li class="b_algo">
      <h2><a href="https://example.org/asset.pdf">PDF result</a></h2>
      <p>PDF snippet.</p>
    </li>
  </ol>
</body></html>
"""

YAHOO_HTML = """
<html><body>
  <div class="dd algo">
    <div class="compTitle">
      <a href="https://r.search.yahoo.com/_ylt=x/RV=2/RE=1/RO=10/RU=https%3a%2f%2fexample.com%2Fpage%3Futm_source%3Dnews/RK=2/RS=y">
        <h3 class="title">Yahoo Result</h3>
      </a>
    </div>
    <div class="compText"><p>Yahoo snippet.</p></div>
  </div>
</body></html>
"""

BRAVE_HTML = """
<html><body>
  <div class="snippet">
    <div class="result-content">
      <a href="https://example.org/brave?utm_source=news">
        <div class="title">Brave Result</div>
      </a>
    </div>
    <div class="generic-snippet">Brave snippet.</div>
  </div>
</body></html>
"""

GOOGLE_HTML = """
<html><body>
  <div id="search">
    <div class="g">
      <a href="/url?q=https://example.net/x&amp;sa=U"><h3>Google Result</h3></a>
      <div>Google snippet.</div>
    </div>
  </div>
</body></html>
"""


def test_build_search_url_encodes_query():
    url = build_search_url("duckduckgo", "vans knu skool", 5)
    assert url == "https://html.duckduckgo.com/html/?q=vans+knu+skool"

    bing = build_search_url("bing", "a&b", 5)
    assert "q=a%26b" in bing
    assert "count=5" in bing


def test_parse_duckduckgo_unwraps_redirects_and_drops_ads():
    results = parse_search_results(DUCKDUCKGO_HTML, "duckduckgo", limit=10)

    assert len(results) == 1
    result = results[0]
    assert result.title == "Example Title"
    assert result.url == "https://example.com/article"
    assert result.snippet == "A useful snippet."
    assert result.engine == "duckduckgo"


def test_parse_bing_filters_pdf_assets():
    results = parse_search_results(BING_HTML, "bing", limit=10)

    assert len(results) == 1
    assert results[0].title == "Bing Result"
    assert results[0].url == "https://example.org/page"
    assert results[0].snippet == "Bing snippet."


def test_parse_yahoo_unwraps_r_search_redirect():
    results = parse_search_results(YAHOO_HTML, "yahoo", limit=10)

    assert len(results) == 1
    assert results[0].title == "Yahoo Result"
    assert results[0].url == "https://example.com/page"
    assert results[0].snippet == "Yahoo snippet."
    assert results[0].engine == "yahoo"


def test_parse_brave_extracts_direct_results():
    results = parse_search_results(BRAVE_HTML, "brave", limit=10)

    assert len(results) == 1
    assert results[0].title == "Brave Result"
    assert results[0].url == "https://example.org/brave"
    assert results[0].snippet == "Brave snippet."


def test_parse_google_unwraps_redirect_and_extracts_snippet():
    results = parse_search_results(GOOGLE_HTML, "google", limit=10)

    assert len(results) == 1
    assert results[0].title == "Google Result"
    assert results[0].url == "https://example.net/x"
    assert results[0].snippet == "Google snippet."


def test_parse_search_results_respects_limit():
    results = parse_search_results(DUCKDUCKGO_HTML, "duckduckgo", limit=0)
    assert results == []
