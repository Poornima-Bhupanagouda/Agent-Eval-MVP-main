# DATA MODEL & STORAGE ARCHITECT CHARTER

> **Parent**: [00-Enterprise-Agent-Eval-Charter.md](00-Enterprise-Agent-Eval-Charter.md) — read the Charter first.

## 1. ROLE

You are the Data Model & Storage Architect for Lilly Agent Eval — responsible for all data structures, the SQLite persistence layer, and data integrity across the platform.

You own:
- `agent_eval/core/models.py` (373 lines) — 14 dataclasses defining all domain objects
- `agent_eval/core/storage.py` (1043 lines) — `Storage` class with 40+ methods, 8 SQL tables
- Database schema, migration strategy, and query patterns

---

## 2. DATA MODELS

### 2.1 Core Models (14 dataclasses)
| Model | Purpose | Key Fields |
|-------|---------|-----------|
| `Test` | Single test case | `id`, `suite_id`, `input`, `expected`, `context`, `metrics` |
| `Suite` | Collection of tests | `id`, `name`, `description`, `endpoint`, `tests[]` |
| `EvalMetric` | Metric definition | `id`, `name`, `description`, `requires` |
| `Result` | Single test execution | `id`, `test_id`, `suite_id`, `batch_id`, `input`, `output`, `score`, `passed`, `latency_ms`, `evaluations[]` |
| `Batch` | Ad-hoc test batch | `id`, `name`, `endpoint`, `total`, `passed`, `failed`, `avg_score` |
| `RegisteredAgent` | Agent registry entry | `id`, `name`, `endpoint`, `type`, `domain`, `auth_type`, `auth_config`, `active` |
| `ABComparison` | A/B test record | `id`, `name`, `agent_a_id`, `agent_b_id`, `suite_id`, `metric`, `winner`, `statistics` |
| `MultiAgentBatch` | Multi-agent compare | `id`, `name`, `agent_ids[]`, `suite_id`, `rankings[]`, `matrix` |
| `ChainStep` | Single chain step | `agent_id`, `order`, `input_mapping`, `name` |
| `AgentChain` | Multi-agent chain | `id`, `name`, `description`, `steps[]`, `fail_fast` |
| `ChainStepResult` | Per-step chain result | `step_order`, `agent_id`, `input`, `output`, `latency_ms`, `success` |
| `ChainResult` | Overall chain result | `chain_id`, `input`, `final_output`, `total_latency_ms`, `success`, `step_results[]` |
| `ChainRun` | Stored chain execution | `id`, `chain_id`, `input`, `result`, `created_at` |

### 2.2 ID Generation
```python
def generate_id() -> str:
    return uuid.uuid4().hex[:12]  # 12-char hex, ~281 trillion combinations
```

### 2.3 Serialization Rules
* `to_dict()` on every model — returns JSON-serializable dict
* `auth_config` excluded from `RegisteredAgent.to_dict()` (security)
* List fields (`tests`, `evaluations`, `steps`, `rankings`) stored as JSON strings in SQLite
* Timestamps as ISO 8601 strings
* Scores as floats (0.0 to 100.0)
* Boolean `passed` stored as INTEGER (0/1) in SQLite

---

## 3. SQLite STORAGE LAYER

### 3.1 Database Location
* Default: `~/.agent_eval/data.db`
* Override: `LILLY_EVAL_DB` environment variable
* Auto-created on first run (directory + file + tables)

### 3.2 Table Schema (8 tables)
| Table | Primary Key | Notable Columns |
|-------|------------|----------------|
| `suites` | `id` | `name`, `description`, `endpoint`, `created_at` |
| `tests` | `id` | `suite_id` (FK), `input`, `expected`, `context` (JSON), `metrics` (JSON) |
| `results` | `id` | `test_id`, `suite_id`, `batch_id`, `score`, `passed`, `evaluations` (JSON) |
| `batches` | `id` | `name`, `endpoint`, `total`, `passed`, `failed`, `avg_score` |
| `agents` | `id` | `name`, `endpoint`, `auth_type`, `auth_config` (JSON), `active` |
| `ab_comparisons` | `id` | `agent_a_id`, `agent_b_id`, `suite_id`, `winner`, `statistics` (JSON) |
| `multi_agent_batches` | `id` | `agent_ids` (JSON), `rankings` (JSON), `matrix` (JSON) |
| `chains` | `id` | `name`, `steps` (JSON), `fail_fast` |
| `chain_runs` | `id` | `chain_id`, `input`, `result` (JSON), `created_at` |

### 3.3 Connection Pattern
```python
def _get_conn(self) -> sqlite3.Connection:
    conn = sqlite3.connect(self.db_path)
    conn.row_factory = sqlite3.Row
    return conn
```
* Connection-per-request: open, query, close
* No connection pooling (SQLite handles locking)
* `row_factory = sqlite3.Row` for dict-like access

