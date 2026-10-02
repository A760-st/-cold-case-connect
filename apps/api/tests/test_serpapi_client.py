import httpx
import pytest
from app.models.web_research import SearchType, ResultType
from app.serpapi.client import SerpApiClient, SerpApiError
from app.serpapi.parsers import canonicalize_url, parse_results


def test_client_sends_search_and_parses_json_without_exposing_secret():
    seen = {}
    def handler(request):
        seen.update(dict(request.url.params))
        return httpx.Response(200, json={"search_metadata": {"id": "search-1"}, "organic_results": []})
    client = SerpApiClient("test-secret", transport=httpx.MockTransport(handler))
    response = client.search({"engine": "google", "q": "query"})
    assert response["search_metadata"]["id"] == "search-1"
    assert seen["api_key"] == "test-secret"
    assert client.last_status == "ONLINE"
    assert "test-secret" not in repr(response)


def test_client_reports_missing_key_and_rate_limit():
    with pytest.raises(SerpApiError) as missing:
        SerpApiClient("").search({"engine": "google", "q": "query"})
    assert missing.value.code == "SERPAPI_NOT_CONFIGURED"
    rate_limited = SerpApiClient("key", transport=httpx.MockTransport(lambda request: httpx.Response(429)))
    with pytest.raises(SerpApiError) as limited:
        rate_limited.search({"engine": "google", "q": "query"})
    assert limited.value.status_code == 429


def test_mock_client_returns_explicit_demo_payload_without_key():
    client = SerpApiClient("", mock_mode=True)
    payload = client.search({"engine": "google_images", "q": "demo"})
    assert client.last_status == "MOCK_MODE"
    assert payload["search_metadata"]["mock"] is True
    assert payload["images_results"][0]["link"].endswith(".example/research-item")


def test_parsers_handle_web_news_images_and_missing_fields():
    web = parse_results({"organic_results": [{"title": "Story", "link": "https://EXAMPLE.com/item#part", "snippet": "Text"}, {}]}, SearchType.WEB, 10)
    assert web[0].result_type == ResultType.WEB and web[0].url == "https://EXAMPLE.com/item#part"
    news = parse_results({"news_results": [{"title": "News", "news_url": "https://news.example/item", "date": "Today", "source": {"name": "Paper"}}]}, SearchType.NEWS, 10)
    assert news[0].published_at == "Today" and news[0].source_name == "Paper"
    images = parse_results({"images_results": [{"title": "Image", "link": "https://source.example/page", "original": "https://cdn.example/image.jpg", "thumbnail": "https://cdn.example/thumb.jpg"}]}, SearchType.IMAGE, 10)
    assert images[0].url == "https://source.example/page" and images[0].thumbnail_url == "https://cdn.example/thumb.jpg"
    assert images[0].metadata["image_url"] == "https://cdn.example/image.jpg"
    assert parse_results({"organic_results": None}, SearchType.WEB, 10) == []


def test_canonical_url_preserves_query_and_normalizes_host_scheme_fragment():
    original, canonical = canonicalize_url("http://Example.COM?a=1&b=2#section")
    assert original == "http://Example.COM?a=1&b=2#section"
    assert canonical == "https://example.com/?a=1&b=2"
    assert canonicalize_url("javascript:alert(1)") == (None, None)
