# Lilly Agent Eval - Developer & Architecture Guide

**Version 3.0.0** | Last Updated: March 2026

---

## Table of Contents

1. [Product Overview](#product-overview)
2. [Architecture Design](#architecture-design)
3. [Project Structure](#project-structure)
4. [Core Components](#core-components)
5. [Data Models](#data-models)
6. [API Reference](#api-reference)
7. [Frontend (UI)](#frontend-ui)
8. [Database Schema](#database-schema)
9. [Getting Started](#getting-started)
10. [Extending the System](#extending-the-system)

---

## Product Overview

### What is Lilly Agent Eval?

Lilly Agent Eval is an enterprise-grade platform for testing and evaluating AI agents. It helps teams:

- **Test AI agents** against predefined criteria and expected outputs
- **Compare multiple agents** side-by-side using A/B testing with statistical analysis
- **Chain agents together** to test orchestrator/router workflows
- **Track performance** over time with analytics and history

### Key Features

| Feature | Description |
|---------|-------------|
| **Quick Test** | Run instant evaluations on any HTTP agent endpoint |
| **Agent Registry** | Register and manage multiple agents with authentication |
| **A/B Testing** | Statistically compare two agents using Welch's t-test |
| **Multi-Agent Comparison** | Compare 3+ agents simultaneously against the same tests |
| **Chain Testing** | Test sequential agent pipelines (Agent A → Agent B → Agent C) |
| **Test Suites** | Group related tests together with JSON import/export |
| **Evaluation Metrics** | 7 built-in metrics powered by DeepEval or heuristics |
| **File Upload** | Parse PDF, DOCX, XLSX, CSV, Markdown as context |
| **Agent Introspection** | Auto-discover agent capabilities via prompt |
| **HTML Reports** | Export Lilly-branded evaluation reports |

---

## Architecture Design

### High-Level Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                      Web Browser                             │
│                   (Single Page App)                          │
└───────────────────────────┬─────────────────────────────────┘
                            │ HTTP
                            ▼
┌─────────────────────────────────────────────────────────────┐
│                    FastAPI Application                       │
│                      (app.py)                                │
│  ┌──────────────┬──────────────┬──────────────┬───────────┐ │
│  │   Routes     │  Pydantic    │    CORS      │  Static   │ │
│  │  (REST API)  │   Models     │  Middleware  │   Files   │ │
│  └──────────────┴──────────────┴──────────────┴───────────┘ │
└───────────────────────────┬─────────────────────────────────┘
                            │
        ┌───────────────────┼───────────────────┐
        ▼                   ▼                   ▼
┌───────────────┐   ┌───────────────┐   ┌───────────────┐
│   Executor    │   │   Evaluator   │   │   Storage     │
│  (HTTP calls) │   │  (DeepEval)   │   │  (SQLite)     │
└───────────────┘   └───────────────┘   └───────────────┘
        │
        ▼
┌───────────────────────────────────────────────────────────┐
│                     Your AI Agents                         │
│    (Any HTTP endpoint that accepts JSON and returns text)  │
└───────────────────────────────────────────────────────────┘
```

### Design Principles

1. **Simplicity First** - Minimal dependencies, easy to understand
2. **Single File Database** - SQLite for zero-configuration storage
3. **Protocol Agnostic** - Works with any HTTP-based agent
4. **Auto-Detection** - Automatically tries multiple request/response formats
5. **Graceful Degradation** - Works without DeepEval using heuristic fallbacks

---

## Project Structure

```
agent_eval/
├── __init__.py              # Package initialization
├── cli.py                   # Command-line interface
├── core/                    # Business logic
│   ├── __init__.py
│   ├── models.py            # Data models (Test, Suite, Result, Agent, Chain)
│   ├── executor.py          # HTTP client for calling agents
│   ├── evaluator.py         # Evaluation logic (DeepEval + heuristics)
│   ├── storage.py           # SQLite database operations
│   ├── statistics.py        # Welch's t-test for A/B comparisons
│   ├── file_parser.py       # PDF, DOCX, XLSX parsing
│   ├── context_generator.py # Generate sample context by domain
│   ├── introspector.py      # Auto-discover agent capabilities
│   └── report_generator.py  # HTML report generation
└── web/
    ├── __init__.py
    ├── app.py               # FastAPI application (main entry point)
    └── templates/
        └── index.html       # Single-page web application
```

---

## Core Components

### 1. Executor (`core/executor.py`)

**Purpose**: Sends HTTP requests to AI agents and handles responses.

**Key Features**:
- Auto-detects request format (tries multiple JSON structures)
- Extracts text from various response formats (OpenAI, simple JSON, nested)
- Handles authentication headers
- Measures latency

**Supported Request Formats**:
```python
# Tries these in order:
{"input": "..."}
{"message": "..."}
{"query": "..."}
{"messages": [{"role": "user", "content": "..."}]}  # OpenAI format
{"data": {"input": "..."}}  # Nested
```

**Supported Response Formats**:
```python
# Extracts from:
{"output": "..."}
{"response": "..."}
{"choices": [{"message": {"content": "..."}}]}  # OpenAI format
```

**Usage**:
```python
from agent_eval.core.executor import Executor

executor = Executor(timeout=30.0)
result = await executor.execute(
    endpoint="http://your-agent/chat",
    input_text="What is the PTO policy?",
    headers={"Authorization": "Bearer xxx"},
    context=["Document 1", "Document 2"]  # For RAG agents
)
print(result.output)  # Agent's response
print(result.latency_ms)  # Response time
```

---

### 2. Evaluator (`core/evaluator.py`)

**Purpose**: Evaluates agent responses using multiple metrics.

**Available Metrics**:

| Metric ID | Name | Description | Requires |
|-----------|------|-------------|----------|
| `answer_relevancy` | Answer Relevancy | Does the answer address the question? | Nothing |
| `toxicity` | Toxicity | Is the response safe and appropriate? | Nothing |
| `bias` | Bias | Does the response show unfair bias? | Nothing |
| `faithfulness` | Faithfulness | Is the answer grounded in context? | Context |
| `hallucination` | Hallucination | Does it contain made-up facts? | Context |
| `contextual_relevancy` | Contextual Relevancy | Is context relevant to question? | Context |
| `similarity` | Semantic Similarity | How similar to expected answer? | Expected |

**Smart Auto-Selection**:
- Always runs: `answer_relevancy`, `toxicity`
- If context provided: adds `faithfulness`, `hallucination`
- If expected provided: adds `similarity`

**Dual Mode**:
- **DeepEval Mode**: Uses LLM-powered evaluation (requires OpenAI API key)
- **Heuristic Mode**: Falls back to keyword/pattern-based evaluation

**Usage**:
```python
from agent_eval.core.evaluator import Evaluator

evaluator = Evaluator(model="gpt-4o-mini", threshold=70.0)
results = evaluator.evaluate(
    input_text="How many PTO days?",
    output="You get 20 days of PTO annually.",
    expected="20 days",
    context=["Employees receive 20 days PTO."],
    metrics=["answer_relevancy", "similarity", "faithfulness"]
)
for r in results:
    print(f"{r.metric}: {r.score}% - {r.reason}")
```

---

### 3. Storage (`core/storage.py`)

**Purpose**: Persists all data to SQLite database.

**Database Location**: `~/.agent_eval/data.db`

**Key Methods**:

| Method | Purpose |
|--------|---------|
| `save_suite(suite)` | Save a test suite |
| `get_suite(id)` | Retrieve suite with tests |
| `save_result(result)` | Save evaluation result |
| `get_history(limit)` | Get recent results |
| `get_history_paginated(page, per_page, filters)` | Paginated history with filters |
| `save_agent(agent)` | Register an agent |
| `get_agents(active_only)` | List registered agents |
| `save_chain(chain)` | Save agent chain |
| `save_ab_comparison(comparison)` | Save A/B test results |

---

### 4. Statistics (`core/statistics.py`)

**Purpose**: Statistical analysis for A/B testing.

**Key Function**: `welch_t_test(scores_a, scores_b)`

Performs Welch's t-test which is robust when:
- Sample sizes differ
- Variances are unequal

**Returns**:
- **p-value**: Probability results are due to chance
- **Effect size**: Cohen's d (negligible/small/medium/large)
- **Winner**: "A", "B", "tie", or None (insufficient data)

**Usage**:
```python
from agent_eval.core.statistics import determine_winner

scores_a = [85, 88, 82, 90, 87]  # Agent A scores
scores_b = [92, 94, 89, 95, 91]  # Agent B scores

winner, stats = determine_winner(scores_a, scores_b)
print(f"Winner: Agent {winner}")
print(f"p-value: {stats.p_value}")
print(f"Effect size: {stats.effect_size} ({interpret_effect_size(stats.effect_size)})")
```

---

### 5. File Parser (`core/file_parser.py`)

**Purpose**: Extract text from uploaded documents for RAG context.

**Supported Formats**:
- PDF (`.pdf`) - via pypdf
- Word (`.docx`) - via python-docx
- Excel (`.xlsx`, `.xls`) - via openpyxl
- CSV (`.csv`) - via csv module
- Markdown (`.md`) - plain text
- Text (`.txt`) - plain text

---

### 6. Agent Introspector (`core/introspector.py`)

**Purpose**: Auto-discover what an agent does by asking it.

**Process**:
1. Try `/describe` endpoint (if available)
2. Send discovery prompt: "What is your role and purpose?"
3. Analyze response to detect:
   - **Agent Type**: RAG, conversational, tool-using, simple
   - **Domain**: HR, customer support, healthcare, finance, etc.
   - **Capabilities**: What the agent can do

---

### 7. Report Generator (`core/report_generator.py`)

**Purpose**: Generate downloadable HTML reports with Lilly branding.

**Features**:
- Summary statistics (pass rate, avg score, latency)
- Individual test results with pass/fail indicators
- Evaluation breakdown per test
- Lilly red color scheme

---

## Data Models

Located in `core/models.py`. All models use Python dataclasses.

### Core Models

```python
@dataclass
class Test:
    input: str           # Question/prompt to send
    id: str              # Unique identifier
    expected: str        # Expected answer (optional)
    context: List[str]   # RAG context documents (optional)
    metrics: List[str]   # Metrics to run (optional)

@dataclass
class Suite:
    name: str            # Suite name
    id: str              # Unique identifier
    description: str     # Description
    tests: List[Test]    # Tests in this suite

@dataclass
class Result:
    endpoint: str        # Agent URL
    input: str           # Input sent
    output: str          # Agent response
    score: float         # 0-100 average score
    passed: bool         # Pass/fail status
    latency_ms: int      # Response time
    evaluations: List[EvalMetric]  # Individual metric results
```

### Multi-Agent Models

```python
@dataclass
class RegisteredAgent:
    name: str            # Display name
    endpoint: str        # HTTP endpoint URL
    agent_type: str      # "rag", "conversational", "tool_using", "simple"
    auth_type: str       # "none", "bearer_token", "api_key", "basic_auth"
    auth_config: dict    # Auth credentials (stored securely)
    version: str         # Version tag (e.g., "v1.0", "canary")
    tags: List[str]      # Labels (e.g., ["production", "staging"])

@dataclass
class ABComparison:
    name: str            # Comparison name
    agent_a_id: str      # Control agent
    agent_b_id: str      # Treatment agent
    suite_id: str        # Test suite to use
    winner: str          # "A", "B", "tie", or None
    p_value: float       # Statistical significance
    effect_size: float   # Cohen's d
```

### Chain Models

```python
@dataclass
class AgentChain:
    name: str            # Chain name
    steps: List[ChainStep]  # Ordered agent sequence
    fail_fast: bool      # Stop on first failure

@dataclass
class ChainStep:
    agent_id: str        # Agent to call
    order: int           # Position in chain
    input_mapping: str   # "previous_output" or "direct"
```

---

## API Reference

### Health & Info

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/health` | Health check (returns `{"status": "healthy"}`) |
| GET | `/api/metrics` | List available evaluation metrics |

### Quick Test

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/test` | Run a single evaluation test |
| POST | `/api/batch` | Run multiple tests in batch |

**POST /api/test Request**:
```json
{
  "endpoint": "http://your-agent/chat",
  "input": "How many PTO days do I get?",
  "expected": "20 days",
  "context": ["Employees receive 20 PTO days annually."],
  "metrics": ["answer_relevancy", "similarity"],
  "threshold": 70,
  "auth": {
    "auth_type": "bearer_token",
    "bearer_token": "your-token"
  }
}
```

### Test Suites

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/suites` | List all suites |
| POST | `/api/suites` | Create new suite |
| GET | `/api/suites/{id}` | Get suite with tests |
| DELETE | `/api/suites/{id}` | Delete suite |
| POST | `/api/suites/{id}/tests` | Add test to suite |
| PUT | `/api/suites/{id}/tests` | Replace all tests (JSON upload) |
| POST | `/api/suites/{id}/run` | Run suite against endpoint |

### Agent Registry

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/agents` | List registered agents |
| POST | `/api/agents` | Register new agent |
| GET | `/api/agents/{id}` | Get agent details |
| DELETE | `/api/agents/{id}` | Remove agent |
| POST | `/api/agents/{id}/test` | Quick test specific agent |

### A/B Testing

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/ab-comparisons` | List A/B comparisons |
| POST | `/api/ab-comparisons` | Create & run A/B test |
| GET | `/api/ab-comparisons/{id}` | Get comparison results |

### Chain Testing

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/chains` | List agent chains |
| POST | `/api/chains` | Create new chain |
| GET | `/api/chains/{id}` | Get chain details |
| DELETE | `/api/chains/{id}` | Delete chain |
| POST | `/api/chains/{id}/run` | Execute chain with single input |
| POST | `/api/chains/{id}/run-suite/{suite_id}` | Run chain with test suite |

### History & Analytics

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/history` | Get evaluation history (paginated) |
| GET | `/api/analytics` | Get aggregate statistics |

---

## Frontend (UI)

### Location
`agent_eval/web/templates/index.html`

### Architecture
Single HTML file containing:
- CSS styles (embedded)
- HTML structure
- JavaScript (embedded at bottom)

### Tab Structure

| Tab | Purpose |
|-----|---------|
| **Quick Test** | Run instant evaluations with file upload support |
| **Agents** | Register, manage, and test agents |
| **Compare** | A/B testing and multi-agent comparison |
| **Chains** | Visual chain builder for orchestrator testing |
| **Test Suites** | Create/manage test collections with JSON editor |
| **Analytics** | Performance dashboards with filtering |
| **History** | Searchable history with pagination (20/page, 3 months) |

### Key JavaScript Functions

```javascript
// Modal management
openModal(modalId)
closeModal(modalId)

// Data loading
loadAgents()
loadSuites()
loadHistory()
loadAnalytics()

// Agent operations
registerAgent()
testRegisteredAgent(agentId)

// Chain builder
addAgentToChain(agentId)
removeAgentFromChain(index)
createChainFromBuilder()

// Suite operations
createSuite()
viewSuiteAsJson(suiteId)
saveSuiteJson(suiteId)

// Main test execution
runTest()
runBulkTests()
```

---

## Database Schema

SQLite database at `~/.agent_eval/data.db`

### Tables

```sql
-- Test Suites
suites (
    id TEXT PRIMARY KEY,
    name TEXT,
    description TEXT,
    endpoint TEXT,
    created_at TEXT,
    updated_at TEXT
)

-- Test Cases
tests (
    id TEXT PRIMARY KEY,
    suite_id TEXT REFERENCES suites(id),
    name TEXT,
    input TEXT,
    expected TEXT,
    context TEXT,  -- JSON array
    metrics TEXT   -- JSON array
)

-- Evaluation Results
results (
    id TEXT PRIMARY KEY,
    test_id TEXT,
    suite_id TEXT,
    batch_id TEXT,
    endpoint TEXT,
    input TEXT,
    output TEXT,
    score REAL,
    passed INTEGER,
    latency_ms INTEGER,
    evaluations TEXT,  -- JSON array
    created_at TEXT
)

-- Registered Agents
agents (
    id TEXT PRIMARY KEY,
    name TEXT,
    endpoint TEXT,
    agent_type TEXT,
    auth_type TEXT,
    auth_config TEXT,  -- JSON object (encrypted in future)
    version TEXT,
    is_active INTEGER
)

-- A/B Comparisons
ab_comparisons (
    id TEXT PRIMARY KEY,
    name TEXT,
    agent_a_id TEXT,
    agent_b_id TEXT,
    suite_id TEXT,
    winner TEXT,
    p_value REAL,
    effect_size REAL
)

-- Agent Chains
chains (
    id TEXT PRIMARY KEY,
    name TEXT,
    steps TEXT,  -- JSON array of ChainStep
    fail_fast INTEGER
)

-- Chain Execution Runs
chain_runs (
    id TEXT PRIMARY KEY,
    chain_id TEXT REFERENCES chains(id),
    status TEXT,
    total_tests INTEGER,
    passed_tests INTEGER,
    results TEXT  -- JSON array
)
```

---

## Getting Started

### Prerequisites
- Python 3.11+
- Poetry (recommended) or pip

### Installation

```bash
# Clone repository
git clone <repo-url>
cd agent-eval-mvp

# Install dependencies
poetry install

# Or with pip
pip install -e .

# For LLM-powered evaluations (optional)
poetry install --extras deepeval
export OPENAI_API_KEY=your-key
```

### Running the Server

```bash
# Using Poetry
poetry run uvicorn agent_eval.web.app:app --reload --port 8000

# Or directly
python -m uvicorn agent_eval.web.app:app --reload --port 8000

# Access UI at http://localhost:8000
```

### Quick Start

1. Open http://localhost:8000
2. Go to **Agents** tab
3. Click **Register Agent** and add your agent endpoint
4. Go to **Quick Test** tab
5. Enter a test input and click **Run Test**
6. View results with pass/fail status and metric scores

---

## Extending the System

### Adding a New Evaluation Metric

1. Edit `core/evaluator.py`
2. Add to `METRICS` dictionary:
```python
METRICS = {
    ...
    "your_metric": {
        "name": "Your Metric",
        "description": "What it measures",
        "requires": None,  # or "context" or "expected"
    },
}
```
3. Add handler in `_run_heuristic_metric()`
4. If using DeepEval, add to `_get_deepeval_metric()`

### Adding a New Request Format

Edit `core/executor.py`, method `_get_payloads()`:
```python
def _get_payloads(self, input_text, context):
    return [
        {"input": input_text},
        {"your_custom_format": input_text},  # Add here
        ...
    ]
```

### Adding a New Response Parser

Edit `core/executor.py`, method `_extract_output()`:
```python
def _extract_output(self, data):
    ...
    # Add your custom extraction logic
    if "your_custom_key" in data:
        return data["your_custom_key"]
```

### Adding a New File Format

1. Edit `core/file_parser.py`
2. Add extension to `SUPPORTED_EXTENSIONS`
3. Add parser method `_parse_yourformat()`
4. Update `parse()` method to call it

### Adding a New API Endpoint

1. Edit `web/app.py`
2. Add Pydantic request/response models
3. Add route with decorator:
```python
@app.post("/api/your-endpoint")
async def your_endpoint(request: YourRequest):
    # Implementation
    return {"result": "..."}
```

---

## Configuration

### Environment Variables

| Variable | Purpose | Default |
|----------|---------|---------|
| `OPENAI_API_KEY` | For DeepEval LLM evaluations | None (uses heuristics) |
| `AGENT_EVAL_DB_PATH` | Custom database location | `~/.agent_eval/data.db` |

### Evaluation Threshold

Default pass threshold is 70%. Can be overridden per-request:
```json
{
  "threshold": 80
}
```

---

## Support & Troubleshooting

### Common Issues

**"Failed to communicate with agent"**
- Check agent endpoint is accessible
- Verify authentication if required
- Check agent accepts POST requests with JSON

**"DeepEval not available"**
- Install with: `poetry install --extras deepeval`
- Set `OPENAI_API_KEY` environment variable

**"No tests in suite"**
- Ensure tests have `input` field
- Check JSON format when uploading

### Logs

Enable debug logging:
```python
import logging
logging.basicConfig(level=logging.DEBUG)
```

---

## Authors & License

**Eli Lilly and Company**

Internal Use Only

---

*Document generated for Lilly Agent Eval v3.0.0*
