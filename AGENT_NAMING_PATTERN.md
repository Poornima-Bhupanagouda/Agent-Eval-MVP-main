# Agent Naming Pattern

All evaluation agents follow the pattern: `{purpose}_agent`

## Renamed Agents

| Old Name | New Name | Purpose |
|----------|----------|---------|
| rule_based | **rule_validation_agent** | Validates output against deterministic rules |
| llm_judge | **quality_assessment_agent** | LLM-powered quality assessment |
| tool_validator | **tool_validation_agent** | Validates tool call sequences |
| context_evaluator | **context_validation_agent** | Validates context/KB/RAG usage |

## New Agents

| Agent Name | Purpose | Status |
|------------|---------|--------|
| **hallucination_check_agent** | Detects hallucinations and factual errors | ✓ To be implemented |
| **safety_check_agent** | Checks for unsafe/harmful content | Planned |
| **pii_detection_agent** | Detects personally identifiable information | Planned |
| **bias_detection_agent** | Detects biased or discriminatory content | Planned |

## Pattern Benefits

1. **Clear Purpose** - Agent name describes what it does
2. **Consistent Naming** - All agents end with `_agent`
3. **Easy Discovery** - Simple to find agents in code
4. **User-Friendly** - Non-technical users understand agent purposes

## Usage in UI

In the web UI, agents will be displayed as:
- ✓ Rule Validation Agent
- ✓ Quality Assessment Agent  
- ✓ Tool Validation Agent
- ✓ Context Validation Agent
- ✓ Hallucination Check Agent

Users can select which agents to run for each test case via checkboxes.
