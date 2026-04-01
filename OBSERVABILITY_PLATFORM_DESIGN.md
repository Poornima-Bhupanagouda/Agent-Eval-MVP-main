# Agent Eval - Next Generation Observability Platform Design

## Lessons from Industry Leaders

### What Makes Langfuse Great
1. **Trace-First Architecture**
   - Everything is a trace (conversations, single calls, multi-step agents)
   - Traces contain spans → spans contain generations
   - Full hierarchy visibility

2. **Decorator-Based Instrumentation**
   ```python
   from langfuse.decorators import observe

   @observe()
   def my_agent(input: str) -> str:
       # Your agent code - automatically traced!
       return result
   ```

3. **Datasets with Versioning**
   - Test cases are versioned
   - Track improvements over time
   - Compare runs across dataset versions

4. **Integrated Scoring**
   - Human scores + LLM-as-judge
   - Multiple dimensions (accuracy, relevance, safety)
   - Scores linked to traces

### What Makes Maxim AI Great
1. **Guided Workflow**
   - Step-by-step wizard
   - No code required for basic testing
   - Visual configuration

2. **Auto-Generate Expected Outputs**
   - Use LLM to suggest expected outputs
   - User can edit/approve
   - Reduces manual work by 80%

3. **Conversation-Level Testing**
   - Multi-turn evaluation
   - Context preservation
   - Memory testing

### What Makes Arize Phoenix Great
1. **OpenTelemetry Native**
   - Industry standard tracing
   - Works with existing observability stack
   - Vendor neutral

2. **Embedding Analysis**
   - Visualize embeddings
   - Detect drift
   - Cluster analysis

3. **Guardrails Integration**
   - Built-in safety checks
   - Content moderation
   - PII detection

---

## Agent Eval v3.0 - Design Proposal

### Core Philosophy
> "Zero to evaluation in 60 seconds, enterprise-grade at scale"

