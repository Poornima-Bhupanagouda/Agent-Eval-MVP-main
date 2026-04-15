"""
Travel Briefing Orchestrator - Master agent that routes to specialized agents.

Orchestrates Weather, Wiki, and Calculator agents to build comprehensive
travel briefings. Calls agents via HTTP, collects their responses and tool calls,
then synthesizes a unified output.

Uses keyword-based routing (no LLM required). When LLM is configured,
uses it for better synthesis; otherwise uses template-based assembly.

Sub-agents:
  - Weather Agent (port 8004) - forecasts via Open-Meteo
  - Wiki Agent (port 8005) - knowledge via Wikipedia
  - Calculator Agent (port 8006) - country/currency/math

Port: 8010
"""

import os
import re
import time
import uuid
import asyncio
import httpx
from typing import Optional, List, Dict, Any, Set

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

# Sub-agent endpoints (configurable via env)
WEATHER_URL = os.environ.get("WEATHER_AGENT_URL", "http://127.0.0.1:8004/chat")
WIKI_URL = os.environ.get("WIKI_AGENT_URL", "http://127.0.0.1:8005/chat")
CALC_URL = os.environ.get("CALC_AGENT_URL", "http://127.0.0.1:8006/chat")

SUB_AGENTS = {
    "weather_agent": {"name": "Weather Agent", "url": WEATHER_URL, "port": 8004},
    "wiki_agent": {"name": "Wiki Agent", "url": WIKI_URL, "port": 8005},
    "calculator_agent": {"name": "Calculator Agent", "url": CALC_URL, "port": 8006},
}


def route_query(text: str) -> Set[str]:
    """Determine which agents to invoke based on input keywords."""
    lower = text.lower()
    agents = set()

    # Weather signals
    if any(kw in lower for kw in ["weather", "forecast", "temperature", "rain", "snow", "climate", "hot", "cold", "sunny"]):
        agents.add("weather_agent")

    # Knowledge signals
    if any(kw in lower for kw in ["about", "history", "tell me", "what is", "who is", "explain",
                                   "culture", "things to do", "attractions", "famous", "known for"]):
        agents.add("wiki_agent")

    # Calculator/data signals
    if any(kw in lower for kw in ["convert", "currency", "cost", "price", "exchange",
                                   "calculate", "math", "country info", "population",
                                   "capital", "language", "timezone"]):
        agents.add("calculator_agent")

    # Travel signals → use all agents
    if any(kw in lower for kw in ["trip", "travel", "plan", "visit", "vacation", "holiday", "tour", "going to"]):
        agents = {"weather_agent", "wiki_agent", "calculator_agent"}

    # Compare queries → all agents
    if "compare" in lower or " vs " in lower or " versus " in lower:
        agents = {"weather_agent", "wiki_agent", "calculator_agent"}

    # Default: wiki + weather
    if not agents:
        agents = {"wiki_agent", "weather_agent"}

    return agents


def build_agent_input(original_input: str, agent_id: str) -> str:
    """Transform the user query into a clean, focused input for each sub-agent."""
    # Always extract the subject first — never send the full multi-sentence query
    location = extract_subject(original_input)

    if agent_id == "weather_agent":
        return f"What's the weather forecast for {location}?"

    elif agent_id == "wiki_agent":
        # Preserve the user's intent (history, culture, attractions, etc.)
        # instead of hardcoding a generic query
        lower = original_input.lower()
        intent_keywords = []
        for kw in ["history", "culture", "food", "cuisine", "architecture",
                    "landmarks", "museums", "art", "religion", "language",
                    "economy", "politics", "sports", "music", "nightlife"]:
            if kw in lower:
                intent_keywords.append(kw)
        if intent_keywords:
            return f"Tell me about {', '.join(intent_keywords)} of {location}"
        return f"Tell me about {location}"

    elif agent_id == "calculator_agent":
        # The calculator agent needs a COUNTRY name (not city).
        # Map well-known cities to their countries.
        country = _city_to_country(location)
        return f"Country info {country}"

    return f"Tell me about {location}"


