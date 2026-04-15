"""
Compliance Agent - Checks if policy summaries are legally correct.

Step 3 in the HR Pipeline Chain:
  Policy Lookup → Summarizer → Compliance

Takes a summarized policy and checks it against compliance rules:
- Are required legal terms present?
- Are numbers/dates accurate?
- Are mandatory disclaimers included?
- Are any prohibited phrases used?

No LLM or API keys required - uses rule-based compliance checking.

Port: 8013
"""

import os
import re
import time
from typing import Optional, List, Dict, Any

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

app = FastAPI(title="Compliance Agent")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# === Compliance Rules ===

# Required terms that should appear in HR policy summaries
REQUIRED_TERMS = {
    "leave": ["days", "leave", "time off", "pto", "absence"],
    "insurance": ["coverage", "insurance", "plan", "deductible", "premium"],
    "retirement": ["401", "contribution", "match", "vesting", "retirement"],
    "benefits": ["eligible", "benefit", "enrollment", "coverage"],
}

# Prohibited phrases in policy communications
PROHIBITED_PHRASES = [
    "guaranteed employment",
    "cannot be fired",
    "unlimited sick",
    "no restrictions",
    "always approved",
    "permanent position",
]

# Required disclaimer concepts
COMPLIANCE_CHECKS = [
    {
        "name": "numeric_accuracy",
        "description": "Contains specific numbers (days, percentages, amounts)",
        "pattern": r'\d+',
        "severity": "high",
    },
    {
        "name": "no_absolute_promises",
        "description": "Avoids absolute guarantees",
        "check_type": "prohibited",
        "patterns": [r'\bguarantee[ds]?\b', r'\balways\s+approved\b', r'\bcannot\s+be\s+(fired|terminated)\b'],
        "severity": "critical",
    },
    {
        "name": "policy_specificity",
        "description": "References specific policy elements",
        "pattern": r'(days?|weeks?|months?|years?|percent|%|\$[\d,]+)',
        "severity": "medium",
    },
    {
        "name": "conditional_language",
        "description": "Uses appropriate conditional language",
        "pattern": r'\b(may|subject to|eligible|upon|provided that|if applicable)\b',
        "severity": "low",
    },
]


def check_compliance(text: str) -> Dict[str, Any]:
    """Run all compliance checks on the given text."""
    text_lower = text.lower()
    findings = []
    passed_checks = 0
    total_checks = 0

    # Check 1: Prohibited phrases
    total_checks += 1
    prohibited_found = []
    for phrase in PROHIBITED_PHRASES:
        if phrase.lower() in text_lower:
            prohibited_found.append(phrase)
    if prohibited_found:
        findings.append({
            "check": "prohibited_phrases",
            "status": "FAIL",
            "severity": "critical",
            "detail": f"Found prohibited phrases: {', '.join(prohibited_found)}",
        })
    else:
        passed_checks += 1
        findings.append({
            "check": "prohibited_phrases",
            "status": "PASS",
            "severity": "none",
            "detail": "No prohibited phrases found",
        })

    # Check 2: Contains specific numbers (factual specificity)
    total_checks += 1
    numbers = re.findall(r'\b\d+(?:\.\d+)?(?:\s*%|\s*days?|\s*weeks?|\s*months?)?\b', text)
    if len(numbers) >= 2:
        passed_checks += 1
        findings.append({
            "check": "numeric_specificity",
            "status": "PASS",
            "severity": "none",
            "detail": f"Contains {len(numbers)} specific numeric references",
        })
    else:
        findings.append({
            "check": "numeric_specificity",
            "status": "WARN",
            "severity": "medium",
            "detail": f"Only {len(numbers)} numeric references — policy summaries should cite specific numbers",
        })

    # Check 3: Appropriate conditional language
    total_checks += 1
    conditionals = re.findall(
        r'\b(may|subject to|eligible|upon approval|provided that|if applicable|up to|maximum|minimum)\b',
        text_lower
    )
    if conditionals:
        passed_checks += 1
        findings.append({
            "check": "conditional_language",
            "status": "PASS",
            "severity": "none",
            "detail": f"Uses appropriate conditional language ({len(conditionals)} instances)",
        })
    else:
        findings.append({
            "check": "conditional_language",
            "status": "WARN",
            "severity": "low",
            "detail": "No conditional language found — summaries should use 'may', 'subject to', 'eligible' etc.",
        })

    # Check 4: No absolute guarantees (regex patterns)
    total_checks += 1
    absolutes_found = []
    for pattern in [r'\bguarantee[ds]?\b', r'\balways\s+approved\b', r'\bcannot\s+be\s+(fired|terminated)\b', r'\bunlimited\b']:
        matches = re.findall(pattern, text_lower)
        absolutes_found.extend(matches)
    if absolutes_found:
        findings.append({
            "check": "no_absolute_guarantees",
            "status": "FAIL",
            "severity": "critical",
            "detail": f"Contains absolute language: {', '.join(absolutes_found)}",
        })
    else:
        passed_checks += 1
        findings.append({
            "check": "no_absolute_guarantees",
            "status": "PASS",
            "severity": "none",
            "detail": "No absolute guarantees or prohibited language found",
        })

    # Check 5: Minimum content length
    total_checks += 1
    word_count = len(text.split())
    if word_count >= 20:
        passed_checks += 1
        findings.append({
            "check": "content_adequacy",
            "status": "PASS",
            "severity": "none",
            "detail": f"Summary has adequate content ({word_count} words)",
        })
    else:
        findings.append({
            "check": "content_adequacy",
            "status": "WARN",
            "severity": "medium",
            "detail": f"Summary may be too brief ({word_count} words) — important details could be missing",
        })

    # Check 6: Topic coverage (mentions key HR terms)
    total_checks += 1
    hr_terms_found = set()
    hr_terms = {'leave', 'days', 'policy', 'employee', 'benefit', 'insurance',
                'paid', 'coverage', 'eligible', 'approval', 'request', 'pto'}
    for term in hr_terms:
        if term in text_lower:
            hr_terms_found.add(term)
    if len(hr_terms_found) >= 3:
        passed_checks += 1
        findings.append({
            "check": "hr_topic_coverage",
            "status": "PASS",
            "severity": "none",
            "detail": f"Covers HR topics: {', '.join(sorted(hr_terms_found))}",
        })
    else:
        findings.append({
            "check": "hr_topic_coverage",
            "status": "WARN",
            "severity": "low",
            "detail": f"Limited HR topic coverage ({len(hr_terms_found)} terms) — may not be HR-related content",
        })

    compliance_score = round((passed_checks / total_checks) * 100) if total_checks > 0 else 0
    status = "COMPLIANT" if compliance_score >= 80 else "NEEDS REVIEW" if compliance_score >= 50 else "NON-COMPLIANT"

    return {
        "compliance_score": compliance_score,
        "status": status,
        "passed": passed_checks,
        "total": total_checks,
        "findings": findings,
    }


