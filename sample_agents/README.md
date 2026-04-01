# Multi-Agent Research Assistant

A complete working multi-agent workflow that demonstrates real LLM-powered capabilities.

## Overview

This sample agent uses a multi-agent architecture with specialized roles:

1. **Planner Agent** - Analyzes queries and creates research plans
2. **Researcher Agent** - Gathers detailed information based on the plan
3. **Synthesizer Agent** - Combines findings into coherent answers
4. **Critic Agent** (optional) - Reviews and validates answers

## Architecture

```
sample_agents/
├── __init__.py
├── api.py                    # FastAPI application
├── core/
│   ├── llm_client.py        # Unified LLM client (OpenAI, Azure, Gateway)
│   ├── models.py            # Data models
│   └── orchestrator.py      # Multi-agent orchestrator
└── agents/
    ├── prompts.py           # Agent system prompts
    └── research_assistant.py # Main workflow
```

## Setup

1. Set your OpenAI API key:
```bash
export OPENAI_API_KEY=your-key-here
```

2. Optional: Configure custom LLM endpoint:
```bash
# For LLM Gateway
export LLM_GATEWAY_URL=https://your-gateway.example.com/v1

# For Azure OpenAI
export AZURE_OPENAI_ENDPOINT=https://your-resource.openai.azure.com
export AZURE_OPENAI_KEY=your-azure-key
```

## Running the Agent

```bash
# From project root
python -m sample_agents.api

# Server starts at http://127.0.0.1:8001
```

## API Endpoints

### POST /chat
Simple chat endpoint (compatible with Lilly Agent Eval):

```bash
curl -X POST http://127.0.0.1:8001/chat \
  -H "Content-Type: application/json" \
  -d '{"input": "What are the benefits of microservices?"}'
```

Response:
```json
{
  "output": "Microservices offer several key benefits...",
  "tokens": 1250,
  "latency_ms": 3500
}
```

### POST /research
Full research endpoint with detailed workflow info:

```bash
curl -X POST http://127.0.0.1:8001/research \
  -H "Content-Type: application/json" \
  -d '{"input": "Explain machine learning"}'
```

Response:
```json
{
  "response": "Machine learning is...",
  "workflow_id": "abc123",
  "total_tokens": 2500,
  "total_latency_ms": 8000,
  "agent_count": 3,
  "agents": [
    {"agent_name": "planner", "content": "...", "latency_ms": 1500},
    {"agent_name": "researcher", "content": "...", "latency_ms": 3000},
    {"agent_name": "synthesizer", "content": "...", "latency_ms": 3500}
  ]
}
```

### Modes

- `full` (default) - Uses Planner → Researcher → Synthesizer (3 agents)
- `quick` - Uses only Synthesizer (1 agent, faster)
- `reviewed` - Uses all 4 agents including Critic

```bash
# Quick mode
curl -X POST http://127.0.0.1:8001/chat \
  -H "Content-Type: application/json" \
  -d '{"input": "What is Python?", "mode": "quick"}'
```

## Using with Lilly Agent Eval

1. Start the sample agent:
```bash
python -m sample_agents.api
```

2. Start the evaluation platform:
```bash
python -m agent_eval.cli serve
```

3. Open http://127.0.0.1:8000 in your browser

4. Click "Load Demo" to pre-fill the sample agent endpoint

5. Run evaluations against the multi-agent workflow

## Customization

### Using a different model:
```bash
export OPENAI_MODEL=gpt-4
python -m sample_agents.api
```

### Adding new agents:
Edit `agents/research_assistant.py` to register additional agents:

```python
self.orchestrator.register_agent(Agent(
    name="my_agent",
    role="custom",
    system_prompt="You are a specialized agent...",
    temperature=0.5,
))
```

## Testing

```bash
# Health check
curl http://127.0.0.1:8001/health

# Test with sample query
curl -X POST http://127.0.0.1:8001/chat \
  -H "Content-Type: application/json" \
  -d '{"input": "Hello, how are you?"}'
```
