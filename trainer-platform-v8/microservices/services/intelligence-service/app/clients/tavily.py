import requests
from typing import Any, Dict, List, Optional
from ..config import get_settings


settings = get_settings()


class TavilyClient:
    """Minimal Tavily client for LinkedIn-style search.

    This client reads the API key and base URL from the service settings.
    It avoids embedding secrets in the repository; set `TAVILY_API_KEY` in
    environment or in the service `.env` file.
    """

    def __init__(self, api_key: Optional[str] = None, base_url: Optional[str] = None):
        self.api_key = api_key or settings.TAVILY_API_KEY
        self.base_url = base_url or settings.TAVILY_API_URL.rstrip("/")
        if not self.api_key:
            raise RuntimeError("TAVILY_API_KEY is not set in environment or settings")

    def _headers(self) -> Dict[str, str]:
        return {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}

    def search_linkedin(self, query: str, limit: int = 10, **params) -> List[Dict[str, Any]]:
        """Perform a LinkedIn-style people/company search using Tavily.

        Args:
            query: Free-text query or name/title/location combination.
            limit: Max number of results to return.
            **params: Extra provider-specific params forwarded to Tavily.

        Returns:
            A list of result dicts returned by Tavily.
        """
        url = f"{self.base_url}/v1/linkedin/search"
        payload = {"q": query, "limit": limit}
        payload.update(params)
        resp = requests.post(url, json=payload, headers=self._headers(), timeout=15)
        resp.raise_for_status()
        data = resp.json()
        # The exact shape depends on Tavily; return 'results' if present, else raw JSON.
        return data.get("results") or data


# Convenience module-level client factory
def get_client() -> TavilyClient:
    return TavilyClient()
