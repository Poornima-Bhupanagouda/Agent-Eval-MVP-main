# Travel Orchestrator: Complete Beginner Explanation

## Quick Answer to Your Questions

1. **Is Travel Orchestrator registered or built?**  
   → Built INTO the project. It's a Python file (`sample_agents/travel_orchestrator.py`) that creates an HTTP service, then the Eval platform auto-registers it on startup.

2. **How does evaluation work?**  
   → Eval sends user input → Orchestrator runs internally (not Eval) → Orchestrator calls 3 sub-agents → Combines responses → Returns final answer → Eval scores that answer.

3. **How do we evaluate a multi-agent?**  
   → Same way as single agent: send input → get output → score output. The fact it's multi-agent inside is invisible to Eval.

---

## PART 1: What is Travel Orchestrator?

### Simple Definition
Travel Orchestrator is a **coordinator agent** that:
- Takes a travel question from you
- Figures out which specialist agents to call
- Calls Weather, Wiki, and Calculator agents in parallel
- Combines their answers
- Returns one unified response

### Real-World Analogy
Think of a travel agency:
- You ask: "Plan a trip to Tokyo"
- Agency decides: "Need weather info, destination facts, AND currency data"
- Agency calls:
  - Weather service
  - Tour guide
  - Currency exchange
- Agency combines all answers into one travel plan
- Gives you the result

That's Travel Orchestrator.

---

## PART 2: Where is it Built?

### File Location
```
sample_agents/travel_orchestrator.py
```

### What's Inside (High Level)
1. **Sub-agent definitions** (lines 30-38)
   ```python
   SUB_AGENTS = {
       "weather_agent": {"url": "http://127.0.0.1:8004/chat", ...},
       "wiki_agent": {"url": "http://127.0.0.1:8005/chat", ...},
       "calculator_agent": {"url": "http://127.0.0.1:8006/chat", ...},
   }
   ```
   This says: "Here are my 3 helper agents and where they live."

2. **Routing logic** (`route_query()` function, lines 42-78)
   ```python
   if "trip" in text.lower():
       agents = {"weather_agent", "wiki_agent", "calculator_agent"}
   ```
   This says: "When user says 'trip', call ALL agents."

3. **Sub-agent calling** (`call_agent()` function, lines 104-126)
   Makes HTTP POST requests to sub-agents.

4. **Response synthesis** (`synthesize_responses()` function, lines 129-166)
   Combines all 3 agent responses into one nice answer.

5. **FastAPI server** (lines 259-298)
   Exposes `/chat` endpoint on port 8010.

---

## PART 3: How is it Registered in the Project?

### Registration Step 1: Manual Start (You Do This)
```powershell
python sample_agents/travel_orchestrator.py
```
→ Starts HTTP server on `http://127.0.0.1:8010`

### Registration Step 2: Auto-Discovery (Eval Does This)
File: `agent_eval/web/app.py`, lines 61-66

```python
STANDALONE_AGENTS = [
    {"name": "Travel Orchestrator", 
     "endpoint": "http://127.0.0.1:8010/chat", 
     "port": 8010, ...},
    # ... other agents
]
```

Then on startup (lines 73-110):
```python
@app.on_event("startup")
async def startup_register():
    for agent_def in STANDALONE_AGENTS:
        # Try to reach agent on that port
        resp = client.get(f"http://127.0.0.1:{port}/health")
        if resp.status_code == 200:
            # Agent is alive! Register it.
            storage.save_agent(agent)
```

### In Plain English
1. Eval platform knows Travel Orchestrator should be at 8010.
2. When Eval starts, it checks: "Is anything on 8010?"
3. If yes → "Welcome! You're registered."
4. If no → "You'll be registered when you start."

---

## PART 4: How Travel Orchestrator Works Internally (Deep Dive)

### Step-by-Step Internal Flow

#### Step 1: User Sends Question
```
Input: "Plan a 3-day trip to Tokyo with budget tips"
```

#### Step 2: Determine Which Agents to Call
Function: `route_query()` (lines 42-78 in travel_orchestrator.py)

```python
text = "Plan a 3-day trip to Tokyo with budget tips"
lower = text.lower()

# Check keywords
if "trip" in lower:
    agents = {"weather_agent", "wiki_agent", "calculator_agent"}
```

**Result**: Call ALL 3 agents (because "trip" is a travel keyword)

