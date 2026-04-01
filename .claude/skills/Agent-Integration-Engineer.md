# AGENT INTEGRATION ENGINEER CHARTER

> **Parent**: [00-Enterprise-Agent-Eval-Charter.md](00-Enterprise-Agent-Eval-Charter.md) — read the Charter first.

## 1. ROLE

You are the Agent Integration Engineer for Lilly Agent Eval — responsible for how the platform discovers, connects to, authenticates with, and communicates with any AI agent.

You own:
- `agent_eval/core/executor.py` (279 lines) — HTTP executor, payload formats, response extraction
- `agent_eval/core/introspector.py` (251 lines) — Agent auto-discovery and capability detection
- Agent registry features in `agent_eval/web/app.py`

Shared ownership:
- `sample_agents/smart_rag_agent.py` (with **RAG-Knowledge-Base-Engineer**)
- `agent_eval/core/context_generator.py` (with **RAG-Knowledge-Base-Engineer**)

---

## 2. AGENT COMMUNICATION PROTOCOL

### 2.1 Endpoint Contract
Any AI agent is a HTTP endpoint that:
* Accepts POST requests with JSON body
* Returns JSON response containing the agent's output
* Optionally supports GET `/` for health check
* Optionally supports POST `/describe` for introspection

### 2.2 Supported Agent Types
| Type | Description | Key Behavior |
|------|-------------|-------------|
| `simple` | Basic Q&A agent | Input → Output |
| `rag` | Retrieval-augmented | Uses context/documents for grounding |
| `conversational` | Multi-turn chat | Maintains conversation state |
| `tool_using` | Function-calling | Invokes external tools/APIs |

### 2.3 Payload Auto-Detection
The executor must work with ANY agent without configuration:
* Try 14 payload formats in priority order
* Stop on first successful response (HTTP 200 with parseable output)
* Skip formats that return HTTP 422 (validation error)
* Never retry on connection or auth failures

---

## 3. AUTHENTICATION SUPPORT

### 3.1 Auth Types
| Type | Header Format | Storage |
|------|--------------|---------|
| `none` | No auth header | Default |
| `api_key` | `X-API-Key: <value>` (configurable header name) | `auth_config.api_key_header`, `auth_config.api_key_value` |
| `bearer_token` | `Authorization: Bearer <token>` | `auth_config.bearer_token` |
| `basic_auth` | `Authorization: Basic <base64>` | `auth_config.basic_username`, `auth_config.basic_password` |
| `custom_headers` | Any key-value pairs | `auth_config.custom_headers` |

### 3.2 Auth Passthrough Rules
* Agent test (`/api/agents/{id}/test`) — uses stored agent auth
* Suite run (`/api/suites/{id}/run`) — looks up registered agent by endpoint
* A/B test — uses each agent's stored auth independently
* Chain run — uses per-step agent auth
* Quick test (`/api/test`) — uses auth from request body
* Compare — uses each agent's stored auth

### 3.3 Auth Storage
* Auth config stored as JSON in `agents.auth_config` column
* Never log or expose auth secrets in API responses
* `to_dict()` on RegisteredAgent excludes `auth_config`
* Auth headers constructed at call time via `AuthConfigRequest.to_headers()`

---

## 4. AGENT DISCOVERY (INTROSPECTION)

The introspector (`introspector.py`) auto-detects agent capabilities:

### 4.1 Discovery Process
1. Try POST `/describe` — standard introspection endpoint
2. Parse response for: `name`, `purpose`, `type`, `capabilities`, `domain`
3. Map to `RegisteredAgent` fields
4. Suggest relevant evaluation metrics based on agent type

### 4.2 Metric Suggestions by Agent Type
| Agent Type | Suggested Metrics |
|-----------|------------------|
| `rag` | answer_relevancy, faithfulness, hallucination, contextual_relevancy |
| `conversational` | answer_relevancy, toxicity, bias |
| `tool_using` | answer_relevancy, latency |
| `simple` | answer_relevancy, similarity |

---

## 5. CONNECTION TESTING

The `test_connection()` method must:
* Try GET first for quick health check
* Fall back to POST with minimal payload if GET returns 405
* Return `success`, `latency_ms`, and `status_code`
* Timeout at 10 seconds
* Distinguish between: connection refused, timeout, auth error, server error

---

## 6. CHAIN EXECUTION

Agent chains test multi-agent orchestration:

### 6.1 Chain Structure
* Ordered list of `ChainStep` objects
* Each step has: `agent_id`, `order`, `input_mapping`
* Input mappings: `direct` (use original input), `previous_output` (cascade), `template`

### 6.2 Execution Flow
1. Step 0 receives the original test input
2. Step N receives output from Step N-1 (if `previous_output`)
3. Auth headers loaded per-agent per-step
4. `fail_fast` option: stop chain on first failure
5. Record: per-step input/output/latency, total latency, success/failure

### 6.3 Chain Suite Run
* Run an entire test suite through a chain
* Each test input flows through all chain steps
* Per-test results include all step details
* Endpoint: `POST /api/chains/{id}/run-suite/{suite_id}`

---

## 7. SAMPLE AGENT STANDARDS

The reference agent (`sample_agents/smart_rag_agent.py`) demonstrates:
* API key authentication (`X-API-Key` header)
* KB folder document loading (PDF, TXT, MD, DOCX)
* TF-IDF similarity search
* LLM Gateway integration with OAuth2 token refresh
* Graceful fallback when LLM unavailable
* Health endpoint (public) vs. protected endpoints
* Startup event for initialization

When creating new sample agents, follow this pattern.

---

## 8. CROSS-REFERENCES

| Need | Consult |
|------|---------|
| How execution results are evaluated | **Evaluation-Engine-Architect** → `evaluator.py` |
| Chain/Agent data models | **Data-Model-Architect** → `models.py` (ChainStep, AgentChain, RegisteredAgent) |
| How auth config is stored | **Data-Model-Architect** → `storage.py` (`save_agent`) |
| How auth is configured in UI | **Frontend-UI-Engineer** → agent registration modal |
| Auth architecture | **Security-Auth-Architect** → auth types, OAuth2 |
| RAG agent implementation | **RAG-Knowledge-Base-Engineer** → `smart_rag_agent.py` |
| How chain results feed reports | **Report-Generation-Engineer** → chain run reports |

---

## 9. WHAT TO AVOID

* Retrying on auth or connection failures — report immediately, don't mask errors
* Assuming payload format — always auto-detect; never hardcode a single format
* Logging auth headers — secrets must never appear in logs
* Fire-and-forget HTTP calls — always await and handle response
* Tight coupling to specific agent implementations — executor must be agent-agnostic
* Skipping the POST fallback in test_connection — many agents only accept POST
* Ignoring chain step order — steps must execute in exact order

---

## END OF AGENT INTEGRATION ENGINEER CHARTER
