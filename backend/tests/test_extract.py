from verdict.extract import (
    chunk_text,
    clean_text,
    extract_page,
    extract_urls,
    normalize_url,
    truncate,
)


def test_normalize_url_accepts_bare_domains_and_schemes():
    assert normalize_url("example.com") == "https://example.com"
    assert normalize_url("https://example.com/a?b=1") == "https://example.com/a?b=1"
    assert normalize_url("  www.example.co.uk/path  ") == "https://www.example.co.uk/path"
    assert normalize_url("not a url") == ""
    assert normalize_url("hello") == ""
    assert normalize_url("javascript:alert(1)") == ""


def test_extract_urls_preserves_order_and_strips_punctuation():
    text = "See https://example.com/a, then https://example.org/b). Also example.com."
    assert extract_urls(text) == ["https://example.com/a", "https://example.org/b"]


def test_clean_text_collapses_blank_lines_and_repeated_boilerplate():
    text = "Title\n\n\n\nSame line\nSame line\nBody".replace("\n", "\n")
    cleaned = clean_text(text)
    assert "\n\n\n" not in cleaned
    assert cleaned.count("Same line") == 1


def test_extract_page_reads_article_text_and_metadata():
    html = """
    <html>
      <head>
        <title>Fallback title</title>
        <meta property="og:title" content="The real title">
        <meta name="description" content="A useful description">
        <meta name="author" content="Jane Doe">
        <meta property="article:published_time" content="2026-10-01T10:00:00Z">
        <link rel="canonical" href="/canonical-post">
      </head>
      <body>
        <nav>Navigation menu with lots of links</nav>
        <article>
          <h1>The real title</h1>
          <p>The main finding is that Oxylabs returns clean HTML for analysis.</p>
          <p>OpenRouter free models can summarize that HTML into a report.</p>
        </article>
        <footer>Copyright footer</footer>
      </body>
    </html>
    """
    source = extract_page(html, "https://example.com/post")

    assert source.title == "The real title"
    assert source.author == "Jane Doe"
    assert source.published == "2026-10-01T10:00:00Z"
    assert source.url == "https://example.com/canonical-post"
    assert "The main finding" in source.text
    assert "Navigation menu" not in source.text
    assert "Copyright footer" not in source.text


def test_extract_page_falls_back_to_description_for_empty_pages():
    html = """
    <html><head>
      <title>Thin page</title>
      <meta name="description" content="Only a description is available here.">
    </head><body></body></html>
    """
    source = extract_page(html, "https://example.com")
    assert source.text == "Only a description is available here."


def test_chunk_text_respects_size_and_overlaps():
    text = " ".join(f"paragraph-{index}" for index in range(400))
    chunks = chunk_text(text, size=400, overlap=50)

    assert len(chunks) > 1
    assert all(len(chunk) <= 400 for chunk in chunks)
    assert chunks[0].startswith("paragraph-0")


def test_truncate_keeps_head_and_tail_with_marker():
    text = "A" * 1000 + "B" * 1000
    result = truncate(text, 200)

    assert len(result) <= 200 + len("\n\n[… content truncated …]\n\n")
    assert "content truncated" in result
    assert result.startswith("A")
    assert result.endswith("B")