# Common city → country mapping for the calculator agent
_CITY_COUNTRY_MAP = {
    "tokyo": "Japan", "kyoto": "Japan", "osaka": "Japan",
    "paris": "France", "lyon": "France", "marseille": "France",
    "london": "United Kingdom", "manchester": "United Kingdom", "edinburgh": "United Kingdom",
    "berlin": "Germany", "munich": "Germany", "frankfurt": "Germany",
    "rome": "Italy", "milan": "Italy", "venice": "Italy", "florence": "Italy",
    "madrid": "Spain", "barcelona": "Spain",
    "new york": "United States", "los angeles": "United States", "chicago": "United States",
    "san francisco": "United States", "washington": "United States", "miami": "United States",
    "sydney": "Australia", "melbourne": "Australia",
    "toronto": "Canada", "vancouver": "Canada", "montreal": "Canada",
    "beijing": "China", "shanghai": "China",
    "mumbai": "India", "delhi": "India", "new delhi": "India", "bangalore": "India",
    "dubai": "United Arab Emirates", "abu dhabi": "United Arab Emirates",
    "bangkok": "Thailand", "singapore": "Singapore", "seoul": "South Korea",
    "cairo": "Egypt", "istanbul": "Turkey", "moscow": "Russia",
    "rio de janeiro": "Brazil", "sao paulo": "Brazil",
    "amsterdam": "Netherlands", "lisbon": "Portugal", "vienna": "Austria",
    "zurich": "Switzerland", "geneva": "Switzerland", "prague": "Czech Republic",
    "budapest": "Hungary", "warsaw": "Poland", "athens": "Greece",
}

def _city_to_country(location: str) -> str:
    """Convert a city name to country, or return as-is if already a country."""
    return _CITY_COUNTRY_MAP.get(location.lower().strip(), location)


def extract_subject(text: str) -> str:
    """Extract the main subject/location from the query."""
    lower = text.lower()

    # Common clause-breakers: prepositions/conjunctions that start a secondary phrase
    STOP = r"(?:what|and|how|where|when|tell|with|for|from|including|during|about|on|i\s+want|budget|tips|cheap)"

    # Patterns for extracting location — stop at sentence boundary or secondary clause
    patterns = [
        # "plan a 3-day trip to Paris with budget tips"
        rf"(?:plan(?:ning)?)\s+(?:a\s+)?(?:\S+\s+)?(?:trip|visit|vacation|holiday)\s+(?:to\s+)?([A-Za-z][A-Za-z\s]{{1,30}}?)(?:\.|,|\?|$|\s+{STOP})",
        rf"(?:trip|travel|going)\s+to\s+([A-Za-z][A-Za-z\s]{{1,30}}?)(?:\.|,|\?|$|\s+{STOP})",
        rf"(?:want\s+to\s+(?:visit|go\s+to|see|explore))\s+([A-Za-z][A-Za-z\s]{{1,30}}?)(?:\.|,|\?|$|\s+{STOP})",
        rf"(?:visit(?:ing)?|explore|see)\s+([A-Za-z][A-Za-z\s]{{1,30}}?)(?:\.|,|\?|$|\s+{STOP})",
        rf"(?:weather|forecast)\s+(?:in|for)\s+([A-Za-z][A-Za-z\s]{{1,30}}?)(?:\.|,|\?|$|\s+{STOP})",
        rf"(?:about|history of)\s+([A-Za-z][A-Za-z\s]{{1,30}}?)(?:\.|,|\?|$|\s+{STOP})",
    ]

    for pattern in patterns:
        match = re.search(pattern, lower)
        if match:
            result = match.group(1).strip().rstrip('.,!?').strip()
            # Remove trailing stop words (e.g. "next", "this", "weekend")
            trailing_stop = {'next', 'this', 'last', 'the', 'a', 'an', 'weekend', 'week', 'month',
                             'with', 'budget', 'tips', 'cheap', 'for', 'from', 'including', 'during'}
            parts = result.split()
            while parts and parts[-1].lower() in trailing_stop:
                parts.pop()
            result = " ".join(parts).strip()
            if result:
                return result.title()

    # Handle "X vs Y" pattern — return first
    vs_match = re.search(r'(?:compare\s+)?([A-Za-z][A-Za-z\s]{1,25}?)\s+(?:vs\.?|versus|compared to)\s+([A-Za-z][A-Za-z\s]{1,25}?)(?:\?|$)', lower)
    if vs_match:
        return vs_match.group(1).strip().rstrip('.,!?').strip().title()

    # Fallback: remove stop words and punctuation, use only first sentence
    stop_words = {"plan", "planning", "a", "the", "weekend", "week", "trip", "to", "visit",
                  "travel", "what", "is", "tell", "me", "about", "compare", "and", "things",
                  "do", "in", "for", "should", "i", "know", "weather", "vs", "versus",
                  "like", "some", "famous", "landmarks", "are", "how", "let", "s", "want",
                  "going", "next", "this", "last", "vacation", "holiday", "tour",
                  "with", "budget", "tips", "cheap", "day", "days", "from", "including", "during",
                  "winter", "summer", "spring", "fall", "autumn", "family", "solo", "long", "short"}
    first_sentence = re.split(r'[.!?]', text)[0].strip()
    words = [
        w.strip('.,!?;:') for w in first_sentence.split()
        if w.strip('.,!?;:').lower() not in stop_words and len(w.strip('.,!?;:')) > 1
    ]
    return " ".join(words).strip().title() if words else text.strip()


