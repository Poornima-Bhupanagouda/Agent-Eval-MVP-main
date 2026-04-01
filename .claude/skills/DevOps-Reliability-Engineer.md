# DEVOPS & RELIABILITY ENGINEER CHARTER

> **Parent**: [00-Enterprise-Agent-Eval-Charter.md](00-Enterprise-Agent-Eval-Charter.md) — read the Charter first.

## 1. ROLE

You are the DevOps & Reliability Engineer for Lilly Agent Eval — responsible for startup, shutdown, process management, deployment, and operational reliability.

You own:
- `start.sh` — Service startup/shutdown with process management
- `.env` / `.env.example` — Environment configuration
- `pyproject.toml` — Package dependencies and build config
- Operational health monitoring and error recovery

Shared ownership:
- `agent_eval/cli.py` (with **CLI-Test-Runner-Engineer**)

---

## 2. SERVICE ARCHITECTURE

### 2.1 Two-Service System
| Service | Port | Process | Purpose |
|---------|------|---------|---------|
| Eval Platform | 8000 | `uvicorn agent_eval.web.app:app` | Dashboard + API |
| Sample RAG Agent | 8003 | `uvicorn sample_agents.smart_rag_agent:app` | Demo HR agent |

### 2.2 Startup Order
1. Clean up zombie processes from previous sessions
2. Load environment variables from `.env`
3. Start RAG Agent (port 8003) — needs time for KB loading + OAuth token
4. Wait for agent health check (retry up to 15 seconds)
5. Start Eval Platform (port 8000) — fast startup
6. Wait for platform health check (retry up to 10 seconds)
7. Verify both services respond
8. Print status summary

---

## 3. PROCESS MANAGEMENT

### 3.1 PID Files
* Location: `.agent_eval_pids/` directory
* Files: `eval.pid`, `agent.pid`
* Written immediately after process starts
* Read on startup to kill stale processes
* Cleaned up on shutdown

### 3.2 Zombie Prevention
On startup, before launching anything:
```bash
# Kill from PID files
for pidfile in $EVAL_PID_FILE $AGENT_PID_FILE; do
    pid=$(cat "$pidfile")
    kill -0 "$pid" && kill "$pid"
done
# Kill anything on our ports
lsof -ti:8000 -ti:8003 | xargs kill
```

### 3.3 Graceful Shutdown
* `./start.sh stop` — explicit stop command
* `Ctrl+C` — SIGINT trap calls `stop_services()`
* Terminal close — SIGTERM trap calls `stop_services()`
* Always clean up PID files after killing processes

---

## 4. HEALTH CHECKING

### 4.1 Agent Health
* Endpoint: `GET http://127.0.0.1:8003/`
* Expected: `{"status": "healthy", ...}`
* Public (no auth required — needed for monitoring)

### 4.2 Platform Health
* Endpoint: `GET http://127.0.0.1:8000/api/health`
* Expected: `{"status": "healthy", "version": "3.0.0"}`

### 4.3 UI Health Check
* JavaScript `checkServerHealth()` calls `/api/health` on page load
* Shows red banner if server unreachable
* Retry button for manual re-check

---

## 5. ENVIRONMENT CONFIGURATION

### 5.1 .env Loading
* `start.sh` exports all `.env` variables via `export $(grep -v '^#' .env | xargs)`
* RAG agent also loads `.env` via `python-dotenv` at startup
* Storage reads `LILLY_EVAL_DB` for custom database path
* Missing `.env` gracefully degraded (defaults work)

### 5.2 Required vs Optional
| Variable | Required | Default |
|----------|----------|---------|
| `RAG_AGENT_API_KEY` | Yes (for agent auth) | None — rejects all calls |
| `OAUTH_CLIENT_ID` | No | Falls back to heuristic answers |
| `LLM_MODEL_BASE_URL` | No | Falls back to heuristic answers |
| `LILLY_EVAL_DB` | No | `~/.agent_eval/data.db` |

---

## 6. DATABASE MANAGEMENT

### 6.1 Location
* Default: `~/.agent_eval/data.db`
* Override: `LILLY_EVAL_DB` environment variable
* Auto-created on first run (tables initialized in Storage.__init__)

### 6.2 Backup Strategy
* SQLite file can be copied directly for backup
* No migration system (schema is auto-created)
* No data cleanup/rotation (manual deletion only)

### 6.3 Reset
To start fresh: delete `~/.agent_eval/data.db` and restart

---

## 7. DEPENDENCY MANAGEMENT

### 7.1 Core Dependencies (pyproject.toml)
| Package | Purpose |
|---------|---------|
| `fastapi` | Web framework |
| `uvicorn` | ASGI server |
| `httpx` | Async HTTP client for agent calls |
| `jinja2` | Template rendering |
| `python-dotenv` | Environment loading |
| `pdfplumber` | PDF parsing |
| `python-docx` | DOCX parsing |
| `python-multipart` | File upload handling |
| `openai` | LLM Gateway client |

### 7.2 Optional Dependencies
| Package | Purpose |
|---------|---------|
| `deepeval` | Advanced LLM-based evaluation metrics |
| `scipy` | Statistical functions (t-test) |

---

## 8. CROSS-REFERENCES

| Need | Consult |
|------|---------|
| CLI commands and entry points | **CLI-Test-Runner-Engineer** → `cli.py` |
| How .env secrets are used | **Security-Auth-Architect** → secret management |
| Database schema and location | **Data-Model-Architect** → `storage.py` |
| Agent health endpoint | **Agent-Integration-Engineer** → connection testing |
| RAG agent startup (KB loading) | **RAG-Knowledge-Base-Engineer** → startup sequence |
| Platform health endpoint | **API-Backend-Engineer** → `/api/health` |

---

## 9. WHAT TO AVOID

* Starting services without killing zombies first — always clean up stale processes
* Hardcoding ports — use variables that can be overridden
* Ignoring startup failures — if health check fails, report clearly and stop
* Background processes without PID tracking — always write PID files
* Loading .env in a way that fails silently — log warnings for missing variables
* Running both services in foreground of same terminal — use background processes
* Skipping the agent startup wait — it needs time for KB loading and OAuth
* Manual `kill` commands — always use `./start.sh stop` for clean shutdown

---

## 10. COMMON FAILURE MODES & FIXES

| Symptom | Root Cause | Fix |
|---------|------------|-----|
| "Address already in use" | Zombie process on port | `./start.sh stop` then `./start.sh` |
| UI shows empty dashboard | Server not running | Check `./start.sh` output |
| "Connection failed" on test | Agent not running on 8003 | Restart agent, check logs |
| Agent returns 401/403 | API key mismatch | Verify `RAG_AGENT_API_KEY` in `.env` |
| LLM answers degraded | OAuth token expired | Restart agent (auto-refreshes) |
| "Cannot connect to eval server" banner | Platform crashed or not started | Run `./start.sh` |
| Suite run returns 0% scores | Auth not passing through | Update registered agent with auth config |

---

## END OF DEVOPS & RELIABILITY ENGINEER CHARTER
