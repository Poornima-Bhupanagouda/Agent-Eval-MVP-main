"""
=============================================================
  Lilly Agent Eval — Agentic Evaluation Demo
  Run this to see how we now inspect AGENT INTERNALS,
  not just final output.
=============================================================

Prerequisites: all services running (start-eval or manual):
  - Weather Agent   :8004
  - Wiki Agent      :8005
  - Calculator Agent:8006
  - Orchestrator    :8010
  - Eval Server     :8888
"""

import requests, json, time, sys, textwrap, io

EVAL = "http://localhost:8888"
WEATHER = "http://127.0.0.1:8004/chat"
ORCHESTRATOR = "http://127.0.0.1:8010/chat"

BLUE = "\033[94m"; GREEN = "\033[92m"; YELLOW = "\033[93m"
RED = "\033[91m"; BOLD = "\033[1m"; RESET = "\033[0m"
LINE = "─" * 60

# Duplicate output to file so we always have full results
_log = open("demo_output.txt", "w", encoding="utf-8")
_orig_print = print
def print(*args, **kwargs):
    _orig_print(*args, **kwargs)
    kwargs["file"] = _log
    _orig_print(*args, **kwargs)
    _log.flush()

def header(title):
    print(f"\n{BOLD}{BLUE}{'═'*60}")
    print(f"  {title}")
    print(f"{'═'*60}{RESET}\n")

def check_services():
    """Make sure everything is up."""
    for name, url in [("Eval Server", f"{EVAL}/api/health"),
                      ("Weather Agent", "http://127.0.0.1:8004/health"),
                      ("Orchestrator", "http://127.0.0.1:8010/health")]:
        try:
            r = requests.get(url, timeout=3)
            r.raise_for_status()
            print(f"  {GREEN}✓{RESET} {name}")
        except Exception:
            print(f"  {RED}✗{RESET} {name} — not reachable")
            print(f"\n{RED}Start services first (run start-eval or start them manually).{RESET}")
            sys.exit(1)

# ── DEMO 1: Direct Agent Call — See the Trace ──────────────
def demo_trace():
    header("DEMO 1 — Agent Trace (What's New)")
    print(f"  Calling Weather Agent: {YELLOW}\"What's the weather in Tokyo?\"{RESET}")
    print(f"  {LINE}")

    resp = requests.post(WEATHER, json={"input": "What's the weather in Tokyo?"}, timeout=30)
    data = resp.json()

    print(f"\n  {BOLD}Response:{RESET} {data['output'][:120]}...")
    print(f"\n  {BOLD}{GREEN}Agent Trace (execution pipeline):{RESET}")
    if data.get("trace"):
        for step in data["trace"]:
            dur = step.get("duration_ms", "?")
            status = f"{GREEN}✓{RESET}" if step.get("result") == "ok" else f"{RED}✗{RESET}"
            print(f"    {status} {step['node']:20s}  {dur:>6}ms")
        nodes = " → ".join(s["node"] for s in data["trace"])
        print(f"\n  Pipeline: {BOLD}{nodes}{RESET}")
    else:
        print(f"  {RED}No trace returned (agent may need update){RESET}")

    print(f"\n  {YELLOW}BEFORE:{RESET} We only saw the final text response.")
    print(f"  {GREEN}NOW:{RESET}    We see every step the agent took internally.")

# ── DEMO 2: Evaluation With Agent Internals ────────────────
def demo_eval_weather():
    header("DEMO 2 — Evaluation: Output + Agent Internals")
    print(f"  Running eval on Weather Agent with ALL metric types...\n")

    payload = {
        "endpoint": WEATHER,
        "input": "What's the weather in Tokyo?",
        "expected": "weather forecast for Tokyo with temperature",
        "metrics": ["answer_relevancy", "node_success_rate", "step_latency", "agent_reasoning"],
        "agent_type": "tool_using",
    }
    resp = requests.post(f"{EVAL}/api/test", json=payload, timeout=120)
    data = resp.json()

    # Show results
    print(f"  {BOLD}Overall Score: {data['score']}%{RESET}  |  {'PASS ✓' if data['passed'] else 'FAIL ✗'}")
    print(f"  Latency: {data['latency_ms']}ms\n")

    print(f"  {BOLD}{'Metric':<25} {'Score':>6}  {'Status':>6}  Category{RESET}")
    print(f"  {LINE}")
    for ev in data["evaluations"]:
        icon = f"{GREEN}PASS{RESET}" if ev["passed"] else f"{RED}FAIL{RESET}"
        cat = "Output Quality" if ev["metric"] == "answer_relevancy" else "Agent Internals"
        print(f"  {ev['metric']:<25} {ev['score']:>5.0f}%  {icon:>14}  {cat}")

    # Show trace if present
    if data.get("trace"):
        print(f"\n  {BOLD}Agent Trace (returned in eval):{RESET}")
        for step in data["trace"]:
            dur = step.get("duration_ms", "?")
            print(f"    ▸ {step['node']:20s}  {dur:>6}ms")

    print(f"\n  {YELLOW}KEY INSIGHT:{RESET}")
    print(f"  • answer_relevancy checks the {BOLD}final output{RESET} (what the user sees)")
    print(f"  • node_success_rate checks if {BOLD}every internal step succeeded{RESET}")
    print(f"  • step_latency detects {BOLD}bottleneck nodes{RESET} in the pipeline")
    print(f"  • agent_reasoning verifies the agent {BOLD}used proper multi-step reasoning{RESET}")