async def call_agent(agent_id: str, input_text: str, timeout: float = 15.0) -> Dict[str, Any]:
    """Call a sub-agent via HTTP and return its response."""
    agent = SUB_AGENTS[agent_id]
    start = time.time()

    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.post(
                agent["url"],
                json={"input": input_text},
                headers={"Content-Type": "application/json"},
            )
            resp.raise_for_status()
            data = resp.json()

        return {
            "agent": agent_id,
            "agent_name": agent["name"],
            "output": data.get("output", str(data)),
            "tool_calls": data.get("tool_calls", []),
            "sources": data.get("sources", []),
            "latency_ms": int((time.time() - start) * 1000),
            "success": True,
            "error": None,
        }

    except httpx.ConnectError:
        return {
            "agent": agent_id,
            "agent_name": agent["name"],
            "output": f"{agent['name']} is not available (port {agent['port']}). Start it first.",
            "tool_calls": [],
            "sources": [],
            "latency_ms": int((time.time() - start) * 1000),
            "success": False,
            "error": f"Connection refused on port {agent['port']}",
        }

    except Exception as e:
        return {
            "agent": agent_id,
            "agent_name": agent["name"],
            "output": f"{agent['name']} returned an error: {str(e)}",
            "tool_calls": [],
            "sources": [],
            "latency_ms": int((time.time() - start) * 1000),
            "success": False,
            "error": str(e),
        }


def _filter_wiki_for_travel(text: str, location: str) -> str:
    """Filter Wikipedia text to keep only travel-relevant sentences.
    
    Removes dry demographic stats, population rankings, EU comparisons, 
    and administrative details that don't help plan a trip.
    """
    import re as _re

    # Words/phrases that signal IRRELEVANT sentences (demographics, stats)
    IRRELEVANT_SIGNALS = [
        "populous", "population of", "urban area", "metropolitan area",
        "census", "municipality of", "autonomous community",
        "administrative", "province of", "gdp", "per capita",
        "incorporated in", "merged with", "was founded in",
        "coordinates", "elevation", "area code",
    ]

    # Words/phrases that signal RELEVANT sentences (travel/culture)
    RELEVANT_SIGNALS = [
        "known for", "famous for", "landmark", "attraction", "museum",
        "beach", "park", "cathedral", "castle", "palace", "temple",
        "festival", "cuisine", "food", "restaurant", "nightlife",
        "architecture", "art", "culture", "heritage", "historic",
        "tourist", "tourism", "visit", "travel", "located on",
        "coast", "mountain", "river", "mediterranean", "beautiful",
        "district", "neighbourhood", "neighborhood", "quarter",
        "church", "tower", "bridge", "square", "market", "garden",
        "climate", "weather", "sunny", "warm", "season",
    ]

    lines = text.split("\n")
    filtered = []

    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue

        # Always keep short lines (headers, source links, titles)
        if len(stripped) < 60 or stripped.startswith("Source:") or stripped.startswith("http"):
            filtered.append(line)
            continue

        lower = stripped.lower()

        # Skip sentences with irrelevant demographic/stat content
        if any(sig in lower for sig in IRRELEVANT_SIGNALS):
            continue

        # Keep sentences with travel-relevant content
        if any(sig in lower for sig in RELEVANT_SIGNALS):
            filtered.append(line)
            continue

        # Keep the first sentence (usually a useful intro like "Paris is the capital of France")
        if len(filtered) <= 2:
            filtered.append(line)
            continue

        # For remaining sentences, keep if they mention the location
        if location.lower() in lower:
            filtered.append(line)

    result = "\n".join(filtered).strip()

    # If filtering removed too much, return original
    if len(result) < 50:
        return text

    return result


