import json
from urllib.error import HTTPError, URLError
from urllib.request import Request, build_opener
from app.core.config import settings
from app.schemas.financial_news import EvidenceRecord

class TavilyError(Exception): pass

def search(query: str):
    if not settings.tavily_search_enabled: raise TavilyError("Tavily search is disabled; use provided_evidence or enable TAVILY_SEARCH_ENABLED")
    if not settings.tavily_api_key: raise TavilyError("TAVILY_API_KEY is required for live retrieval")
    request=Request("https://api.tavily.com/search", data=json.dumps({"api_key":settings.tavily_api_key,"query":query,"search_depth":settings.tavily_search_depth,"max_results":settings.tavily_max_results}).encode(), headers={"Content-Type":"application/json"}, method="POST")
    try:
        with build_opener().open(request,timeout=settings.tavily_timeout_seconds) as response: data=json.loads(response.read(1024*1024).decode())
    except (HTTPError, URLError, TimeoutError, ValueError) as exc: raise TavilyError("Tavily search failed") from exc
    return [EvidenceRecord(evidence_id=f"E{i}",type="news",title=str(x.get("title") or "Untitled result"),content=str(x.get("content") or ""),source_name=str(x.get("source") or "Tavily"),url=str(x.get("url") or ""),published_at=x.get("published_date")) for i,x in enumerate(data.get("results",[]),1) if x.get("url") and x.get("content")]
