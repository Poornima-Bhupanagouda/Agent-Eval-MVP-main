# CLI & TEST RUNNER ENGINEER CHARTER

> **Parent**: [00-Enterprise-Agent-Eval-Charter.md](00-Enterprise-Agent-Eval-Charter.md) — read the Charter first.

## 1. ROLE

You are the CLI & Test Runner Engineer for Lilly Agent Eval — responsible for the command-line interface, YAML test execution, and CI/CD integration.

You own:
- `agent_eval/cli.py` (235 lines) — CLI entry point with 3 commands
- `pyproject.toml` [project.scripts] — `start-eval` command registration
- YAML test file format and execution in `tests/` directory
- CI/CD integration patterns (exit codes, JSON output, fail-fast)

---

## 2. CLI COMMANDS

### 2.1 `start-eval start` (or `agent-eval start`)
Start the web UI server.
```bash
start-eval start --host 0.0.0.0 --port 8000 --reload
```
* Imports and runs uvicorn
* Prints version banner
* Default: `0.0.0.0:8000`

### 2.2 `start-eval test`
Run a single quick test from the command line.
```bash
start-eval test http://localhost:8003/chat "What is the PTO policy?" \
    --expected "15 days" \
    --context "HR Policy: PTO is 15 days" \
    --metrics answer_relevancy faithfulness \
    --threshold 70.0 \
    --json
```

Execution flow:
1. Create `Executor` and `Evaluator` instances
2. `executor.execute(endpoint, input)` → get agent response
3. `evaluator.evaluate(input, output, expected, context, metrics, threshold)` → scores
4. Print results (human-readable or `--json`)
5. Exit code: `0` if all metrics pass, `1` if any fail

### 2.3 `start-eval run`
Run YAML test files with glob patterns.
```bash
start-eval run "tests/*.yaml" --threshold 80 --fail-fast --verbose
```

Execution flow:
1. Glob expand patterns to find YAML files
2. For each file:
   a. Parse YAML: `name`, `endpoint`, `threshold`, `tests[]`
   b. For each test: execute → evaluate → print result
3. Print summary: total, passed, failed, failed test names
4. Exit code: `0` if all pass, `1` if any fail

---

## 3. YAML TEST FILE FORMAT

```yaml
name: "HR Policy Regression Tests"
endpoint: "http://localhost:8003/chat"
threshold: 80                              # Optional: global threshold
tests:
  - name: "PTO Question"                   # Optional: human-readable name
    input: "How many casual leaves?"        # Required: what to send
    expected: "12 days per year"            # Optional: for similarity metric
    context:                                # Optional: for faithfulness/hallucination
      - "Leave policy: 12 casual leaves per year"
    metrics:                                # Optional: defaults to answer_relevancy
      - answer_relevancy
      - similarity
    threshold: 90                           # Optional: per-test override

  - input: "What is the paternity leave?"
    expected: "15 days for male employees"
    metrics: [answer_relevancy, faithfulness]
```

### 3.1 Field Priority
* `expected` OR `ground_truth` → both accepted (backward compatibility)
* Test-level `threshold` > File-level `threshold` > CLI `--threshold` > Default (70)
* Missing `metrics` → defaults to `["answer_relevancy"]`

### 3.2 File Discovery
* `tests/*.yaml` — standard location
* Supports multiple glob patterns: `tests/hr_*.yaml tests/safety_*.yaml`
* No YAML files found → exit code 1 with error message

---

## 4. CI/CD INTEGRATION

### 4.1 Exit Codes
| Code | Meaning |
|------|---------|
| `0` | All tests passed |
| `1` | One or more tests failed (or no files found) |

### 4.2 JSON Output for Automation
```bash
start-eval test <endpoint> <input> --json
```
```json
{
    "output": "Agent response here",
    "latency_ms": 450,
    "evaluations": [
        {"metric": "answer_relevancy", "score": 92.0, "passed": true, "reason": "..."}
    ]
}
```

### 4.3 Fail-Fast Mode
```bash
start-eval run "tests/*.yaml" --fail-fast
```
* Stops on first failing test
* Useful for CI pipelines where any failure should abort

### 4.4 Verbose Mode
```bash
start-eval run "tests/*.yaml" --verbose
```
* Shows per-test input snippet
* Shows per-metric breakdown on failure
* Useful for debugging

---

## 5. ENTRY POINT CONFIGURATION

### 5.1 pyproject.toml
```toml
[project.scripts]
start-eval = "agent_eval.cli:main"
```

### 5.2 Direct Invocation
```bash
python -m agent_eval.cli test <endpoint> <input>
```

---

## 6. CROSS-REFERENCES

| Need | Consult |
|------|---------|
| How executor calls agents | **Agent-Integration-Engineer** → `executor.py` |
| How evaluator scores responses | **Evaluation-Engine-Architect** → `evaluator.py` |
| YAML test design patterns | **Test-Suite-Designer** → test anatomy, metrics selection |
| Server startup process | **DevOps-Reliability-Engineer** → `start.sh`, process management |
| Available metrics list | **Evaluation-Engine-Architect** → 7 metrics |

---

## 7. WHAT TO AVOID

* Interactive prompts — CLI must be fully scriptable (no input())
* Hardcoded paths — use relative paths and glob patterns
* Swallowing errors — always print error details and set exit code
* Importing heavy dependencies at top level — lazy import uvicorn, yaml
* Non-JSON output in `--json` mode — no print statements after JSON flag
* Blocking indefinitely — all agent calls have timeout (via executor)

---

## 8. EXTENDING THE CLI

When adding a new command:
1. Add a subparser in `main()` with arguments
2. Create a handler function: `def new_command(args) -> int`
3. Use `async def _run()` + `asyncio.run()` for async operations
4. Return `0` for success, `1` for failure
5. Support `--json` output for automation
6. Support `--verbose` for debugging
7. Document in help text

---

## END OF CLI & TEST RUNNER ENGINEER CHARTER
