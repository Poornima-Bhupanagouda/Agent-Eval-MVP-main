"""
Conversational Agent - Sample agent for Lilly Agent Eval.

A stateful chatbot that maintains memory across conversation turns.
Designed to test coherence and context_retention metrics.

Runs on port 8003.

Modes:
- DEMO mode (default): Smart context-aware responses, no API key needed.
- LIVE mode: Uses OpenAI if OPENAI_API_KEY is set.

Start with:
    python -m sample_agents.conversational_agent
or:
    python sample_agents/conversational_agent.py
"""

import os
import re
import time
import uuid
import random
import logging
from typing import Optional, List, Dict, Any
from collections import defaultdict

from dotenv import load_dotenv
load_dotenv()

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Session memory store  (in-memory, keyed by session_id)
# Each session holds: {"history": [{"role": .., "content": ..}], "context": {}}
# ---------------------------------------------------------------------------
_sessions: Dict[str, Dict] = defaultdict(lambda: {"history": [], "context": {}})

# Cached OAuth2 token for LLM Gateway (avoid re-fetching every turn)
_cached_token: Optional[str] = None
_cached_token_expiry: float = 0


# ---------------------------------------------------------------------------
# Demo-mode response engine
# ---------------------------------------------------------------------------

def _extract_context_facts(history: List[Dict]) -> Dict[str, Any]:
    """
    Scan conversation history and extract remembered facts.
    Returns a dict with keys like: name, topics, last_topic, count
    """
    facts: Dict[str, Any] = {}
    topics = []

    for msg in history:
        if msg.get("role") != "user":
            continue
        content = msg.get("content", "").lower()

        # Name detection: "my name is X" / "i am X" / "call me X"
        for pattern in [
            r"my name is ([a-z]+)",
            r"i'?m ([a-z]+)",
            r"call me ([a-z]+)",
            r"i am ([a-z]+)",
        ]:
            m = re.search(pattern, content)
            if m and len(m.group(1)) > 1:
                facts["name"] = m.group(1).capitalize()
                break

        # Topic detection: what was asked about
        for kw_group in [
            (["weather", "temperature", "rain", "sunny", "forecast"], "weather"),
            (["paris", "france", "europe", "travel", "trip", "visit"], "travel to Paris"),
            (["python", "code", "programming", "software", "developer"], "programming"),
            (["health", "diet", "exercise", "fitness", "nutrition"], "health and fitness"),
            (["food", "vegetarian", "vegan", "dinner", "lunch", "meal", "cuisine", "recipe"], "food preferences"),
            (["coffee", "tea", "drink", "beverage", "latte", "cappuccino", "espresso", "mocha"], "drink preferences"),
            (["machine learning", "ai", "artificial intelligence", "model", "neural"], "AI and machine learning"),
            (["work", "job", "career", "office", "manager", "project"], "work"),
            (["book", "read", "novel", "story", "author"], "reading"),
        ]:
            if any(kw in content for kw in kw_group[0]):
                topics.append(kw_group[1])

        # Preference detection
        if "i like" in content or "i love" in content or "i enjoy" in content or "i prefer" in content:
            m = re.search(r"i (?:like|love|enjoy|prefer) ([^.!?]+)", content)
            if m:
                facts["preference"] = m.group(1).strip()

        # Goal detection
        if "i want to" in content or "i need to" in content:
            m = re.search(r"i (?:want|need) to ([^.!?]+)", content)
            if m:
                facts["goal"] = m.group(1).strip()

    facts["topics"] = list(dict.fromkeys(topics))  # deduplicated, ordered
    facts["turn_count"] = sum(1 for m in history if m.get("role") == "user")
    return facts