### User Journey

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                           STEP 1: CONNECT                                    │
│                                                                              │
│  How does your agent work?                                                   │
│                                                                              │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐      │
│  │  REST    │  │  Python  │  │ LangChain│  │  OpenAI  │  │  Custom  │      │
│  │  API     │  │ Function │  │  Agent   │  │  API     │  │  SDK     │      │
│  └──────────┘  └──────────┘  └──────────┘  └──────────┘  └──────────┘      │
│                                                                              │
│  [Smart Detection: Paste your code/URL and we'll figure it out]             │
└─────────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                           STEP 2: TEST INPUT                                 │
│                                                                              │
│  What do you want to test?                                                   │
│                                                                              │
│  ┌─────────────────────────────────────────────────────────────────────┐    │
│  │ "Summarize this document about climate change..."                   │    │
│  └─────────────────────────────────────────────────────────────────────┘    │
│                                                                              │
│  [💡 Generate Test Cases] [📁 Upload Dataset] [📋 Use Template]             │
└─────────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                           STEP 3: RUN & OBSERVE                              │
│                                                                              │
│  ┌─ Trace: tr_abc123 ──────────────────────────────────────────────────┐    │
│  │                                                                      │    │
│  │  ┌─ Agent Call ─────────────────────────────────────────────────┐   │    │
│  │  │  Input: "Summarize this document..."                         │   │    │
│  │  │  Duration: 2.3s | Tokens: 1,234 | Cost: $0.02               │   │    │
│  │  │                                                              │   │    │
│  │  │  ┌─ LLM Call (GPT-4) ─────────────────────────────────────┐ │   │    │
│  │  │  │  Prompt: [System: You are...] [User: Summarize...]     │ │   │    │
│  │  │  │  Response: "The document discusses..."                  │ │   │    │
│  │  │  │  Tokens: 456 in / 234 out | Latency: 1.8s              │ │   │    │
│  │  │  └────────────────────────────────────────────────────────┘ │   │    │
│  │  │                                                              │   │    │
│  │  │  ┌─ Tool Call: search_web ─────────────────────────────────┐ │   │    │
│  │  │  │  Args: {"query": "climate change statistics 2024"}      │ │   │    │
│  │  │  │  Result: [3 results]                                    │ │   │    │
│  │  │  └────────────────────────────────────────────────────────┘ │   │    │
│  │  │                                                              │   │    │
│  │  └──────────────────────────────────────────────────────────────┘   │    │
│  │                                                                      │    │
│  │  Output: "The document analyzes climate change impacts..."           │    │
│  └──────────────────────────────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                           STEP 4: EXPECTED OUTPUT                            │
│                                                                              │
│  What should the output look like?                                           │
│                                                                              │
│  ┌─ Auto-Generated Suggestion ──────────────────────────────────────────┐   │
│  │                                                                       │   │
│  │  Based on your input, we suggest:                                    │   │
│  │                                                                       │   │
│  │  "A concise summary covering: 1) Main thesis about climate          │   │
│  │   change, 2) Key statistics, 3) Proposed solutions"                 │   │
│  │                                                                       │   │
│  │  [✓ Accept]  [✏️ Edit]  [🔄 Regenerate]  [Skip - Use Evaluators]    │   │
│  └───────────────────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                           STEP 5: EVALUATE                                   │
│                                                                              │
│  How do you want to evaluate?                                                │
│                                                                              │
│  Automatic Evaluators:                                                       │
│  ┌────────────────┐ ┌────────────────┐ ┌────────────────┐                   │
│  │ ☑ Relevance    │ │ ☑ Faithfulness │ │ ☑ Toxicity     │                   │
│  │   (LLM Judge)  │ │   (RAG Check)  │ │   (Safety)     │                   │
│  └────────────────┘ └────────────────┘ └────────────────┘                   │
│  ┌────────────────┐ ┌────────────────┐ ┌────────────────┐                   │
│  │ ☐ Bias Check   │ │ ☑ Format       │ │ ☐ Custom Rule  │                   │
│  │   (Fairness)   │ │   (JSON/etc)   │ │   (Your own)   │                   │
│  └────────────────┘ └────────────────┘ └────────────────┘                   │
│                                                                              │
│  Comparison Mode:                                                            │
│  ○ Exact Match  ○ Semantic Similarity  ● LLM-as-Judge  ○ Rule-Based         │
│                                                                              │
│  [🚀 Run Evaluation]                                                        │
└─────────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                           STEP 6: RESULTS                                    │
│                                                                              │
│  ┌─ Evaluation Results ─────────────────────────────────────────────────┐   │
│  │                                                                       │   │
│  │  Overall Score: 87/100  ✓ PASSED                                     │   │
│  │                                                                       │   │
│  │  ┌─────────────────────────────────────────────────────────────────┐ │   │
│  │  │  Relevance       ████████████████████░░  85%  ✓                 │ │   │
│  │  │  Faithfulness    █████████████████████░  92%  ✓                 │ │   │
│  │  │  Toxicity        ████████████████████░░  0%   ✓ (Lower=Better)  │ │   │
│  │  │  Format          █████████████████████░  95%  ✓                 │ │   │
│  │  └─────────────────────────────────────────────────────────────────┘ │   │
│  │                                                                       │   │
│  │  [📊 View Details] [💾 Save to Dataset] [🔄 Re-run] [📤 Export]     │   │
│  └───────────────────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## Key Features to Implement

### 1. Smart Agent Detection
- User pastes code/URL/config
- System auto-detects agent type
- Pre-fills configuration

```python
# User pastes:
from openai import OpenAI
client = OpenAI()

def my_agent(question):
    response = client.chat.completions.create(
        model="gpt-4",
        messages=[{"role": "user", "content": question}]
    )
    return response.choices[0].message.content

# System detects:
# - OpenAI SDK usage
# - Function signature
# - Model being used
# - Auto-generates wrapper
```

### 2. Auto-Generate Expected Outputs
Use LLM to generate expected outputs based on:
- Input content
- Agent type/purpose
- Previous examples

```python
async def generate_expected_output(
    input: str,
    agent_description: str,
    examples: List[Dict] = None
) -> str:
    """Use LLM to generate suggested expected output."""
    prompt = f"""
    Given this agent description: {agent_description}
    And this input: {input}

    Generate what a good expected output would look like.
    Focus on:
    - Key information that should be present
    - Appropriate tone/format
    - Required elements

    Output should be editable by user.
    """
    return await llm.generate(prompt)
```

