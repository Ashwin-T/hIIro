"""Stock quotes skill — Finnhub."""
from __future__ import annotations
from datetime import datetime, timedelta

TOOLS = [
    {"name": "get_stock_quote", "description": "Real-time stock quote for a ticker (e.g. AAPL).",
     "input_schema": {"type": "object", "properties": {"symbol": {"type": "string"}}, "required": ["symbol"]}},
    {"name": "get_stock_news", "description": "Recent news for a stock ticker.",
     "input_schema": {"type": "object", "properties": {"symbol": {"type": "string"}, "days": {"type": "integer", "default": 7}}, "required": ["symbol"]}},
]


def _make(api_key: str):
    if not api_key:
        def _nope(**_): return {"error": "FINNHUB_API_KEY not set"}
        return [_nope, _nope]

    import finnhub
    client = finnhub.Client(api_key=api_key)

    def quote(symbol: str) -> dict:
        s = symbol.upper().strip()
        try:
            q = client.quote(s)
            if not q or q.get("c") == 0: return {"error": f"No data for {s}"}
            return {"symbol": s, "price": q["c"], "change": round(q.get("d", 0), 2),
                    "change_pct": round(q.get("dp", 0), 2), "high": q["h"], "low": q["l"]}
        except Exception as e: return {"error": str(e)}

    def news(symbol: str, days: int = 7) -> dict:
        s = symbol.upper().strip()
        try:
            to_d = datetime.now(); from_d = to_d - timedelta(days=min(max(1, days), 30))
            arts = client.company_news(s, _from=from_d.strftime("%Y-%m-%d"), to=to_d.strftime("%Y-%m-%d"))
            return {"symbol": s, "news": [{"headline": a.get("headline"), "source": a.get("source"),
                    "date": datetime.fromtimestamp(a.get("datetime", 0)).strftime("%Y-%m-%d")} for a in arts[:5]]}
        except Exception as e: return {"error": str(e)}

    return [quote, news]


def build(cfg) -> list[tuple[dict, object]]:
    fns = _make(cfg.finnhub_api_key)
    return list(zip(TOOLS, fns))