#### Step 3: Transform Query for Each Agent
Function: `build_agent_input()` (lines 81-95)

Original input sent to each agent DIFFERENTLY:
- **Weather Agent** gets: "What's the weather forecast for Tokyo?"
- **Wiki Agent** gets: "Tell me about Tokyo"
- **Calculator Agent** gets: "Country info about Tokyo"

Why? Each agent specializes, so ask it specially.

#### Step 4: Call All 3 Agents in Parallel
Function: `call_agent()` (lines 104-126)

```python
async def call_agent(agent_id, input_text):
    # Make HTTP POST to that agent
    resp = await client.post(
        WEATHER_URL,  # http://127.0.0.1:8004/chat
        json={"input": input_text}
    )
    return resp.json()  # Get response
```

**Parallel means**: Call all 3 at the same time, not one after another.

#### Step 5: Combine All Responses
Function: `synthesize_responses()` (lines 129-166)

```
Weather Agent says: "Tokyo: sunny, 22°C, low rain risk"
Wiki Agent says: "Tokyo is the capital of Japan, famous for tech and culture"
Calculator Agent says: "Currency: JPY, 1 USD = 150 JPY, population 14M"

Combine INTO:
"Travel Briefing: Tokyo
=== Weather Forecast ===
sunny, 22°C, low rain risk

=== Background & Overview ===
Tokyo is the capital of Japan...

=== Country & Currency Data ===
Currency: JPY..."
```

#### Step 6: Return Final Response
Orchestrator returns this combined text via `/chat` endpoint.

---

## PART 5: How Evaluation Works with Travel Orchestrator

### The Full Evaluation Flow

```
┌─────────────────────────────────────────────────────────┐
│ YOU (User): Click "Run Test" in UI                      │
└─────────────┬───────────────────────────────────────────┘
              │
              ▼
┌─────────────────────────────────────────────────────────┐
│ EVAL PLATFORM: /api/test endpoint                       │
│ (agent_eval/web/app.py, lines 345-410)                  │
│                                                         │
│ Request contains:                                       │
│ - endpoint: "http://127.0.0.1:8010/chat"              │
│ - input: "Plan a trip to Tokyo"                        │
│ - expected: "Tokyo is a great destination"             │
│ - metrics: ["answer_relevancy", "similarity"]          │
└─────────────┬───────────────────────────────────────────┘
              │
              ▼
┌─────────────────────────────────────────────────────────┐
│ EXECUTOR: Execute agent                                │
│ (agent_eval/core/executor.py, lines 49-100)           │
│                                                         │
│ Step 1: Make HTTP request                             │
│   POST http://127.0.0.1:8010/chat                     │
│   Body: {"input": "Plan a trip to Tokyo"}             │
└─────────────┬───────────────────────────────────────────┘
              │
              ▼
┌─────────────────────────────────────────────────────────┐
│ TRAVEL ORCHESTRATOR (Internal Processing)              │
│ (sample_agents/travel_orchestrator.py)                 │
│                                                         │
│ Step 1: route_query("Plan a trip to Tokyo")           │
│   → ["weather_agent", "wiki_agent", "calculator"]     │
│                                                         │
│ Step 2: Transform for each agent:                      │
│   - Weather: "Weather in Tokyo?"                       │
│   - Wiki: "Tell me about Tokyo"                        │
│   - Calc: "Country info about Tokyo"                   │
│                                                         │
│ Step 3: Call all 3 agents in parallel:                │
│   - 8004/chat (Weather)                              │
│   - 8005/chat (Wiki)                                  │
│   - 8006/chat (Calculator)                            │
│                                                         │
│ Step 4: Combine responses                             │
│   Combined output = full travel briefing              │
└─────────────┬───────────────────────────────────────────┘
              │
              ▼ (Returns to Evaluator)
┌─────────────────────────────────────────────────────────┐
│ EXECUTOR: Receives combined response                    │
│                                                         │
│ output: "Travel Briefing: Tokyo..."                    │
│ latency_ms: 2500                                       │
│ status_code: 200                                       │
└─────────────┬───────────────────────────────────────────┘
              │
              ▼
┌─────────────────────────────────────────────────────────┐
│ EVALUATOR: Score the output                            │
│ (agent_eval/core/evaluator.py, lines 106-168)         │
│                                                         │
│ Input to scorer:                                       │
│ - input_text: "Plan a trip to Tokyo"                  │
│ - output: "Travel Briefing: Tokyo..."                 │
│ - expected: "Tokyo is a great destination"            │
│ - metrics: ["answer_relevancy", "similarity"]         │
│                                                         │
│ For each metric:                                       │
│ - "answer_relevancy": Does out PUT answer the query?  │
│   → 85% (YES, it has all info)                        │
│ - "similarity": How close to expected text?           │
│   → 72% (somewhat similar)                            │
│                                                         │
│ Final score: (85 + 72) / 2 = 78.5%                   │
│ Passed? YES (78.5 > 70 threshold)                     │
└─────────────┬───────────────────────────────────────────┘
              │
              ▼
┌─────────────────────────────────────────────────────────┐
│ STORAGE: Save result to database                        │
│                                                         │
│ Stored:                                                 │
│ {                                                       │
│   "id": "uuid",                                         │
│   "endpoint": "http://127.0.0.1:8010/chat",           │
│   "input": "Plan a trip to Tokyo",                    │
│   "output": "Travel Briefing: Tokyo...",              │
│   "score": 78.5,                                       │
│   "passed": true,                                      │
│   "latency_ms": 2500,                                  │
│   "evaluations": [                                     │
│     {"metric": "answer_relevancy", "score": 85, ...}, │
│     {"metric": "similarity", "score": 72, ...}        │
│   ]                                                    │
│ }                                                       │
└─────────────┬───────────────────────────────────────────┘
              │
              ▼
┌─────────────────────────────────────────────────────────┐
│ UI: Display Results                                     │
│                                                         │
│ Dashboard shows:                                        │
│ ✓ PASSED (78.5%)                                       │
│ Output: "Travel Briefing: Tokyo..."                    │
│ Latency: 2.5 seconds                                   │
│ Metrics: [answer_relevancy: 85%, similarity: 72%]     │
└─────────────────────────────────────────────────────────┘
```