### 3. Trace Hierarchy System
```python
@dataclass
class Trace:
    id: str
    name: str
    input: str
    output: str
    start_time: datetime
    end_time: datetime
    spans: List[Span]
    metadata: Dict
    scores: List[Score]

@dataclass
class Span:
    id: str
    trace_id: str
    parent_span_id: Optional[str]
    name: str
    type: SpanType  # LLM_CALL, TOOL_CALL, RETRIEVAL, etc.
    input: Any
    output: Any
    start_time: datetime
    end_time: datetime
    metadata: Dict  # tokens, cost, model, etc.

@dataclass
class Generation:
    """Specific LLM call within a span"""
    span_id: str
    model: str
    prompt: str
    completion: str
    input_tokens: int
    output_tokens: int
    cost: float
    latency_ms: int
```

### 4. Dataset Management with Versioning
```python
class Dataset:
    id: str
    name: str
    description: str
    version: int
    items: List[DatasetItem]
    created_at: datetime

class DatasetItem:
    id: str
    input: str
    expected_output: Optional[str]
    metadata: Dict
    tags: List[str]

# Operations:
- Create dataset from traces
- Add items manually
- Import from CSV/JSON
- Version when modified
- Compare runs across versions
```

### 5. Evaluation Modes

| Mode | Use Case | How It Works |
|------|----------|--------------|
| **Exact Match** | Deterministic outputs | String comparison |
| **Semantic Similarity** | Meaning matters | Embedding cosine similarity |
| **LLM-as-Judge** | Complex/subjective | Another LLM evaluates |
| **Rule-Based** | Specific requirements | Contains/format checks |
| **Human-in-Loop** | Final verification | Manual scoring UI |

### 6. Langfuse Integration Strategy

**Option A: Use Langfuse as Backend**
- Agent Eval becomes a testing frontend
- Langfuse handles all tracing/storage
- Best for users already using Langfuse

**Option B: Langfuse-Compatible Export**
- Agent Eval has its own tracing
- Export traces to Langfuse format
- User chooses where to send data

**Option C: Hybrid (Recommended)**
- Native tracing in Agent Eval
- One-click sync to Langfuse
- Best of both worlds

```python
# Example integration
from langfuse import Langfuse

langfuse = Langfuse()

class AgentEvalWithLangfuse:
    async def run_and_trace(self, agent, input):
        # Create Langfuse trace
        trace = langfuse.trace(name="agent_eval_test")

        # Run agent with instrumentation
        with trace.span(name="agent_execution"):
            result = await agent.run(input)

        # Add evaluation scores
        trace.score(name="relevance", value=0.85)
        trace.score(name="safety", value=1.0)

        return result
```

---

## Implementation Phases

### Phase 1: Guided Workflow (Week 1-2)
- [ ] Redesign UI with step-by-step wizard
- [ ] Smart agent detection
- [ ] Visual configuration builder
- [ ] One-click test execution

### Phase 2: Auto-Generation (Week 2-3)
- [ ] Expected output generation via LLM
- [ ] Test case suggestions
- [ ] Evaluation criteria suggestions
- [ ] Smart defaults based on agent type

### Phase 3: Tracing System (Week 3-4)
- [ ] Trace/Span/Generation data models
- [ ] Automatic instrumentation decorators
- [ ] Visual trace explorer UI
- [ ] Cost/latency aggregation

### Phase 4: Dataset Management (Week 4-5)
- [ ] Dataset CRUD operations
- [ ] Version control
- [ ] Import/export (CSV, JSON, Langfuse format)
- [ ] Dataset-based batch testing

### Phase 5: Langfuse Integration (Week 5-6)
- [ ] Langfuse SDK integration
- [ ] Bi-directional sync
- [ ] Trace export to Langfuse
- [ ] Import evaluations from Langfuse

### Phase 6: Production Features (Week 6-8)
- [ ] Scheduled evaluations
- [ ] Regression detection
- [ ] Alerts on quality drops
- [ ] Multi-environment support (dev/staging/prod)

---

## Database Schema (SQLite/PostgreSQL)