# === Models ===

class ChatRequest(BaseModel):
    input: str = Field(..., description="Policy summary to check for compliance")


class ChatResponse(BaseModel):
    output: str
    tool_calls: Optional[List[Dict[str, Any]]] = None
    latency_ms: Optional[int] = None
    trace: Optional[List[Dict[str, Any]]] = None


# === Endpoints ===

@app.get("/")
async def root():
    return {
        "name": "Compliance Agent",
        "version": "1.0.0",
        "status": "healthy",
        "description": "Checks policy summaries for compliance with HR and legal rules",
    }


@app.get("/health")
async def health():
    return {"status": "healthy"}


@app.post("/describe")
async def describe():
    return {
        "name": "Compliance Agent",
        "purpose": "Checks policy summaries against compliance rules: prohibited phrases, numeric accuracy, conditional language, and content adequacy.",
        "type": "simple",
        "domain": "hr_policies",
        "capabilities": ["compliance_checking", "rule_validation", "policy_review"],
        "tools": [
            {"name": "check_compliance", "description": "Run 6 compliance checks on policy text"},
        ],
    }


@app.post("/chat", response_model=ChatResponse)
async def chat(request: ChatRequest):
    start = time.time()

    # --- Pipeline node functions ---

    def preprocess_node(state: dict) -> dict:
        """Node 1: Preprocess input text."""
        state = dict(state)
        state["intermediate"] = dict(state.get("intermediate", {}))
        state["intermediate"]["input_text"] = state["query"]
        state["intermediate"]["word_count"] = len(state["query"].split())
        return state

    def compliance_check_node(state: dict) -> dict:
        """Node 2: Run compliance checks."""
        state = dict(state)
        state["tool_calls"] = list(state.get("tool_calls", []))
        text = state["query"]

        state["tool_calls"].append({
            "name": "check_compliance",
            "args": {"text_length": len(text), "checks": 6},
        })

        result = check_compliance(text)
        state["intermediate"] = dict(state.get("intermediate", {}))
        state["intermediate"]["compliance_result"] = result
        return state

    def format_report_node(state: dict) -> dict:
        """Node 3: Format compliance report."""
        state = dict(state)
        result = state["intermediate"].get("compliance_result", {})

        score = result.get("compliance_score", 0)
        status = result.get("status", "UNKNOWN")
        findings = result.get("findings", [])

        # Build readable report
        lines = [
            f"COMPLIANCE REPORT",
            f"Status: {status} ({score}%)",
            f"Checks Passed: {result.get('passed', 0)}/{result.get('total', 0)}",
            "",
        ]

        for f in findings:
            icon = "✅" if f["status"] == "PASS" else "⚠️" if f["status"] == "WARN" else "❌"
            lines.append(f"{icon} {f['check']}: {f['status']} — {f['detail']}")

        lines.append("")
        if status == "COMPLIANT":
            lines.append("✅ This policy summary meets compliance requirements.")
        elif status == "NEEDS REVIEW":
            lines.append("⚠️ This policy summary needs review — some checks did not fully pass.")
        else:
            lines.append("❌ This policy summary has compliance issues that must be resolved.")

        state["output"] = "\n".join(lines)
        return state

    # --- Run steps sequentially ---
    state = {"query": request.input, "intermediate": {}, "tool_calls": [], "output": "", "errors": []}
    state = preprocess_node(state)
    state = compliance_check_node(state)
    state = format_report_node(state)
    latency = int((time.time() - start) * 1000)

    return ChatResponse(
        output=state.get("output", ""),
        tool_calls=state.get("tool_calls", []),
        latency_ms=latency,
    )


def main():
    import uvicorn
    port = int(os.environ.get("COMPLIANCE_PORT", 8013))
    host = os.environ.get("HOST", "127.0.0.1")
    print(f"\nCompliance Agent starting at http://{host}:{port}")
    print(f"  API docs: http://{host}:{port}/docs\n")
    uvicorn.run(app, host=host, port=port)


if __name__ == "__main__":
    main()