---

## PART 6: Key Concept - Why It Works This Way

### Concept 1: Orchestrator is a BLACK BOX to Evaluator

**From Eval's perspective:**
- "I call http://127.0.0.1:8010/chat"
- "I get back a response"
- "I don't care if it's single-agent or multi-agent"
- "I only score the FINAL output"

**You don't test the sub-agents during orchestrator eval** because the orchestrator INTERNALLY decides when/how to call them.

### Concept 2: Multi-Agent Means INTERNAL Complexity

**Inside the Orchestrator:**
```
Input → Routing → Parallel Calls → Combining → Output
```

**From Eval's View:**
```
Input → [BLACK BOX] → Output
```

Eval only sees the black box. What's inside doesn't matter.

### Concept 3: Evaluation Metrics Work The Same

Whether you evaluate:
- A simple single agent (8003)
- A complex multi-agent (8010)

The metrics are the same:
- Does it answer the question? (answer_relevancy)
- Is it similar to expected? (similarity)
- Does it contain toxic language? (toxicity)

The **output quality** is what matters, not **how** it was generated.

---

## PART 7: Step-By-Step Test Instructions

### 6 Commands to Test Everything

#### Terminal 1: Weather Agent
```powershell
python sample_agents/weather_agent.py
# Waits listening on http://127.0.0.1:8004
```

#### Terminal 2: Wiki Agent
```powershell
python sample_agents/wiki_agent.py
# Waits listening on http://127.0.0.1:8005
```

#### Terminal 3: Calculator Agent
```powershell
python sample_agents/calculator_agent.py
# Waits listening on http://127.0.0.1:8006
```

#### Terminal 4: Travel Orchestrator
```powershell
python sample_agents/travel_orchestrator.py
# Waits listening on http://127.0.0.1:8010
# Will internally call 8004, 8005, 8006
```

#### Terminal 5: Eval Platform
```powershell
python -m agent_eval.cli start --port 8000
# Opens http://127.0.0.1:8000
```

#### Terminal 6: Quick Test (Optional)
```powershell
$body = @{ input = "Plan a trip to Tokyo" } | ConvertTo-Json
Invoke-WebRequest -Uri http://127.0.0.1:8010/chat -Method Post `
  -ContentType application/json -Body $body -UseBasicParsing
# Returns: full travel briefing
```

### Then in Browser
1. Open http://127.0.0.1:8000
2. Endpoint: `http://127.0.0.1:8010/chat`
3. Input: `Plan 3-day trip to Paris with budget`
4. Expected: `Paris is a beautiful city`
5. Metrics: `answer_relevancy, similarity`
6. Click Run Test

