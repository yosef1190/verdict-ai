import pytest

from verdict.errors import OxylabsError
from verdict.oxylabs_client import OxylabsClient
from tests.conftest import FakeResponse


def make_client():
    return OxylabsClient("test-token", retries=0)


def test_scrape_supports_webapi_results_shape():
    client = make_client()
    client.session.post = lambda *args, **kwargs: FakeResponse(
        200,
        {
            "state": "done",
            "results": [
                {
                    "html": "<html><body>hello</body></html>",
                    "metadata": {
                        "url": "https://example.com/",
                        "statuses": {"http_request": {"code": 200}},
                    },
                }
            ],
        },
    )

    result = client.scrape("https://example.com")

    assert result.html == "<html><body>hello</body></html>"
    assert result.status_code == 200
    assert result.url == "https://example.com/"


def test_scrape_supports_legacy_content_shape():
    client = make_client()
    client.session.post = lambda *args, **kwargs: FakeResponse(
        200,
        {
            "results": [
                {
                    "content": "<html>legacy</html>",
                    "status_code": 200,
                    "url": "https://example.org/",
                }
            ]
        },
    )

    result = client.scrape("https://example.org")

    assert result.html == "<html>legacy</html>"
    assert result.url == "https://example.org/"


def test_scrape_raises_on_target_error_status():
    client = make_client()
    client.session.post = lambda *args, **kwargs: FakeResponse(
        200,
        {
            "results": [
                {
                    "html": "<html>blocked</html>",
                    "metadata": {
                        "url": "https://example.com/",
                        "statuses": {"http_request": {"code": 403}},
                    },
                }
            ]
        },
    )

    with pytest.raises(OxylabsError, match="target status 403"):
        client.scrape("https://example.com")


def test_scrape_raises_on_api_error():
    client = make_client()
    client.session.post = lambda *args, **kwargs: FakeResponse(
        401, {"message": "Invalid credentials"}
    )

    with pytest.raises(OxylabsError, match="401"):
        client.scrape("https://example.com")


def test_missing_key_is_rejected():
    with pytest.raises(OxylabsError, match="OXYLABS_API_KEY"):
        OxylabsClient("")
