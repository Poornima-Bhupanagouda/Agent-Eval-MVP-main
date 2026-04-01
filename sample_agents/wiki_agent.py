"""
Wiki Agent - Knowledge lookup using Wikipedia REST API.

A tool-using agent that wraps the Wikipedia search and summary APIs.
No LLM or API keys required - uses completely free, open APIs.

Tools:
  - search_wikipedia(query) -> list of matching articles
  - get_summary(title) -> article summary text

Port: 8005
"""

import os
import re
import time
import urllib.parse
import httpx
from typing import Optional, List, Dict, Any

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

SEARCH_URL = "https://en.wikipedia.org/w/api.php"
SUMMARY_URL = "https://en.wikipedia.org/api/rest_v1/page/summary"
USER_AGENT = "LillyAgentEval/1.0 (agent-eval-mvp; educational demo)"


def extract_topic(text: str) -> str:
    """Extract the main topic from natural language input."""
    lower = text.lower().strip()

    patterns = [
        r"(?:tell me|what do you know)\s+about\s+(.+?)(?:\?|$|\.|\!)",
        r"(?:what is|what are|who is|who are|who was)\s+(.+?)(?:\?|$|\.|\!)",
        r"(?:explain|describe|define)\s+(.+?)(?:\?|$|\.|\!)",
        r"(?:history of|info on|information about|facts about)\s+(.+?)(?:\?|$|\.|\!)",
        r"(?:search|look up|find|research)\s+(.+?)(?:\?|$|\.|\!)",
    ]

    for pattern in patterns:
        match = re.search(pattern, lower)
        if match:
            return match.group(1).strip()

    # Fallback: remove common filler words
    stop_words = {"tell", "me", "about", "what", "is", "the", "a", "an", "please",
                  "can", "you", "do", "know", "search", "for", "find", "look", "up",
                  "give", "some", "info", "information", "on"}
    words = [w for w in text.split() if w.lower() not in stop_words]
    return " ".join(words).strip() if words else text.strip()


async def search_wikipedia(query: str, limit: int = 3) -> List[Dict[str, str]]:
    """Search Wikipedia for articles matching the query."""
    params = {
        "action": "query",
        "list": "search",
        "srsearch": query,
        "srlimit": limit,
        "format": "json",
    }
    headers = {"User-Agent": USER_AGENT}

    async with httpx.AsyncClient(timeout=10.0, verify=False) as client:
        resp = await client.get(SEARCH_URL, params=params, headers=headers)
        resp.raise_for_status()
        data = resp.json()

    results = []
    for item in data.get("query", {}).get("search", []):
        # Strip HTML tags from snippet
        snippet = re.sub(r"<[^>]+>", "", item.get("snippet", ""))
        results.append({
            "title": item.get("title", ""),
            "snippet": snippet,
            "page_id": item.get("pageid"),
        })
    return results


async def get_summary(title: str) -> Optional[Dict[str, Any]]:
    """Get the summary of a Wikipedia article."""
    encoded = urllib.parse.quote(title.replace(" ", "_"))
    url = f"{SUMMARY_URL}/{encoded}"
    headers = {"User-Agent": USER_AGENT}

    async with httpx.AsyncClient(timeout=10.0, verify=False) as client:
        resp = await client.get(url, headers=headers)
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        data = resp.json()

    return {
        "title": data.get("title", title),
        "extract": data.get("extract", ""),
        "description": data.get("description", ""),
        "url": data.get("content_urls", {}).get("desktop", {}).get("page", ""),
        "thumbnail": data.get("thumbnail", {}).get("source"),
    }


def format_response(topic: str, search_results: List[Dict], summary: Optional[Dict]) -> str:
    """Format Wikipedia results as natural language."""
    if summary and summary.get("extract"):
        lines = []
        title = summary["title"]
        desc = summary.get("description", "")
        if desc:
            lines.append(f"{title} ({desc})")
        else:
            lines.append(title)

        lines.append("")
        lines.append(summary["extract"])

        url = summary.get("url", "")
        if url:
            lines.append(f"\nSource: {url}")

        return "\n".join(lines)

    if search_results:
        lines = [f"Wikipedia search results for '{topic}':\n"]
        for i, r in enumerate(search_results, 1):
            lines.append(f"{i}. {r['title']}: {r['snippet']}")
        return "\n".join(lines)

    return f"No Wikipedia articles found for '{topic}'."


# === FastAPI Application ===

app = FastAPI(
    title="Wiki Agent",
    description="Knowledge lookup using Wikipedia REST API (no API key needed)",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class ChatRequest(BaseModel):
    input: str = Field(..., description="Natural language knowledge query")


class ChatResponse(BaseModel):
    output: str
    tool_calls: Optional[List[Dict[str, Any]]] = None
    sources: Optional[List[str]] = None
    latency_ms: Optional[int] = None


@app.get("/")
async def root():
    return {
        "name": "Wiki Agent",
        "version": "1.0.0",
        "status": "healthy",
        "description": "Knowledge lookup via Wikipedia (no API key needed)",
    }


@app.get("/health")
async def health():
    return {"status": "healthy"}


@app.post("/describe")
async def describe():
    return {
        "name": "Wiki Agent",
        "purpose": "Searches Wikipedia and retrieves article summaries for knowledge queries. No API key required.",
        "type": "tool_using",
        "domain": "knowledge",
        "capabilities": ["tool_calling", "question_answering", "research"],
        "tools": [
            {"name": "search_wikipedia", "description": "Search for Wikipedia articles matching a query"},
            {"name": "get_summary", "description": "Get the summary/extract of a specific Wikipedia article"},
        ],
    }


@app.post("/chat", response_model=ChatResponse)
async def chat(request: ChatRequest):
    start = time.time()
    tool_calls = []
    sources = []

    topic = extract_topic(request.input)
    if not topic:
        return ChatResponse(
            output="I couldn't identify a topic in your request. Try asking like: 'Tell me about the Eiffel Tower'",
            tool_calls=[],
            latency_ms=int((time.time() - start) * 1000),
        )

    # Tool 1: Search Wikipedia
    tool_calls.append({"name": "search_wikipedia", "args": {"query": topic}})
    search_results = await search_wikipedia(topic)

    # Tool 2: Get summary of the top result
    summary = None
    if search_results:
        top_title = search_results[0]["title"]
        tool_calls.append({"name": "get_summary", "args": {"title": top_title}})
        summary = await get_summary(top_title)
        if summary and summary.get("url"):
            sources.append(summary["url"])

    output = format_response(topic, search_results, summary)
    latency = int((time.time() - start) * 1000)

    return ChatResponse(
        output=output,
        tool_calls=tool_calls,
        sources=sources if sources else None,
        latency_ms=latency,
    )


def main():
    import uvicorn
    port = int(os.environ.get("WIKI_AGENT_PORT", 8005))
    host = os.environ.get("HOST", "127.0.0.1")
    print(f"\nWiki Agent starting at http://{host}:{port}")
    print(f"  API docs: http://{host}:{port}/docs")
    print(f"  Uses Wikipedia API (no API key needed)\n")
    uvicorn.run(app, host=host, port=port)


if __name__ == "__main__":
    main()
