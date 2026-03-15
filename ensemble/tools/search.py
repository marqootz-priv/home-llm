"""Web search tool for Ensemble: Brave (if API key set) or DuckDuckGo (free fallback)."""
import httpx

from config import BRAVE_API_KEY

BRAVE_URL = "https://api.search.brave.com/res/v1/web/search"


def _search_brave(query: str) -> list[dict]:
    with httpx.Client(timeout=15.0) as client:
        r = client.get(
            BRAVE_URL,
            headers={"Accept": "application/json", "X-Subscription-Token": BRAVE_API_KEY},
            params={"q": query.strip()},
        )
        r.raise_for_status()
        data = r.json()
    web = data.get("web") or {}
    results = (web.get("results") or [])[:3]
    return [
        {"title": r.get("title", ""), "snippet": r.get("description", r.get("snippet", "")), "url": r.get("url", "")}
        for r in results
    ]


def _search_duckduckgo(query: str) -> list[dict]:
    import os

    # Clear proxy env so ddgs/primp don't receive proxy; avoids Client(proxy=...) errors
    saved = {k: os.environ.pop(k, None) for k in ("DDGS_PROXY", "HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy")}
    try:
        from ddgs import DDGS

        with DDGS() as ddgs:
            raw = list(ddgs.text(query.strip(), max_results=3))
        return [
            {"title": r.get("title", ""), "snippet": r.get("body", ""), "url": r.get("href", "")}
            for r in raw
        ]
    except TypeError as e:
        if "proxi" in str(e).lower():
            raise RuntimeError(
                "Web search failed: ddgs/primp version mismatch (proxy argument). "
                "Set BRAVE_API_KEY in .env to use Brave Search, or run: pip install -U ddgs primp"
            ) from e
        raise
    finally:
        for k, v in saved.items():
            if v is not None:
                os.environ[k] = v


def search_web(query: str) -> dict:
    """Search the web. Uses Brave if BRAVE_API_KEY is set, else DuckDuckGo (free). Returns top 3 results: title, snippet, url."""
    if not query or not query.strip():
        return {"ok": False, "error": "query is required"}
    try:
        if BRAVE_API_KEY:
            results = _search_brave(query)
        else:
            results = _search_duckduckgo(query)
        return {"ok": True, "results": results}
    except httpx.HTTPStatusError as e:
        return {"ok": False, "error": f"Search API error: {e.response.status_code}"}
    except Exception as e:
        return {"ok": False, "error": str(e)}
