import time
import httpx


class SerpApiError(Exception):
    def __init__(self, code: str, message: str, status_code: int = 502):
        self.code, self.message, self.status_code = code, message, status_code


class SerpApiClient:
    endpoint = "https://serpapi.com/search.json"

    def __init__(self, api_key: str, timeout: float = 15, transport=None, mock_mode: bool = False):
        self.api_key = api_key.strip()
        self.timeout = timeout
        self.transport = transport
        self.mock_mode = mock_mode
        self.last_status = "MOCK_MODE" if mock_mode else ("NOT_CONFIGURED" if not self.api_key else "IDLE")

    def search(self, params: dict) -> dict:
        if self.mock_mode:
            self.last_status = "MOCK_MODE"
            query = str(params.get("q", ""))
            engine = params.get("engine", "google")
            kind = "images_results" if engine == "google_images" else ("news_results" if engine == "google_news" or params.get("tbm") == "nws" else "organic_results")
            row = {"title": f"Demo search data for: {query}", "link": "https://demo-source.example/research-item", "snippet": "This deterministic placeholder is mock data. It is not a live search result and must not be treated as a source.", "source": {"name": "Demo source"}, "position": 1}
            if kind == "news_results": row["date"] = "Demo publication date"
            if kind == "images_results": row.update({"thumbnail": "https://demo-source.example/thumbnail.png", "original": "https://demo-source.example/image.png"})
            return {"search_metadata": {"id": "MOCK-DEMO", "status": "Success", "mock": True}, kind: [row]}
        if not self.api_key:
            self.last_status = "NOT_CONFIGURED"
            raise SerpApiError("SERPAPI_NOT_CONFIGURED", "Web research is not configured. Set SERPAPI_API_KEY on the backend.", 503)
        request_params = {**params, "api_key": self.api_key}
        last_error = None
        for attempt in range(3):
            try:
                with httpx.Client(timeout=self.timeout, transport=self.transport) as client:
                    response = client.get(self.endpoint, params=request_params)
                if response.status_code == 429:
                    self.last_status = "RATE_LIMITED"
                    raise SerpApiError("SERPAPI_RATE_LIMITED", "SerpApi rate limit reached. Retry later.", 429)
                if response.status_code >= 500:
                    raise SerpApiError("SERPAPI_UNAVAILABLE", "SerpApi is temporarily unavailable.", 502)
                if response.status_code >= 400:
                    self.last_status = "ERROR"
                    raise SerpApiError("SERPAPI_REQUEST_REJECTED", "SerpApi rejected the search request.", 502)
                try:
                    data = response.json()
                except ValueError:
                    self.last_status = "ERROR"
                    raise SerpApiError("SERPAPI_INVALID_RESPONSE", "SerpApi returned an invalid response.", 502) from None
                if not isinstance(data, dict):
                    self.last_status = "ERROR"
                    raise SerpApiError("SERPAPI_INVALID_RESPONSE", "SerpApi returned an invalid response.", 502)
                if data.get("error"):
                    error = str(data["error"]).lower()
                    self.last_status = "RATE_LIMITED" if "limit" in error or "quota" in error else "ERROR"
                    code = "SERPAPI_RATE_LIMITED" if self.last_status == "RATE_LIMITED" else "SERPAPI_PROVIDER_ERROR"
                    raise SerpApiError(code, "SerpApi could not complete this search.", 429 if self.last_status == "RATE_LIMITED" else 502)
                self.last_status = "ONLINE"
                return data
            except SerpApiError as exc:
                if exc.code == "SERPAPI_UNAVAILABLE":
                    self.last_status = "UNAVAILABLE"
                if exc.code not in {"SERPAPI_UNAVAILABLE"} or attempt == 2:
                    raise
                last_error = exc
            except httpx.HTTPError:
                self.last_status = "UNAVAILABLE"
                last_error = SerpApiError("SERPAPI_UNAVAILABLE", "SerpApi could not be reached. Retry later.", 502)
                if attempt == 2:
                    raise last_error from None
            if attempt < 2:
                time.sleep(0.15 * (attempt + 1))
        raise last_error or SerpApiError("SERPAPI_UNAVAILABLE", "SerpApi could not be reached.", 502)
