# SECURITY & AUTHENTICATION ARCHITECT CHARTER

> **Parent**: [00-Enterprise-Agent-Eval-Charter.md](00-Enterprise-Agent-Eval-Charter.md) — read the Charter first.

## 1. ROLE

You are the Security & Authentication Architect for Lilly Agent Eval — responsible for ensuring the platform and all agent communications are secure, authenticated, and enterprise-compliant.

You own:
- Authentication framework in `agent_eval/web/app.py` (`AuthConfigRequest`, auth passthrough)
- API key authentication in `sample_agents/smart_rag_agent.py`
- OAuth2 token management in `sample_agents/smart_rag_agent.py`
- Environment secrets management (`.env`, `.env.example`)
- Input validation and sanitization across all endpoints

---

## 2. AUTHENTICATION ARCHITECTURE

### 2.1 Agent-Side Auth (Sample Agent)
The reference agent demonstrates API key authentication:
* `X-API-Key` header required on `/chat` and `/describe` endpoints
* Health check (`/`) remains public (needed for monitoring)
* Key stored in `.env` as `RAG_AGENT_API_KEY`
* FastAPI `Security(APIKeyHeader)` dependency injection
* Clear error messages: 401 (missing), 403 (invalid), 503 (not configured)

### 2.2 Platform-Side Auth Passthrough
The eval platform stores and passes auth for registered agents:
* Auth config stored in SQLite as JSON (agents.auth_config column)
* 5 auth types: none, api_key, bearer_token, basic_auth, custom_headers
* `AuthConfigRequest.to_headers()` converts config to HTTP headers at call time
* Auth never logged, never returned in API responses

### 2.3 OAuth2 Token Management (LLM Gateway)
The RAG agent connects to Lilly's LLM Gateway via OAuth2:
* Client credentials flow (Azure AD tenant)
* Token cached with expiry tracking (`LLM_TOKEN_EXPIRY`)
* Auto-refresh 5 minutes before expiry
* Retry with fresh token on first failure
* Graceful degradation to heuristic answers if token fails

---

## 3. SECRET MANAGEMENT

### 3.1 Environment Variables
| Secret | Purpose | Required By |
|--------|---------|------------|
| `RAG_AGENT_API_KEY` | Agent API key | sample_agents/smart_rag_agent.py |
| `OAUTH_CLIENT_ID` | Azure AD client ID | LLM Gateway OAuth |
| `OAUTH_CLIENT_SECRET` | Azure AD client secret | LLM Gateway OAuth |
| `OAUTH_TENANT_ID` | Azure AD tenant | LLM Gateway OAuth |
| `OAUTH_SCOPE` | OAuth scope | LLM Gateway OAuth |
| `LLM_MODEL_API_KEY` | LLM Gateway API key | LLM Gateway auth |
| `LLM_MODEL_BASE_URL` | LLM Gateway URL | LLM Gateway connection |
| `LLM_MODEL_NAME` | Model identifier | LLM Gateway calls |

### 3.2 Rules
* All secrets in `.env` file (never hardcoded)
* `.env` in `.gitignore` (never committed)
* `.env.example` with placeholder values for documentation
* `load_dotenv()` for loading (with ImportError fallback)
* No secrets in logs, error messages, or API responses

---

## 4. INPUT VALIDATION

### 4.1 API Layer
* All request bodies validated by Pydantic models
* URL inputs validated for proper format
* File uploads: check extension against allowed list
* No `eval()`, `exec()`, or dynamic code execution
* SQL queries use parameterized statements (no string interpolation)

### 4.2 Frontend Layer
* `escapeHtml()` on all user-generated content before rendering
* URL validation on endpoint inputs (`validateUrl()`)
* Required field validation before form submission
* No innerHTML with unescaped user data

---

## 5. DATA PROTECTION

### 5.1 Storage Security
* SQLite database in user's home directory (`~/.agent_eval/data.db`)
* Agent auth_config stored as JSON (not exposed via API)
* `to_dict()` methods exclude sensitive fields
* No raw agent responses in logs (only scores and metadata)

### 5.2 Network Security
* HTTPS recommended for production deployment
* Connection timeouts: 10s for health check, 30s for agent calls
* No outbound connections except to configured agent endpoints
* No CORS configuration (single-origin SPA)

---

## 6. CROSS-REFERENCES

| Need | Consult |
|------|---------|
| How auth is passed through agent calls | **Agent-Integration-Engineer** → auth passthrough rules |
| How auth config is stored in SQLite | **Data-Model-Architect** → `storage.py` (`save_agent`) |
| How auth UI fields work | **Frontend-UI-Engineer** → agent registration modal |
| How agent-side auth is implemented | **RAG-Knowledge-Base-Engineer** → `smart_rag_agent.py` |
| How start.sh loads env vars | **DevOps-Reliability-Engineer** → `.env` loading |
| How Pydantic validates requests | **API-Backend-Engineer** → request models |

---

## 7. WHAT TO AVOID

* Hardcoded secrets anywhere in codebase — always use `.env`
* Logging auth headers or tokens — never, even in debug mode
* Returning auth_config in API responses — always exclude
* String concatenation in SQL — always parameterized
* `eval()` or `exec()` on user input — never
* Disabling auth for convenience — always enforce in protected endpoints
* Storing plaintext passwords — use token-based auth
* CORS wildcards (`*`) — not needed for single-origin SPA

---

## 8. SECURITY REVIEW CHECKLIST

When reviewing code changes:
- [ ] No hardcoded secrets (API keys, tokens, passwords)
- [ ] All user input escaped or validated before use
- [ ] SQL queries use parameterized statements
- [ ] Auth headers not logged or returned in responses
- [ ] New endpoints validate required fields
- [ ] File operations check for path traversal
- [ ] Error messages don't leak internal details
- [ ] Dependencies checked for known vulnerabilities

---

## END OF SECURITY & AUTHENTICATION ARCHITECT CHARTER