def synthesize_responses(query: str, agent_results: List[Dict[str, Any]]) -> str:
    """Combine agent responses into a coherent travel briefing."""
    subject = extract_subject(query)
    sections = []

    # Header
    lower = query.lower()
    if any(kw in lower for kw in ["trip", "travel", "plan", "visit"]):
        sections.append(f"Travel Briefing: {subject}\n{'=' * (len(subject) + 18)}")
    elif "compare" in lower or " vs " in lower:
        sections.append(f"Comparison Report\n{'=' * 17}")
    else:
        sections.append(f"Information: {subject}\n{'=' * (len(subject) + 13)}")

    # Agent sections (in a consistent order)
    agent_order = ["weather_agent", "wiki_agent", "calculator_agent"]
    section_headers = {
        "weather_agent": "Weather Forecast",
        "wiki_agent": "Tourist Attractions & Things To Do",
        "calculator_agent": "Country & Currency Data",
    }

    for agent_id in agent_order:
        result = next((r for r in agent_results if r["agent"] == agent_id), None)
        if not result:
            continue

        header = section_headers.get(agent_id, result["agent_name"])
        sections.append(f"\n--- {header} ---")

        if result["success"]:
            output = result["output"]
            # Filter wiki content to keep only travel-relevant info
            if agent_id == "wiki_agent":
                output = _filter_wiki_for_travel(output, subject)
            sections.append(output)
        else:
            # Show a clean user-friendly message, not raw error details
            sections.append(f"[{result['agent_name']} data temporarily unavailable]")

    # Summary (only show useful info, not internal stats)
    successful = [r for r in agent_results if r["success"]]
    failed = [r for r in agent_results if not r["success"]]

    if failed:
        sections.append(f"\nNote: {len(failed)} data source(s) were temporarily unavailable.")

    return "\n".join(sections)


# === FastAPI Application ===