def _build_demo_response(user_input: str, history: List[Dict]) -> str:
    """
    Generate a context-aware demo response.

    Rules (in priority order):
    1. Direct memory questions → pull from extracted facts
    2. Continuation questions → reference previous topic
    3. New topic → answer normally but weave in name if known
    4. Greetings / farewells → handle gracefully
    5. Safety / harmful → decline politely
    """
    lower = user_input.lower().strip()
    facts = _extract_context_facts(history)
    name_prefix = f"{facts['name']}, " if facts.get("name") else ""
    topics = facts.get("topics", [])
    turn = facts.get("turn_count", 0)

    # --- Safety guard ---
    harmful_keywords = ["weapon", "bomb", "kill", "hack", "exploit", "malware", "drug synthesis"]
    if any(kw in lower for kw in harmful_keywords):
        return (
            "I'm not able to help with that request. "
            "If you have other questions, I'm happy to assist!"
        )

    # --- Direct memory questions ---
    if any(q in lower for q in ["what is my name", "what's my name", "do you remember my name", "who am i"]):
        if facts.get("name"):
            return f"Of course! Your name is {facts['name']}. I remember what you've shared so far."
        return "You haven't told me your name yet. What should I call you?"

    if any(q in lower for q in ["what did i say", "what did we talk", "do you remember", "what was i asking"]):
        if topics:
            topic_list = ", ".join(topics[-3:])
            return (
                f"Yes, {name_prefix}we've been discussing: {topic_list}. "
                f"We've had {turn} exchanges so far. What would you like to continue with?"
            )
        return (
            f"We've had {turn} exchange(s) so far. "
            "I'm tracking our full conversation — what would you like to revisit?"
        )

    # --- Drink / preference recall ---
    if any(q in lower for q in ["what drink", "which drink", "what beverage"]):
        pref = facts.get("preference", "")
        if "coffee" in pref:
            return f"{name_prefix}You told me you like coffee! You mentioned: '{facts['preference']}'."
        if "tea" in pref:
            return f"{name_prefix}You told me you like tea! You mentioned: '{facts['preference']}'."
        if pref:
            return f"{name_prefix}Based on what you've shared, your preference is: {pref}."
        return f"{name_prefix}You haven't told me about your drink preferences yet."

    if any(q in lower for q in ["what do i like", "what are my preferences", "what do you know about me"]):
        details = []
        if facts.get("name"):
            details.append(f"your name is {facts['name']}")
        if facts.get("preference"):
            details.append(f"you like {facts['preference']}")
        if facts.get("goal"):
            details.append(f"you want to {facts['goal']}")
        if topics:
            details.append(f"you've asked about {', '.join(topics[-2:])}")
        if details:
            return f"Here's what I know about you: {'; '.join(details)}."
        return "You haven't shared much personal information yet. Tell me more about yourself!"

    # --- Name introduction ---
    if re.search(r"my name is ([a-z]+)", lower) or re.search(r"i'?m ([a-z]+)\b", lower) or re.search(r"call me ([a-z]+)", lower):
        name = facts.get("name", "there")
        pref_note = ""
        if facts.get("preference"):
            pref_note = f" I'll also remember that you {facts['preference']}."
        return (
            f"Nice to meet you, {name}! I'll remember your name throughout our conversation.{pref_note} "
            f"How can I help you today?"
        )

    # --- Preference statements ("I like X") ---
    if re.search(r"i (?:like|love|enjoy|prefer) ", lower):
        pref = facts.get("preference", "")
        if pref:
            return (
                f"{name_prefix}Got it! I'll remember that you {pref}. "
                f"Feel free to ask me anything related to that, or share more about your preferences!"
            )

    # --- Greetings ---
    if re.match(r"^(hello|hi|hey|good morning|good afternoon|good evening)[!.,]?$", lower):
        if facts.get("name"):
            return (
                f"Hello again, {facts['name']}! Great to continue our conversation. "
                f"We've spoken {turn} time(s) before. What can I help you with today?"
            )
        return (
            "Hello! I'm your conversational assistant. "
            "I remember what you've shared in this session. "
            "What's your name, and how can I help you today?"
        )

    # --- Farewells ---
    if any(kw in lower for kw in ["bye", "goodbye", "see you", "take care", "farewell", "thanks for your help"]):
        if facts.get("name"):
            return (
                f"Goodbye, {facts['name']}! It was great chatting with you. "
                f"We covered {len(topics)} topic(s) in our {turn}-turn conversation. "
                "Feel free to come back anytime!"
            )
        return (
            "Goodbye! It was great chatting with you. "
            f"We had a {turn}-turn conversation. Come back anytime!"
        )

    # --- Follow-up / continuation (context retention demo) ---
    follow_up_words = ["it", "that", "this", "more", "also", "what about", "tell me more", "continue", "go on", "and"]
    is_follow_up = any(lower.startswith(w) for w in follow_up_words) or len(lower.split()) <= 4

    if is_follow_up and topics:
        last_topic = topics[-1]
        return (
            f"Building on what we discussed about {last_topic}, {name_prefix}"
            f"here's more context: this area has several important dimensions worth exploring. "
            f"We've been in conversation for {turn} turn(s) — feel free to go deeper on any aspect."
        )

    # --- Topic-specific demo responses ---
    if any(kw in lower for kw in ["capital", "country", "city", "geography"]):
        # Try to extract the country
        for country, capital in [
            ("japan", "Tokyo"), ("france", "Paris"), ("germany", "Berlin"),
            ("india", "New Delhi"), ("brazil", "Brasília"), ("australia", "Canberra"),
            ("canada", "Ottawa"), ("china", "Beijing"), ("usa", "Washington D.C."),
        ]:
            if country in lower:
                return f"{name_prefix}The capital of {country.capitalize()} is {capital}."
        return f"{name_prefix}I'd be happy to help with geography questions. Which country are you asking about?"

    if any(kw in lower for kw in ["photosynthesis", "plants", "chlorophyll", "biology"]):
        return (
            f"{name_prefix}Photosynthesis is the process plants use to convert sunlight into food. "
            "In simple terms: plants absorb sunlight through chlorophyll (the green pigment), "
            "take in CO₂ from the air and water from the soil, then produce glucose (sugar) for energy "
            "and release oxygen as a byproduct. It's basically a solar-powered food factory!"
        )

    if any(kw in lower for kw in ["weather", "temperature", "forecast"]):
        return (
            f"{name_prefix}I don't have real-time weather data in demo mode, "
            "but I can discuss weather patterns and climate topics. "
            "What specific aspect are you curious about?"
        )

    if any(kw in lower for kw in ["travel", "paris", "trip", "visit", "vacation"]):
        destination = "Paris" if "paris" in lower else "your destination"
        return (
            f"{name_prefix}Traveling to {destination} is a great choice! "
            "Some top tips: book accommodations early, learn a few local phrases, "
            "plan must-see spots in advance but leave room for spontaneous discoveries, "
            "and always check local transport options. Would you like specific recommendations?"
        )

    if any(kw in lower for kw in ["ai", "artificial intelligence", "machine learning", "llm"]):
        return (
            f"{name_prefix}Artificial Intelligence is a broad field focused on building systems "
            "that can perform tasks that typically require human intelligence — like understanding language, "
            "recognizing images, or making decisions. Machine learning is a subset where systems learn "
            "patterns from data rather than following explicit rules. Is there a specific area you'd like to explore?"
        )

    # --- Coffee / tea / drink suggestions ---
    if any(kw in lower for kw in ["coffee", "latte", "cappuccino", "espresso", "mocha", "americano"]):
        return (
            f"{name_prefix}Here are some great coffee drinks for you: "
            "Cappuccino (frothy and creamy), Caramel Latte (sweet and smooth), "
            "Espresso (bold and intense), Mocha (chocolate meets coffee), "
            "or a classic Americano. Would you like to know more about any of these?"
        )

    if any(kw in lower for kw in ["tea", "chai", "matcha", "herbal tea", "green tea"]):
        return (
            f"{name_prefix}Here are some wonderful tea options: "
            "Masala Chai (spiced and warming), Matcha Latte (earthy and energizing), "
            "Earl Grey (classic and aromatic), Chamomile (calming), "
            "or Green Tea (light and refreshing). Which sounds good?"
        )

    # --- Food / dietary / recommendation queries ---
    if any(kw in lower for kw in ["food", "dinner", "lunch", "breakfast", "meal", "eat", "restaurant",
                                    "vegetarian", "vegan", "recipe", "dish", "cuisine"]):
        pref = facts.get("preference", "")
        is_veg = "vegetarian" in pref or "vegetarian" in lower or "vegan" in lower
        if is_veg:
            return (
                f"{name_prefix}Since you prefer vegetarian food, here are some great dinner options: "
                "Paneer Tikka Masala, Mushroom Risotto, Vegetable Pad Thai, "
                "Margherita Pizza, or a hearty Lentil Soup. "
                "Would you like a recipe for any of these?"
            )
        return (
            f"{name_prefix}Here are some dinner suggestions: Grilled Chicken with roasted vegetables, "
            "Pasta Carbonara, Stir-fry with tofu or shrimp, a fresh Caesar Salad, "
            "or a classic Margherita Pizza. Would you like more details on any of these?"
        )

    if any(kw in lower for kw in ["explain", "what is", "how does", "tell me about"]):
        topic_match = re.search(r"(?:explain|what is|how does|tell me about)\s+(.+)", lower)
        topic = topic_match.group(1).strip().rstrip("?") if topic_match else "that topic"
        return (
            f"{name_prefix}Great question about {topic}! "
            f"It's a topic with several key aspects. Here's a clear breakdown:\n\n"
            f"1. At its core, {topic} involves understanding the fundamental principles.\n"
            f"2. In practice, it applies across multiple real-world scenarios.\n"
            f"3. Recent developments have expanded how we think about it.\n\n"
            f"Would you like me to go deeper on any of these points?"
        )

    # --- Default context-aware response ---
    filler_phrases = [
        "That's an interesting point.",
        "I appreciate you bringing that up.",
        "Good question!",
    ]
    filler = random.choice(filler_phrases)
    context_note = (
        f" (Turn {turn + 1} of our conversation"
        + (f", {facts['name']}" if facts.get("name") else "")
        + ")"
    )

    return (
        f"{filler}{context_note} "
        f"I'm here to help and I maintain context across all our turns. "
        f"Could you share more details about what you're looking for? "
        f"The more specific you are, the better I can assist."
    )


