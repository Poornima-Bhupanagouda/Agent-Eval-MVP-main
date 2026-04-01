# LILLY AGENT EVAL — ENTERPRISE ENGINEERING CHARTER

## 1. ROLE & IDENTITY

You are engineering an enterprise AI agent evaluation platform for Eli Lilly and Company.

This is NOT a demo.
This is NOT a prototype.
This is NOT throwaway code.

Lilly Agent Eval is an internal tool that evaluates AI agents across quality, safety, faithfulness, and reliability — used by teams deploying AI agents in regulated pharma environments.

All implementations must meet enterprise standards for:
* Reliability (runs must produce consistent, reproducible results)
* Security (auth passthrough, no secret leakage, input validation)
* Accuracy (evaluation scores must be mathematically sound)
* Traceability (every test run, every score, every comparison — stored and queryable)
* Usability (single-command startup, intuitive UI, actionable error messages)

---

## 2. SYSTEM ARCHITECTURE

### 2.1 Two-Service System
| Service | Port | Module | Purpose |
|---------|------|--------|---------|
| Eval Platform | 8000 | `agent_eval.web.app` | Dashboard + 46 API endpoints |
| Sample RAG Agent | 8003 | `sample_agents.smart_rag_agent` | Reference HR policy agent |

### 2.2 Core Modules (7,071 lines total)
| Module | File | Lines | Responsibility |
|--------|------|-------|---------------|
| Evaluator | `agent_eval/core/evaluator.py` | 564 | 7 metrics, DeepEval + heuristic |
| Executor | `agent_eval/core/executor.py` | 279 | HTTP bridge, 14 payload formats |
| Storage | `agent_eval/core/storage.py` | 1043 | SQLite, 8 tables, full CRUD |
| Models | `agent_eval/core/models.py` | 373 | 14 dataclasses |
| Statistics | `agent_eval/core/statistics.py` | 273 | Welch's t-test, Cohen's d |
| Report Generator | `agent_eval/core/report_generator.py` | 820 | Branded HTML/JSON reports |
| Context Generator | `agent_eval/core/context_generator.py` | 291 | Domain-aware synthetic context |
| File Parser | `agent_eval/core/file_parser.py` | 191 | PDF, DOCX, TXT, MD, CSV, JSON |
| Introspector | `agent_eval/core/introspector.py` | 251 | Agent auto-discovery |
| CLI | `agent_eval/cli.py` | 235 | 3 commands: start, test, run |
| Backend | `agent_eval/web/app.py` | 2108 | FastAPI routes + orchestration |
| Frontend | `agent_eval/web/templates/index.html` | ~5100 | SPA: HTML + CSS + JS |
| RAG Agent | `sample_agents/smart_rag_agent.py` | 630 | TF-IDF + LLM reference agent |

### 2.3 Data Flow
```
User → UI (index.html) → API (app.py) → Executor → Agent HTTP endpoint
                                       → Evaluator → Score + Reason
                                       → Storage → SQLite
                                       → Report Generator → HTML/JSON
```

---

## 3. GLOBAL ENGINEERING PRINCIPLES

* **Single-file backend** — `app.py` is the monolith; acceptable at current scale
* **Single-file frontend** — `index.html` with embedded CSS + JS; no build tools
* **All state in SQLite** — no in-memory state between requests
* **Parameterized SQL only** — never string concatenation in queries
* **Async for I/O** — all agent HTTP calls use `async/await`
* **Pydantic for validation** — every endpoint has a request model
* **Auth passthrough** — platform stores and forwards agent credentials, never logs them
* **Heuristic fallback** — every LLM-dependent feature has a non-LLM fallback
* **Connection-per-request** — SQLite handles concurrency via separate connections
* **Process isolation** — PID files, zombie cleanup, health checks on startup

---

## 4. SKILL OWNERSHIP MAP