app = FastAPI(
    title="Travel Briefing Orchestrator",
    description="Master agent that orchestrates weather, knowledge, and data agents for travel planning",
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
    input: str = Field(..., description="Travel query or general question")


class ChatResponse(BaseModel):
    output: str
    tool_calls: Optional[List[Dict[str, Any]]] = None
    workflow: Optional[Dict[str, Any]] = None
    latency_ms: Optional[int] = None


@app.get("/")
async def root():
    return {
        "name": "Travel Briefing Orchestrator",
        "version": "1.0.0",
        "status": "healthy",
        "description": "Orchestrates weather, wiki, and calculator agents for travel planning",
        "sub_agents": {
            "weather_agent": WEATHER_URL,
            "wiki_agent": WIKI_URL,
            "calculator_agent": CALC_URL,
        },
    }


@app.get("/health")
async def health():
    """Check health of orchestrator and sub-agents."""
    agent_status = {}
    async with httpx.AsyncClient(timeout=3.0) as client:
        for agent_id, agent in SUB_AGENTS.items():
            try:
                url = agent["url"].replace("/chat", "/health")
                resp = await client.get(url)
                agent_status[agent_id] = "healthy" if resp.status_code == 200 else "unhealthy"
            except Exception:
                agent_status[agent_id] = "unavailable"

    all_healthy = all(s == "healthy" for s in agent_status.values())
    return {
        "status": "healthy" if all_healthy else "degraded",
        "sub_agents": agent_status,
    }


@app.post("/describe")
async def describe():
    return {
        "name": "Travel Briefing Orchestrator",
        "purpose": (
            "Orchestrates specialized agents to build comprehensive travel briefings. "
            "Routes queries to Weather Agent (forecasts), Wiki Agent (destination info), "
            "and Calculator Agent (country/currency data). Synthesizes results into "
            "a unified response."
        ),
        "type": "orchestrator",
        "domain": "travel",
        "capabilities": ["orchestration", "tool_calling", "multi_agent", "routing", "question_answering"],
        "sub_agents": [
            {"name": "Weather Agent", "endpoint": WEATHER_URL, "domain": "weather"},
            {"name": "Wiki Agent", "endpoint": WIKI_URL, "domain": "knowledge"},
            {"name": "Calculator Agent", "endpoint": CALC_URL, "domain": "data"},
        ],
        "tools": [
            {"name": "route_to_agent", "description": "Route query to a specialized sub-agent via HTTP"},
        ],
    }


@app.post("/chat", response_model=ChatResponse)
async def chat(request: ChatRequest):
    start = time.time()
    workflow_id = str(uuid.uuid4())[:8]

    # --- Pipeline node functions ---

    def plan_route_node(state: dict) -> dict:
        """Node 1: Decide which agents to call based on the query."""
        target_agents = route_query(state["query"])
        tool_calls = []
        for agent_id in sorted(target_agents):
            agent = SUB_AGENTS[agent_id]
            tool_calls.append({
                "name": "route_to_agent",
                "args": {"agent": agent_id, "endpoint": agent["url"]},
            })
        state = dict(state)
        state["intermediate"] = dict(state.get("intermediate", {}))
        state["intermediate"]["target_agents"] = sorted(target_agents)
        state["tool_calls"] = list(state.get("tool_calls", [])) + tool_calls

        # Descriptive summary for trace visualization
        agent_names = [SUB_AGENTS[a]["name"] for a in sorted(target_agents)]
        state["_node_summary"] = f"Routed to {len(target_agents)} agent(s): {', '.join(agent_names)}"
        return state

    async def call_agents_node(state: dict) -> dict:
        """Node 2: Call all selected sub-agents in parallel."""
        target_agents = state["intermediate"]["target_agents"]
        tasks = []
        for agent_id in target_agents:
            agent_input = build_agent_input(state["query"], agent_id)
            tasks.append(call_agent(agent_id, agent_input))
        agent_results = await asyncio.gather(*tasks)

        state = dict(state)
        state["intermediate"] = dict(state.get("intermediate", {}))
        state["intermediate"]["agent_results"] = list(agent_results)

        # Collect sub-agent tool_calls
        sub_tool_calls = []
        for r in agent_results:
            for tc in r.get("tool_calls", []):
                sub_tool_calls.append(tc)
        state["tool_calls"] = list(state.get("tool_calls", [])) + sub_tool_calls

        successful = [r for r in agent_results if r["success"]]
        failed = [r for r in agent_results if not r["success"]]
        return state

    def synthesize_node(state: dict) -> dict:
        """Node 3: Combine agent responses into a unified travel briefing."""
        agent_results = state["intermediate"]["agent_results"]
        output = synthesize_responses(state["query"], agent_results)
        state = dict(state)
        state["output"] = output

        # Descriptive summary for trace visualization
        successful = [r for r in agent_results if r["success"]]
        output_len = len(output.split())
        state["_node_summary"] = f"Merged {len(successful)} agent response(s) into {output_len}-word briefing"
        return state

    # --- Run steps sequentially ---
    state = {"query": request.input, "intermediate": {}, "tool_calls": [], "output": "", "errors": [], "metadata": {"workflow_id": workflow_id}}
    state = plan_route_node(state)
    state = await call_agents_node(state)
    state = synthesize_node(state)

    # --- Build response ---
    total_latency = int((time.time() - start) * 1000)
    agent_results = state.get("intermediate", {}).get("agent_results", [])
    target_agents = state.get("intermediate", {}).get("target_agents", [])

    workflow = {
        "workflow_id": workflow_id,
        "agents_called": target_agents,
        "agent_responses": [
            {
                "agent": r["agent"],
                "agent_name": r["agent_name"],
                "output": r["output"],
                "tool_calls": r["tool_calls"],
                "latency_ms": r["latency_ms"],
                "success": r["success"],
                "error": r.get("error"),
            }
            for r in agent_results
        ],
        "total_latency_ms": total_latency,
    }

    # Filter tool_calls to only routing decisions (not sub-agent internals)
    routing_tool_calls = [
        tc for tc in state.get("tool_calls", [])
        if tc.get("name") == "route_to_agent"
    ]

    return ChatResponse(
        output=state.get("output", ""),
        tool_calls=routing_tool_calls,
        workflow=workflow,
        latency_ms=total_latency,
    )


def main():
    import uvicorn
    port = int(os.environ.get("ORCHESTRATOR_PORT", 8010))
    host = os.environ.get("HOST", "127.0.0.1")
    print(f"\nTravel Briefing Orchestrator starting at http://{host}:{port}")
    print(f"  API docs: http://{host}:{port}/docs")
    print(f"  Sub-agents:")
    print(f"    Weather: {WEATHER_URL}")
    print(f"    Wiki:    {WIKI_URL}")
    print(f"    Calc:    {CALC_URL}")
    print()
    uvicorn.run(app, host=host, port=port)


if __name__ == "__main__":
    main()