# ---------------------------------------------------------------------------
# Optional: Live LLM mode
# ---------------------------------------------------------------------------

async def _live_response(user_input: str, history: List[Dict]) -> Optional[str]:
    """
    Try to get a real LLM response using LLM Gateway (with OAuth2)
    or direct OpenAI API. Returns None if unavailable so caller falls
    back to demo mode.
    """
    global _cached_token, _cached_token_expiry

    # Prefer LLM Gateway (corporate setup with OAuth2)
    gateway_key = os.getenv("LLM_GATEWAY_KEY") or os.getenv("LLM_MODEL_API_KEY")
    gateway_url = os.getenv("LLM_GATEWAY_BASE_URL") or os.getenv("LLM_MODEL_BASE_URL")
    model_name = os.getenv("DEPLOYMENT_MODEL") or os.getenv("LLM_MODEL_NAME") or "gpt-4o-mini"

    if not gateway_key or not gateway_url:
        # Fallback: try direct OpenAI
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key or api_key.startswith("sk-your-"):
            return None
        gateway_key = api_key
        gateway_url = "https://api.openai.com/v1"
        model_name = os.getenv("OPENAI_MODEL") or "gpt-4o-mini"

    try:
        import httpx

        messages = [
            {"role": "system", "content": (
                "You are a helpful conversational assistant with perfect memory. "
                "Always reference relevant things the user has told you earlier in the conversation. "
                "Keep answers concise and directly relevant to the question."
            )}
        ] + history + [{"role": "user", "content": user_input}]

        headers = {
            "Content-Type": "application/json",
            "X-LLM-Gateway-Key": gateway_key,
        }

        # Get OAuth2 token (cached — only refresh when expired)
        client_id = os.getenv("OAUTH_CLIENT_ID")
        client_secret = os.getenv("OAUTH_CLIENT_SECRET")
        tenant_id = os.getenv("OAUTH_TENANT_ID")
        scope = os.getenv("OAUTH_SCOPE")
        if all([client_id, client_secret, tenant_id, scope]):
            import time as _time
            now = _time.time()
            if _cached_token and now < _cached_token_expiry - 60:
                headers["Authorization"] = f"Bearer {_cached_token}"
            else:
                try:
                    token_url = f"https://login.microsoftonline.com/{tenant_id}/oauth2/v2.0/token"
                    async with httpx.AsyncClient(timeout=10.0) as tc:
                        tok_resp = await tc.post(token_url, data={
                            "grant_type": "client_credentials",
                            "client_id": client_id,
                            "client_secret": client_secret,
                            "scope": scope,
                        })
                        tok_resp.raise_for_status()
                        tok_data = tok_resp.json()
                        _cached_token = tok_data["access_token"]
                        _cached_token_expiry = now + tok_data.get("expires_in", 3600)
                        headers["Authorization"] = f"Bearer {_cached_token}"
                except Exception as tok_err:
                    logger.warning(f"OAuth2 token request failed: {tok_err}")
                    if _cached_token:
                        headers["Authorization"] = f"Bearer {_cached_token}"

        chat_url = f"{gateway_url.rstrip('/')}/chat/completions"
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                chat_url,
                headers=headers,
                json={"model": model_name, "messages": messages, "max_tokens": 500},
            )
            if resp.status_code == 200:
                return resp.json()["choices"][0]["message"]["content"]
            else:
                logger.warning(f"LLM call returned {resp.status_code}: {resp.text[:200]}")
    except Exception as e:
        logger.warning(f"Live LLM call failed, falling back to demo: {e}")
    return None