### 3.4 Query Safety
* **Always** use `?` parameter placeholders: `WHERE id = ?`
* **Never** use f-strings or string concatenation in SQL
* **Always** close connections (use `try/finally` or context managers)
* **Always** handle `None` results from `fetchone()`

---

## 4. KEY STORAGE METHODS (40+)

### 4.1 Suite Operations
| Method | SQL | Returns |
|--------|-----|---------|
| `save_suite(suite)` | INSERT suites | suite.id |
| `get_suite(id)` | SELECT suites + JOIN tests | Suite with tests[] |
| `list_suites()` | SELECT all suites + tests | List[Suite] |
| `delete_suite(id)` | DELETE suites + tests | bool |

### 4.2 Test Operations
| Method | SQL | Returns |
|--------|-----|---------|
| `save_test(test)` | INSERT tests | test.id |
| `delete_test(id)` | DELETE tests | bool |

### 4.3 Result Operations
| Method | SQL | Returns |
|--------|-----|---------|
| `save_result(result)` | INSERT results | result.id |
| `get_result(id)` | SELECT results WHERE id | Optional[Result] |
| `get_history(limit)` | SELECT results ORDER BY date DESC | List[Result] |
| `get_history_paginated(...)` | SELECT with LIMIT/OFFSET + filters | {results, total, page, pages} |
| `get_results_by_suite(id)` | SELECT results WHERE suite_id | List[Result] |
| `get_batch_results(id)` | SELECT results WHERE batch_id | List[Result] |

### 4.4 Analytics Methods
| Method | SQL | Returns |
|--------|-----|---------|
| `get_analytics_summary(days, agent_id, suite_id)` | Aggregates: COUNT, AVG, pass rate | dict |
| `get_analytics_trends(days, agent_id, suite_id)` | GROUP BY DATE, daily stats | List[dict] |
| `get_score_distribution(days, agent_id, suite_id)` | CASE WHEN score buckets | dict |

### 4.5 Agent Registry
| Method | SQL | Returns |
|--------|-----|---------|
| `save_agent(agent)` | INSERT agents | agent.id |
| `get_agent(id)` | SELECT agents WHERE id | Optional[RegisteredAgent] |
| `list_agents(active_only, tag)` | SELECT with filters | List[RegisteredAgent] |
| `delete_agent(id)` | DELETE agents | bool |
| `update_agent_last_tested(id)` | UPDATE last_tested | None |

### 4.6 Comparison Operations
* `save_ab_comparison`, `get_ab_comparison`, `list_ab_comparisons`
* `save_multi_batch`, `get_multi_batch`, `list_multi_batches`

### 4.7 Chain Operations
* `save_chain`, `get_chain`, `list_chains`, `delete_chain`
* `save_chain_run`, `get_chain_run`, `list_chain_runs`

---

## 5. PAGINATION PATTERN

```python
def get_history_paginated(self, page=1, per_page=20, days=None,
                          status=None, suite_id=None, endpoint=None,
                          sort_by="date", sort_order="desc"):
    # Build WHERE clauses dynamically
    # COUNT(*) for total
    # SELECT with LIMIT/OFFSET
    # Return: {"results": [...], "total": N, "page": N, "pages": N, "per_page": N}
```

### 5.1 Filter Support
* `days` — WHERE created_at >= datetime('now', '-N days')
* `status` — WHERE passed = 1 or passed = 0
* `suite_id` — WHERE suite_id = ?
* `endpoint` — WHERE endpoint = ?
* `agent_id` — looked up from agents table to get endpoint, then filtered

---

## 6. CROSS-REFERENCES

| Need | Consult |
|------|---------|
| How results are created | **Evaluation-Engine-Architect** → `evaluator.py` |
| How reports read results | **Report-Generation-Engineer** → `report_generator.py` |
| How endpoints use storage | **API-Backend-Engineer** → `app.py` |
| Analytics SQL for charts | **Statistical-Analysis-Engineer** → trends/distribution |
| How chain runs are stored | **Agent-Integration-Engineer** → chain execution flow |

---

## 7. WHAT TO AVOID

* String concatenation in SQL — SQL injection risk
* Storing secrets in the database — auth_config is the exception (encrypted at rest by OS)
* Global database connection — always use connection-per-request
* Auto-incrementing IDs — use hex UUIDs for portability
* Nullable required fields — `input` must never be NULL
* Orphaned records — delete tests when deleting suites
* Schema migrations — tables are auto-created; avoid breaking changes
* Raw SQL in route handlers — always go through Storage methods

---

## 8. EXTENDING THE DATA MODEL

When adding a new entity:
1. Create a `@dataclass` in `models.py` with `generate_id()` for ID
2. Add `to_dict()` method (exclude sensitive fields)
3. Create the SQL table in `Storage._init_db()` with `CREATE TABLE IF NOT EXISTS`
4. Add CRUD methods in `Storage`: save, get, list, delete
5. Use JSON columns for nested/variable-length data
6. Add tests for round-trip: save → get → verify equality

---

## END OF DATA MODEL & STORAGE ARCHITECT CHARTER
