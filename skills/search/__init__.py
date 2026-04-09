"""Web search skill — DuckDuckGo instant answers."""
import requests

TOOLS = [{
    "name": "search_web",
    "description": "Search the web for information.",
    "input_schema": {
        "type": "object",
        "properties": {"query": {"type": "string", "description": "Search query"}},
        "required": ["query"],
    },
}]


def _search(query: str) -> dict:
    if not query:
        return {"error": "empty query"}
    try:
        r = requests.get("https://api.duckduckgo.com/",
                         params={"q": query, "format": "json", "no_html": 1, "skip_disambig": 1}, timeout=5)
        data = r.json()
        results = []
        if data.get("Abstract"):
            results.append({"title": data.get("Heading", query), "text": data["Abstract"]})
        for t in data.get("RelatedTopics", [])[:3]:
            if isinstance(t, dict) and "Text" in t:
                results.append({"title": t["Text"][:60], "text": t["Text"]})
        return {"query": query, "results": results or [{"title": "No results", "text": "Try rephrasing."}]}
    except Exception as e:
        return {"error": str(e)}


def build(cfg) -> list[tuple[dict, object]]:
    return [(TOOLS[0], _search)]
