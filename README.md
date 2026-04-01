# Lilly Agent Eval

Simple, fast evaluation platform for AI agents. Inspired by TruLens and DeepEval.

## Quick Start

```bash
# Install dependencies
pip install -e .

# Start the web UI
agent-eval start

# Open browser to http://localhost:8000
```

## Features

- **Quick Test**: Test any agent endpoint with a single click
- **Smart Metrics**: Auto-selects relevant metrics based on your inputs
- **Test Suites**: Organize tests into suites for regression testing
- **Batch Testing**: Run multiple tests from JSON/CSV
- **Analytics**: Track pass rates, scores, and trends over time
- **CI/CD Ready**: Exit codes for automated pipelines

## Usage

### Web UI

```bash
# Start the server
agent-eval start --port 8000

# With auto-reload for development
agent-eval start --reload
```

### Command Line

```bash
# Quick test
agent-eval test http://localhost:8001/chat "What is Python?" --expected "programming language"

# Run YAML test files
agent-eval run tests/*.yaml --threshold 70 --fail-fast

# Output as JSON
agent-eval test http://localhost:8001/chat "Hello" --json
```

### YAML Test Format

```yaml
endpoint: http://localhost:8001/chat
name: My Test Suite
threshold: 70

tests:
  - name: Basic Question
    input: "What is 2+2?"
    expected: "4"
    metrics:
      - answer_relevancy
      - similarity

  - name: RAG Test
    input: "What is our return policy?"
    context:
      - "We offer 30-day returns."
    metrics:
      - faithfulness
      - hallucination
```

## Available Metrics

| Metric | Description | Requires |
|--------|-------------|----------|
| `answer_relevancy` | Does the answer address the question? | - |
| `toxicity` | Is the response safe and appropriate? | - |
| `bias` | Does the response show unfair bias? | - |
| `faithfulness` | Is the answer grounded in context? | context |
| `hallucination` | Does it contain made-up facts? | context |
| `similarity` | How similar to expected output? | expected |

## API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/test` | POST | Run a quick test |
| `/api/suites` | GET/POST | Manage test suites |
| `/api/suites/{id}/run` | POST | Run all tests in a suite |
| `/api/batch` | POST | Run batch tests |
| `/api/history` | GET | Get evaluation history |
| `/api/analytics/summary` | GET | Get analytics summary |
| `/api/metrics` | GET | List available metrics |

## Configuration

Set your OpenAI API key for LLM-powered evaluations:

```bash
export OPENAI_API_KEY=sk-...
```

Without an API key, heuristic evaluations are used as fallback.

## CI/CD Integration

### GitHub Actions

```yaml
- name: Run agent evaluation
  run: agent-eval run tests/*.yaml --threshold 70 --fail-fast
  env:
    OPENAI_API_KEY: ${{ secrets.OPENAI_API_KEY }}
```

### Exit Codes

- `0`: All tests passed
- `1`: One or more tests failed

## Development

```bash
# Install dev dependencies
pip install -e ".[dev]"

# Run tests
pytest

# Format code
black agent_eval
```

## Architecture

```
agent_eval/
├── core/
│   ├── evaluator.py    # DeepEval wrapper
│   ├── executor.py     # HTTP client
│   ├── models.py       # Data classes
│   └── storage.py      # SQLite storage
├── web/
│   ├── app.py          # FastAPI routes
│   └── templates/
│       └── index.html  # Single-page UI
└── cli.py              # CLI interface
```

## License

Eli Lilly and Company - Internal Use