| Skill | Primary Files | Shared Ownership |
|-------|--------------|-----------------|
| Evaluation-Engine-Architect | `evaluator.py` | `models.py` (EvalMetric, Result) |
| Agent-Integration-Engineer | `executor.py`, `introspector.py` | `smart_rag_agent.py` |
| Statistical-Analysis-Engineer | `statistics.py` | `app.py` (A/B, compare endpoints) |
| API-Backend-Engineer | `app.py` | All endpoint consumers |
| Frontend-UI-Engineer | `index.html` | Chart rendering, modals |
| Security-Auth-Architect | Auth in `app.py` + `smart_rag_agent.py` | `.env`, `.env.example` |
| Test-Suite-Designer | Tests in `app.py` + YAML | `models.py` (Test, Suite) |
| DevOps-Reliability-Engineer | `start.sh`, `cli.py` | `pyproject.toml`, `.env` |
| Principal-Engineer | Cross-cutting code review | All files |
| RAG-Knowledge-Base-Engineer | `smart_rag_agent.py` | `file_parser.py`, `context_generator.py`, `KB/` |
| Report-Generation-Engineer | `report_generator.py` | `app.py` (report endpoints) |
| Data-Model-Architect | `models.py`, `storage.py` | All consumers |

---

## 5. CROSS-CUTTING RULES

### 5.1 Error Handling
* Backend: `HTTPException` with human-readable `detail`; never expose stack traces
* Frontend: `showToast()` for every error; never `console.error` alone
* Evaluator: return score=0 with reason on error; never throw
* Executor: return `ExecuteResult(error=...)` on failure; never throw

### 5.2 Security
* Secrets in `.env` only — never hardcoded, never in git, never in logs
* All user content escaped with `escapeHtml()` in frontend
* SQL uses `?` placeholders exclusively
* Auth headers never returned in API responses
* File uploads validate extension against allowed list

### 5.3 Data Integrity
* All IDs are 12-char hex UUIDs (`generate_id()`)
* All timestamps are ISO 8601 UTC
* JSON fields serialized via `json.dumps()`, deserialized via `json.loads()`
* Never delete data without explicit user action
* Pagination via LIMIT/OFFSET with total count

### 5.4 JavaScript Safety
* No duplicate `let`/`const` declarations (kills ALL JS silently)
* No innerHTML with unescaped user data (XSS)
* Every `fetch()` checks `response.ok` before parsing
* Every catch block shows user-visible feedback
* All functions at script-level scope (no modules)

---

## 6. THINKING INSTRUCTIONS

Before writing any code:
1. **Identify the owning skill** — check the ownership map above
2. **Read the file first** — never modify code you haven't read
3. **Check API contracts** — verify JS endpoint URLs match Python routes
4. **Check auth passthrough** — any endpoint calling an agent must pass headers
5. **Check for duplicates** — especially JS variables and function names
6. **Consider edge cases** — empty data, missing fields, auth failures, timeouts
7. **Test the change** — extract JS and syntax-check; verify endpoints respond

---

## 7. WHAT TO AVOID

* Toy implementations — this is production tooling, not a demo
* Silent failures — every error must surface to the user
* Global mutable state — all state goes through SQLite
* Magic strings — use constants or Pydantic models
* Over-engineering — single-file architecture is intentional; don't split without cause
* Framework additions — no React, no npm, no build tools for the frontend
* Bare `except Exception` — catch specific errors
* Fire-and-forget promises — `await` all async calls
* Hardcoded secrets — everything through `.env`
* Duplicate code — check if a function already exists before writing a new one

---

## 8. QUALITY GATES

Before any change is considered complete:
- [ ] All API endpoints return correct status codes
- [ ] JS syntax valid (no duplicate declarations, no undefined functions)
- [ ] Auth passthrough works for suite runs, A/B tests, chain runs
- [ ] Error states show user-visible feedback
- [ ] No secrets in logs or responses
- [ ] SQL uses parameterized queries
- [ ] New endpoints validate all required fields
- [ ] Frontend escapes all user content

---

## END OF ENTERPRISE ENGINEERING CHARTER
