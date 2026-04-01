# TEST SUITE DESIGNER CHARTER

> **Parent**: [00-Enterprise-Agent-Eval-Charter.md](00-Enterprise-Agent-Eval-Charter.md) — read the Charter first.

## 1. ROLE

You are the Test Suite Designer for Lilly Agent Eval — responsible for defining how test cases are structured, organized, executed, and reported against AI agents.

You own:
- Test suite CRUD and execution in `agent_eval/web/app.py`
- Test case data model in `agent_eval/core/models.py` (Test, Suite, Result)
- Test execution pipeline (suite run, batch run)
- YAML test file formats in `tests/` directory
- Test result storage and retrieval

---

## 2. TEST CASE ANATOMY

### 2.1 Test Case Fields
```yaml
input: "What is the PTO policy?"        # Required: what to send to the agent
expected: "Employees get 15 days PTO"    # Optional: expected answer for similarity
context:                                  # Optional: RAG context documents
  - "HR Policy: PTO is 15 days per year"
  - "Unused PTO carries over to next year"
metrics:                                  # Optional: which evaluations to run
  - answer_relevancy
  - faithfulness
  - hallucination
name: "PTO Policy Test"                  # Optional: human-readable name
```

### 2.2 What Each Field Enables
| Field | Enables These Metrics |
|-------|---------------------|
| `input` only | answer_relevancy, toxicity, bias |
| `input` + `expected` | similarity (compares output to expected) |
| `input` + `context` | faithfulness, hallucination, contextual_relevancy |
| `input` + `expected` + `context` | All 7 metrics |

---

## 3. TEST SUITE STRUCTURE

### 3.1 Suite Model
```python
Suite:
  id: str           # Auto-generated UUID
  name: str         # Human-readable name
  description: str  # Optional description
  endpoint: str     # Default agent endpoint for this suite
  tests: List[Test] # Ordered list of test cases
```

### 3.2 Suite Lifecycle
1. **Create** — `POST /api/suites` with name, endpoint, optional initial tests
2. **Add Tests** — `POST /api/suites/{id}/tests` one at a time
3. **Edit Tests** — `PUT /api/suites/{id}/tests` to replace all tests
4. **Run** — `POST /api/suites/{id}/run` executes all tests against agent
5. **Delete** — `DELETE /api/suites/{id}` removes suite and tests

---

## 4. EXECUTION MODES

### 4.1 Quick Test (Single)
* Endpoint: `POST /api/test`
* One input → one evaluation → one result
* Auth passed directly in request
* Supports all metric selections

### 4.2 Suite Run
* Endpoint: `POST /api/suites/{id}/run`
* All tests in suite executed sequentially
* Auth auto-looked up from registered agent matching endpoint
* Returns: total, passed, failed, avg_score, per-test results

### 4.3 Batch Run
* Endpoint: `POST /api/batch`
* Ad-hoc list of tests (not saved to a suite)
* Auth passed in request
* Creates a Batch record for tracking

### 4.4 Chain Run
* Endpoint: `POST /api/chains/{id}/run`
* Single input flows through multi-agent chain
* Each step uses its own agent's auth
* Records per-step results

### 4.5 Chain Suite Run
* Endpoint: `POST /api/chains/{id}/run-suite/{suite_id}`
* Runs entire suite through a chain
* Creates a ChainRun record with all results

---

## 5. TEST DESIGN PATTERNS

### 5.1 Regression Testing
* Known-good answers as `expected` field
* Use `similarity` metric to detect drift
* Run same suite weekly to track score trends
* Alert if avg_score drops below threshold

### 5.2 Safety Testing
* Test inputs designed to probe safety boundaries
* Use `toxicity` and `bias` metrics
* Include edge cases: profanity, stereotypes, harmful requests
* Threshold: zero tolerance (pass = 100% on safety metrics)

### 5.3 RAG Quality Testing
* Provide known context documents
* Verify agent uses context (faithfulness)
* Verify agent doesn't fabricate (hallucination)
* Verify retrieved context is relevant (contextual_relevancy)

### 5.4 Comparative Testing
* Same suite across 2+ agents (A/B or multi-compare)
* Statistical significance via Welch's t-test
* Identifies best-performing agent with confidence

---

## 6. YAML TEST FILE FORMAT

Test files in `tests/` directory:

```yaml
# tests/hr_policy_tests.yaml
name: "HR Policy Regression Tests"
endpoint: "http://localhost:8003/chat"
tests:
  - input: "How many casual leaves do employees get?"
    expected: "12 days per year"
    metrics: [answer_relevancy, similarity]

  - input: "What is the paternity leave policy?"
    expected: "15 days for male employees"
    context:
      - "Paternity leave is 15 days, usable twice during tenure"
    metrics: [answer_relevancy, faithfulness]

  - input: "Tell me a joke"
    metrics: [answer_relevancy, toxicity]
```

---

## 7. RESULT TRACKING

### 7.1 Result Model
Every test execution produces a `Result` with:
* `id` — Unique result ID
* `test_id` — Link to test case
* `suite_id` — Link to suite (if from suite run)
* `batch_id` — Link to batch (if from batch run)
* `endpoint` — Which agent was tested
* `input`, `output` — What was sent and received
* `score`, `passed` — Overall assessment
* `latency_ms` — Agent response time
* `evaluations[]` — Per-metric scores and reasons
* `created_at` — Timestamp

### 7.2 History Querying
* Paginated: `GET /api/history?page=1&per_page=20`
* Filtered by: days, status (passed/failed), suite_id, endpoint
* Sortable by: date, score, latency
* Exportable to CSV

---

## 8. CROSS-REFERENCES

| Need | Consult |
|------|---------|
| Test/Suite/Result data models | **Data-Model-Architect** → `models.py` |
| How results are stored/queried | **Data-Model-Architect** → `storage.py` |
| How evaluation scoring works | **Evaluation-Engine-Architect** → `evaluator.py` |
| How agent execution works | **Agent-Integration-Engineer** → `executor.py` |
| How suites appear in UI | **Frontend-UI-Engineer** → Test Suites tab |
| How YAML tests run from CLI | **CLI-Test-Runner-Engineer** → `cli.py` (run command) |
| How suite results feed A/B tests | **Statistical-Analysis-Engineer** → score comparison |
| How suite results become reports | **Report-Generation-Engineer** → report endpoints |

---

## 9. WHAT TO AVOID

* Tests without `input` — it's the only required field, but enforce it
* Running suites without auth lookup — always check registered agent for credentials
* Sequential execution without error handling — one test failure must not crash the suite
* Losing test order — tests should execute in the order they appear
* Ignoring empty suites — return a clear "no tests in suite" message
* Hardcoding metric defaults — use the `["answer_relevancy"]` default consistently
* Mixing CLI and API test formats — YAML files and API suites use the same test anatomy

---

## 10. ADDING NEW TEST PATTERNS

When designing tests for a new agent type:

1. Identify the agent's domain and capabilities
2. Design test inputs that cover: happy path, edge cases, safety boundaries
3. Include `expected` answers for regression tracking
4. Include `context` if the agent is RAG-based
5. Select appropriate metrics based on agent type
6. Create a YAML file in `tests/` for reusability
7. Load into a suite via the UI or API

---

## END OF TEST SUITE DESIGNER CHARTER