# ── DEMO 3: Orchestrator With Tool Metrics ──────────────────
def demo_orchestrator():
    header("DEMO 3 — Orchestrator: Tools + Internals")
    print(f"  Running eval on Travel Orchestrator...\n")

    payload = {
        "endpoint": ORCHESTRATOR,
        "input": "Plan a trip to Tokyo",
        "expected": "travel briefing for Tokyo with weather, attractions, and country info",
        "metrics": [
            "answer_relevancy",
            "tool_correctness", "tool_args_accuracy", "tool_sequence",
            "node_success_rate", "step_latency", "agent_reasoning",
        ],
        "agent_type": "orchestrator",
        "expected_tool_calls": [
            {"tool": "route_to_agent", "args": {"agent": "weather_agent"}},
            {"tool": "route_to_agent", "args": {"agent": "wiki_agent"}},
            {"tool": "route_to_agent", "args": {"agent": "calculator_agent"}},
        ],
    }
    resp = requests.post(f"{EVAL}/api/test", json=payload, timeout=180)
    data = resp.json()

    print(f"  {BOLD}Overall Score: {data['score']}%{RESET}  |  {'PASS ✓' if data['passed'] else 'FAIL ✗'}")
    print(f"  Latency: {data['latency_ms']}ms\n")

    categories = {
        "Output Quality": [],
        "Tool Use": [],
        "Agent Internals": [],
    }
    for ev in data["evaluations"]:
        m = ev["metric"]
        if m in ("tool_correctness", "tool_args_accuracy", "tool_sequence"):
            categories["Tool Use"].append(ev)
        elif m in ("node_success_rate", "step_latency", "agent_reasoning"):
            categories["Agent Internals"].append(ev)
        else:
            categories["Output Quality"].append(ev)

    for cat, evs in categories.items():
        if not evs:
            continue
        print(f"  {BOLD}{cat}:{RESET}")
        for ev in evs:
            icon = f"{GREEN}PASS{RESET}" if ev["passed"] else f"{YELLOW}WARN{RESET}"
            print(f"    {ev['metric']:<25} {ev['score']:>5.0f}%  {icon}")
        print()

    # Trace
    if data.get("trace"):
        print(f"  {BOLD}Orchestrator Pipeline:{RESET}")
        nodes = " → ".join(s["node"] for s in data["trace"])
        print(f"    {nodes}")
        print()

    # Tool calls
    if data.get("tool_calls"):
        print(f"  {BOLD}Tool Calls Made:{RESET}")
        for tc in data["tool_calls"]:
            print(f"    ▸ {tc.get('tool', tc.get('name', '?'))}")

    print(f"\n  {YELLOW}WHAT THIS PROVES:{RESET}")
    print(f"  We evaluate {BOLD}3 dimensions{RESET} of agent quality:")
    print(f"    1. Output Quality  — Is the answer good?")
    print(f"    2. Tool Use        — Did it call the right tools correctly?")
    print(f"    3. Agent Internals — Did the reasoning pipeline work properly?")

# ── SUMMARY ─────────────────────────────────────────────────
def summary():
    header("SUMMARY — Before vs After")
    print(f"  {BOLD}{RED}BEFORE (output-only evaluation):{RESET}")
    print(f"    • Send query, get response, check text quality")
    print(f"    • No visibility into HOW the agent reached its answer")
    print(f"    • Can't detect broken internal steps or slow nodes")
    print()
    print(f"  {BOLD}{GREEN}AFTER (agentic evaluation):{RESET}")
    print(f"    • Traced pipelines in every agent with auto-tracing")
    print(f"    • Trace flows through: Agent → Executor → Evaluator → UI")
    print(f"    • 3 new 'Agent Internals' metrics inspect the pipeline")
    print(f"    • Tool use metrics verify correct orchestration")
    print(f"    • UI shows interactive pipeline visualization")
    print()
    print(f"  {BOLD}New Metrics Added:{RESET}")
    print(f"    node_success_rate — Did every pipeline node complete without error?")
    print(f"    step_latency      — Are any nodes taking disproportionate time?")
    print(f"    agent_reasoning   — Does the agent follow a proper reasoning pattern?")
    print()
    print(f"  {BOLD}Try it in the UI:{RESET} http://localhost:8888")
    print()

# ── MAIN ────────────────────────────────────────────────────
if __name__ == "__main__":
    header("Lilly Agent Eval — Agentic Evaluation Demo")
    print("  Checking services...\n")
    check_services()

    demo_trace()
    demo_eval_weather()
    try:
        demo_orchestrator()
    except Exception as e:
        print(f"  {RED}Demo 3 error: {e}{RESET}")
        import traceback; traceback.print_exc()
    summary()