Result: You see score, latency, and whether it passed.

---

## PART 8: Key Differences - Single vs Multi-Agent

| Aspect | Single Agent (8003 RAG) | Multi-Agent (8010 Orchestrator) |
|--------|-------------------------|--------------------------------|
| **What it does** | Answers questions from KB | Coordinates 3 specialists |
| **How it gets input** | Directly queries KB | Decides which agents to route to |
| **Response time** | Fast (single lookup) | Slower (parallel 3 calls + combine) |
| **Eval process** | Send q → get answer → score answer | Send q → orchestrator calls 3 → combines → score |
| **What Eval scores** | The KB answer | The COMBINED answer |
| **Complexity visible to Eval** | None (single endpoint) | None (still just 1 endpoint) |

---

## PART 9: Common Beginner Questions Answered

### Q: If Travel Orchestrator calls 3 agents, doesn't Eval evaluate all 3?
**A:** No. Eval only evaluates **what Travel Orchestrator returns**. Eval doesn't know about the 3 internal agents.

It's like ordering food via a restaurant website:
- Restaurant internally might call 5 suppliers
- You only care about final plate
- Restaurant is evaluated on final plate quality

### Q: Why not just use 1 agent instead of 3?
**A:** Because:
- Weather Agent is specialized (uses weather APIs)
- Wiki Agent is specialized (uses Wikipedia)
- Calculator Agent is specialized (currency/math)
- Together they give better travel advice than any 1 could alone

### Q: Can I evaluate just 1 sub-agent (like Weather) directly?
**A:** Yes! Instead of 8010, use 8004:
```
Endpoint: http://127.0.0.1:8004/chat
Input: "What is weather in Tokyo?"
```
This bypasses orchestrator entirely.

### Q: What happens if 1 sub-agent fails?
**A:** Travel Orchestrator catches the error and continues:
```python
except httpx.ConnectError:
    return {
        "output": "Weather Agent is not available",
        "success": False,
        "error": "Connection refused",
    }
```
Then synthesizer combines the working responses only.

### Q: Is latency 2-3 seconds because of multi-agent?
**A:** Yes. Because:
- Orchestrator → decides routing (~50ms)
- 3 agents called in parallel (~2000ms each, but parallel)
- Synthesis (~100ms)
- Total: ~2100ms (bottleneck is slowest agent)

If called sequentially: 3 × 2000ms = 6000ms.
Parallel saves time.

---

## PART 10: Visual Summary

### Registration & Auto-Discovery
```
You Start:              Eval Starts:         Result:
┌──────────────┐      ┌──────────────┐      ┌──────────────┐
│ Terminal 1   │      │ Check ports: │      │ Registered   │
│ travel_orch  │      │ 8003? ✓      │      │ 5 agents:    │
│ :8010        │      │ 8004? ✓      │      │ - HR RAG     │
│              │  →   │ 8005? ✓      │  →   │ - Weather    │
│              │      │ 8006? ✓      │      │ - Wiki       │
│              │      │ 8010? ✓      │      │ - Calculator │
│              │      │              │      │ - Orchestr.  │
└──────────────┘      └──────────────┘      └──────────────┘
```

### Evaluation Flow
```
You send Q          Orchestr processes         Eval scores
┌─────────────┐    ┌──────────────────────┐    ┌───────────┐
│"Plan trip   │    │Route to 3 agents    │    │Answer:85% │
│to Paris"    │ → │(parallel calls)      │ → │Similarity:│
│             │    │Combine responses     │    │72%        │
│             │    │Return: "Travel Brief"│    │PASS: 78%  │
└─────────────┘    └──────────────────────┘    └───────────┘
```

---

## Summary for a Beginner

1. **Travel Orchestrator is built-in** to the project (Python file).
2. **It auto-registers** when you start it (Eval discovers it).
3. **It works internally with 3 agents**, but Eval doesn't know/care.
4. **Eval evaluates only the FINAL output**, not the internal agents.
5. **The entire process is same as single-agent** from evaluation perspective.
6. **You test it** by: start all agents → start eval → enter endpoint → run test.

**Think of it as a restaurant**: customers order through 1 counter, restaurant internally uses 5 kitchens, but customer only cares about food quality on the plate.