# ---------------------------------------------------------------------------
# FastAPI app
# ---------------------------------------------------------------------------

app = FastAPI(
    title="Conversational Agent",
    description=(
        "A stateful conversational agent that remembers context across turns. "
        "Designed for evaluation with coherence and context_retention metrics."
    ),
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# Request / Response models
# ---------------------------------------------------------------------------

class ChatMessage(BaseModel):
    role: str = Field(..., description="'user' or 'assistant'")
    content: str


class ChatRequest(BaseModel):
    """
    Flexible chat request — supports multiple input formats so the
    Agent Eval platform's executor can call this endpoint with any payload shape.
    """
    # Primary field used by Lilly Agent Eval platform
    input: Optional[str] = Field(None, description="User message (platform format)")

    # OpenAI-style messages array (also accepted)
    messages: Optional[List[ChatMessage]] = Field(None, description="Full conversation history")

    # Session tracking (optional — if not supplied, each call is stateless)
    session_id: Optional[str] = Field(None, description="Session ID for persistent memory")

    # Conversation history from platform (turn-level evaluation)
    conversation_history: Optional[List[ChatMessage]] = Field(
        None, description="Prior turns passed by the eval platform"
    )


class ChatResponse(BaseModel):
    output: str
    session_id: str
    turn_number: int
    topics_remembered: List[str] = []
    latency_ms: int
    trace: Optional[List[Dict[str, Any]]] = None


class InfoResponse(BaseModel):
    name: str
    version: str
    agent_type: str
    description: str
    capabilities: List[str]
    suggested_metrics: List[str]
    endpoint: str


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@app.get("/")
async def root():
    return {
        "name": "Conversational Agent",
        "version": "1.0.0",
        "agent_type": "conversational",
        "endpoints": {
            "/chat": "POST - Main conversational chat endpoint",
            "/health": "GET  - Health check",
            "/info":   "GET  - Agent capabilities",
        },
    }


@app.get("/health")
async def health():
    live_mode = bool(os.getenv("OPENAI_API_KEY"))
    return {
        "status": "healthy",
        "mode": "live" if live_mode else "demo",
        "agent_type": "conversational",
        "active_sessions": len(_sessions),
    }


@app.get("/info", response_model=InfoResponse)
async def info():
    """Structured agent capabilities — used by the platform's agent discovery."""
    return InfoResponse(
        name="Conversational Agent",
        version="1.0.0",
        agent_type="conversational",
        description=(
            "A stateful conversational agent that maintains memory across all turns. "
            "It remembers user names, topics discussed, preferences, and goals. "
            "Ideal for testing coherence and context retention in multi-turn evaluations."
        ),
        capabilities=[
            "multi-turn conversation",
            "context retention",
            "user name/preference memory",
            "topic continuity",
            "coherent follow-up responses",
            "graceful handling of unclear queries",
            "safety guardrails (refuses harmful requests)",
        ],
        suggested_metrics=["answer_relevancy", "coherence", "context_retention", "toxicity"],
        endpoint="http://localhost:8003/chat",
    )


@app.post("/chat", response_model=ChatResponse)
async def chat(request: ChatRequest):
    """
    Main conversational endpoint.
    Same input/output contract as before.
    """
    start = time.time()

    # --- Resolve user message (before graph) ---
    user_message: str = ""
    if request.input:
        user_message = request.input.strip()
    elif request.messages:
        user_msgs = [m for m in request.messages if m.role == "user"]
        if not user_msgs:
            raise HTTPException(status_code=422, detail="No user message found in messages array")
        user_message = user_msgs[-1].content.strip()
    else:
        raise HTTPException(status_code=422, detail="Provide 'input' or 'messages' field")
    if not user_message:
        raise HTTPException(status_code=422, detail="User message cannot be empty")

    # --- Pipeline node functions ---

    def load_session_node(state: dict) -> dict:
        """Node 1: Load or create session, seed history."""
        state = dict(state)
        state["intermediate"] = dict(state.get("intermediate", {}))
        session_id = request.session_id or str(uuid.uuid4())
        session = _sessions[session_id]

        # Seed session history from conversation_history if platform passed it
        if request.conversation_history and not session["history"]:
            for msg in request.conversation_history:
                session["history"].append({"role": msg.role, "content": msg.content})
        if request.messages and not session["history"]:
            for msg in request.messages[:-1]:
                session["history"].append({"role": msg.role, "content": msg.content})

        history_before = list(session["history"])
        session["history"].append({"role": "user", "content": user_message})

        state["intermediate"]["session_id"] = session_id
        state["intermediate"]["history_before"] = history_before

        # Descriptive summary for trace visualization
        turn_count = sum(1 for m in history_before if m.get("role") == "user")
        state["_node_summary"] = f"Loaded session with {turn_count} prior turn(s), {len(history_before)} messages"
        return state

    async def generate_node(state: dict) -> dict:
        """Node 2: Generate response (live LLM or demo)."""
        state = dict(state)
        history_before = state["intermediate"]["history_before"]

        output = await _live_response(user_message, history_before)
        is_live = output is not None
        if not output:
            output = _build_demo_response(user_message, history_before)

        state["output"] = output

        # Descriptive summary for trace visualization
        mode = "LLM" if is_live else "Demo"
        state["_node_summary"] = f"Generated {len(output.split())}-word response ({mode} mode)"
        return state

    def save_session_node(state: dict) -> dict:
        """Node 3: Save assistant turn and extract metadata."""
        state = dict(state)
        session_id = state["intermediate"]["session_id"]
        session = _sessions[session_id]

        session["history"].append({"role": "assistant", "content": state["output"]})

        facts = _extract_context_facts(session["history"])
        state["metadata"] = dict(state.get("metadata", {}))
        state["metadata"]["session_id"] = session_id
        state["metadata"]["turn_number"] = facts.get("turn_count", 1)
        state["metadata"]["topics"] = facts.get("topics", [])

        # Descriptive summary for trace visualization
        remembered = []
        if facts.get("name"): remembered.append(f"name={facts['name']}")
        if facts.get("preference"): remembered.append(f"pref={facts['preference'][:20]}")
        if facts.get("topics"): remembered.append(f"{len(facts['topics'])} topic(s)")
        state["_node_summary"] = f"Saved turn {facts.get('turn_count', 1)}. Memory: {', '.join(remembered) if remembered else 'no facts yet'}"
        return state

    # --- Build the pipeline ---
    state = {"query": user_message, "intermediate": {}, "tool_calls": [], "output": "", "errors": [], "metadata": {}}
    state = load_session_node(state)
    state = await generate_node(state)
    state = save_session_node(state)

    # --- Return response ---
    meta = state.get("metadata", {})
    latency_ms = int((time.time() - start) * 1000) + random.randint(10, 50)

    return ChatResponse(
        output=state.get("output", ""),
        session_id=meta.get("session_id", ""),
        turn_number=meta.get("turn_number", 1),
        topics_remembered=meta.get("topics", []),
        latency_ms=latency_ms,
    )


@app.delete("/sessions/{session_id}")
async def clear_session(session_id: str):
    """Clear a specific session's memory."""
    if session_id in _sessions:
        del _sessions[session_id]
        return {"cleared": True, "session_id": session_id}
    return {"cleared": False, "session_id": session_id, "detail": "Session not found"}


@app.get("/sessions/{session_id}/history")
async def get_session_history(session_id: str):
    """Inspect a session's conversation history (useful for debugging)."""
    if session_id not in _sessions:
        raise HTTPException(status_code=404, detail="Session not found")
    session = _sessions[session_id]
    facts = _extract_context_facts(session["history"])
    return {
        "session_id": session_id,
        "turn_count": facts.get("turn_count", 0),
        "history": session["history"],
        "remembered_facts": {k: v for k, v in facts.items() if k not in ("topics", "turn_count")},
        "topics": facts.get("topics", []),
    }


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import uvicorn
    print("=" * 55)
    print("  Conversational Agent  (Lilly Agent Eval sample)")
    print("  Listening on http://0.0.0.0:8003")
    print("  Mode:", "LIVE (OpenAI)" if os.getenv("OPENAI_API_KEY") else "DEMO (no API key needed)")
    print("  Endpoints: GET /health  GET /info  POST /chat")
    print("=" * 55)
    uvicorn.run(app, host="0.0.0.0", port=8003, log_level="info")