```sql
-- Traces table
CREATE TABLE traces (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    input TEXT,
    output TEXT,
    start_time TIMESTAMP,
    end_time TIMESTAMP,
    duration_ms INTEGER,
    total_tokens INTEGER,
    total_cost REAL,
    metadata JSON,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Spans table
CREATE TABLE spans (
    id TEXT PRIMARY KEY,
    trace_id TEXT REFERENCES traces(id),
    parent_span_id TEXT REFERENCES spans(id),
    name TEXT NOT NULL,
    type TEXT, -- 'LLM_CALL', 'TOOL_CALL', 'RETRIEVAL', etc.
    input JSON,
    output JSON,
    start_time TIMESTAMP,
    end_time TIMESTAMP,
    duration_ms INTEGER,
    metadata JSON
);

-- Generations (LLM calls)
CREATE TABLE generations (
    id TEXT PRIMARY KEY,
    span_id TEXT REFERENCES spans(id),
    model TEXT,
    prompt TEXT,
    completion TEXT,
    input_tokens INTEGER,
    output_tokens INTEGER,
    total_tokens INTEGER,
    cost REAL,
    latency_ms INTEGER
);

-- Scores
CREATE TABLE scores (
    id TEXT PRIMARY KEY,
    trace_id TEXT REFERENCES traces(id),
    name TEXT NOT NULL, -- 'relevance', 'safety', etc.
    value REAL,
    source TEXT, -- 'LLM_JUDGE', 'HUMAN', 'RULE'
    comment TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Datasets
CREATE TABLE datasets (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    description TEXT,
    version INTEGER DEFAULT 1,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Dataset items
CREATE TABLE dataset_items (
    id TEXT PRIMARY KEY,
    dataset_id TEXT REFERENCES datasets(id),
    input TEXT NOT NULL,
    expected_output TEXT,
    metadata JSON,
    tags JSON,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Evaluation runs
CREATE TABLE evaluation_runs (
    id TEXT PRIMARY KEY,
    dataset_id TEXT REFERENCES datasets(id),
    dataset_version INTEGER,
    status TEXT, -- 'running', 'completed', 'failed'
    total_items INTEGER,
    passed_items INTEGER,
    average_score REAL,
    started_at TIMESTAMP,
    completed_at TIMESTAMP
);
```

---

## API Design

```yaml
# Traces
POST   /api/v2/traces              # Create new trace
GET    /api/v2/traces              # List traces (with filters)
GET    /api/v2/traces/{id}         # Get trace details
GET    /api/v2/traces/{id}/spans   # Get spans for trace
POST   /api/v2/traces/{id}/scores  # Add score to trace

# Datasets
POST   /api/v2/datasets            # Create dataset
GET    /api/v2/datasets            # List datasets
GET    /api/v2/datasets/{id}       # Get dataset
POST   /api/v2/datasets/{id}/items # Add items to dataset
POST   /api/v2/datasets/{id}/run   # Run evaluation on dataset

# Evaluation
POST   /api/v2/evaluate            # Run single evaluation
POST   /api/v2/evaluate/batch      # Run batch evaluation
GET    /api/v2/evaluators          # List available evaluators

# Generation (AI-assisted)
POST   /api/v2/generate/expected   # Generate expected output
POST   /api/v2/generate/test-cases # Generate test cases
POST   /api/v2/generate/evaluation # Suggest evaluation criteria

# Integration
POST   /api/v2/integrations/langfuse/sync   # Sync to Langfuse
GET    /api/v2/integrations/langfuse/import # Import from Langfuse
```

---

## What Sets This Apart

1. **Zero-Config Start** - Built-in agents, paste code, auto-detect
2. **AI-Assisted Everything** - Generate expected outputs, test cases, criteria
3. **Visual Tracing** - See exactly what your agent did
4. **Langfuse Compatible** - Works with existing ecosystem
5. **Enterprise Ready** - Self-hosted, audit logs, compliance
6. **Progressive Complexity** - Simple start, scale to production

---

## Next Steps

1. **Prototype the new wizard UI** - Step-by-step flow
2. **Implement trace data models** - Foundation for everything
3. **Add expected output generation** - Key differentiator
4. **Build trace explorer** - Visual debugging
5. **Integrate Langfuse SDK** - Ecosystem compatibility
