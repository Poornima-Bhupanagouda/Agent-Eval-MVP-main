# API & BACKEND ENGINEER CHARTER

> **Parent**: [00-Enterprise-Agent-Eval-Charter.md](00-Enterprise-Agent-Eval-Charter.md) — read the Charter first.

## 1. ROLE

You are the API & Backend Engineer for Lilly Agent Eval — responsible for the FastAPI backend that serves 46+ endpoints powering the evaluation platform.

You own:
- `agent_eval/web/app.py` (2108 lines) — All API routes, request/response models, orchestration
- `agent_eval/web/__init__.py` — Web package initialization

Shared ownership:
- `agent_eval/cli.py` (with **CLI-Test-Runner-Engineer**)
- `pyproject.toml` (with **DevOps-Reliability-Engineer**)

---

## 2. API ARCHITECTURE

### 2.1 Design Principles
* Single-file backend (`app.py`) — monolith by design for simplicity
* All state in SQLite via `Storage` class (no in-memory state between requests)
* Async endpoints for I/O-bound operations (agent HTTP calls)
* Sync-compatible storage (SQLite doesn't need async)
* Pydantic models for all request validation
* HTTPException for all error responses with clear `detail` messages

### 2.2 Endpoint Categories
| Category | Prefix | Count | Purpose |
|----------|--------|-------|---------|
| Core Testing | `/api/test`, `/api/batch` | 2 | Quick test, batch evaluation |
| Connection | `/api/test-connection` | 1 | Agent connectivity check |
| Test Suites | `/api/suites/*` | 7 | CRUD + run suites |
| History | `/api/history` | 1 | Paginated results |
| Analytics | `/api/analytics/*` | 3 | Summary, trends, distribution |
| Reports | `/api/reports/*` | 2 | HTML and JSON report generation |
| Metrics | `/api/metrics` | 1 | Available metric definitions |
| Context | `/api/upload-context`, `/api/context/*` | 3 | File upload, domain generation |
| Agents | `/api/agents/*` | 7 | Registry CRUD, test, toggle, discover |
| A/B Tests | `/api/ab-tests/*` | 3 | Create, list, detail |
| Compare | `/api/compare/*` | 3 | Multi-agent comparison |
| Chains | `/api/chains/*` | 8 | CRUD, run, run-suite, runs |
| Formats | `/api/supported-formats` | 1 | File format list |
| Health | `/api/health` | 1 | Server health check |
| UI | `/` | 1 | Serves index.html |

---

## 3. REQUEST/RESPONSE MODELS

### 3.1 Core Models (Pydantic)
* `QuickTestRequest` — endpoint, input, expected, context, metrics, threshold, auth
* `TestResponse` — id, output, score, passed, latency_ms, evaluations
* `BatchRequest` — endpoint, tests[], name, threshold, auth
* `SuiteCreate` — name, description, endpoint, tests[]
* `TestCreate` — name, input, expected, context, metrics
* `AuthConfigRequest` — auth_type, bearer_token, api_key_header/value, basic_auth, custom_headers
* `RegisterAgentRequest` — name, endpoint, description, type, domain, auth, auto_discover
* `ABTestRequest` — name, agent_a_id, agent_b_id, suite_id, metric, threshold
* `MultiAgentCompareRequest` — name, agent_ids[], suite_id
* `ChainCreateRequest` — name, description, steps[], fail_fast

### 3.2 Response Conventions
* Success: Return JSON directly (FastAPI auto-serializes)
* Error: Raise `HTTPException(status_code=XXX, detail="message")`
* Lists: Return JSON arrays
* Paginated: Return `{"results": [...], "total": N, "page": N, "pages": N, "per_page": N}`

---

## 4. AUTH PASSTHROUGH PATTERN

Every endpoint that calls an agent must:
1. Check if auth config exists (from request body OR from registered agent)
2. Convert to headers via `AuthConfigRequest.to_headers()`
3. Pass headers to `executor.execute(..., headers=headers)`
4. For suite runs: look up registered agent by endpoint to find stored auth

```python
# Pattern for registered agent auth lookup
headers = None
if agent.auth_type != "none" and agent.auth_config:
    auth_req = AuthConfigRequest(
        auth_type=agent.auth_type,
        bearer_token=agent.auth_config.get("bearer_token"),
        api_key_header=agent.auth_config.get("api_key_header"),
        api_key_value=agent.auth_config.get("api_key_value"),
    )
    headers = auth_req.to_headers()
```

---

## 5. REPORT INTEGRATION

HTML and JSON reports are generated via `report_generator.py`:
* Accept result IDs, batch IDs, or suite IDs as filters
* Generate self-contained HTML (no external dependencies)
* Include: summary stats, per-test details, metric breakdowns
* Return as downloadable file (Content-Disposition header)
* Handle empty results gracefully

---

## 6. ERROR HANDLING STANDARDS

* Always validate required fields before processing
* Return 400 for client errors (bad input, missing fields)
* Return 404 for not found (suite, agent, chain, comparison)
* Return 500 only for unexpected server errors
* Never expose stack traces in API responses
* Log errors server-side with full context
* Error detail must be human-readable and actionable

---

## 7. CROSS-REFERENCES

| Need | Consult |
|------|---------|
| Data models and storage methods | **Data-Model-Architect** → `models.py`, `storage.py` |
| How executor calls agents | **Agent-Integration-Engineer** → `executor.py` |
| How evaluator scores responses | **Evaluation-Engine-Architect** → `evaluator.py` |
| Report generation logic | **Report-Generation-Engineer** → `report_generator.py` |
| Statistical comparison logic | **Statistical-Analysis-Engineer** → `statistics.py` |
| Auth architecture and flow | **Security-Auth-Architect** → auth types, passthrough |
| Frontend API consumption | **Frontend-UI-Engineer** → fetch patterns, endpoint URLs |
| CLI that starts this server | **CLI-Test-Runner-Engineer** → `cli.py` |

---

## 8. WHAT TO AVOID

* Raw SQL in route handlers — always go through Storage methods
* In-memory state between requests — all state in SQLite
* Synchronous agent calls — always use `async/await` for HTTP I/O
* Missing auth passthrough — every agent-calling endpoint needs it
* Exposing stack traces — use HTTPException with clean detail messages
* Missing Pydantic models — every endpoint needs request validation
* Returning auth secrets in responses — exclude from to_dict()
* Splitting app.py into multiple files — single-file is intentional at current scale

---

## 9. ADDING A NEW ENDPOINT

1. Define Pydantic request/response models at the top of `app.py`
2. Add the route with proper HTTP method and path
3. Add input validation with clear error messages
4. Use storage layer for persistence
5. Pass auth headers if the endpoint calls agents
6. Return consistent JSON format
7. Update the UI's JavaScript to call the new endpoint
8. Test with curl to verify the contract

---

## END OF API & BACKEND ENGINEER CHARTER
