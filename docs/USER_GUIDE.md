# Lilly Agent Eval - User Guide

A comprehensive evaluation platform for AI agents powered by DeepEval.

## Table of Contents

1. [Getting Started](#1-getting-started)
2. [Core Concepts](#2-core-concepts)
3. [Running Evaluations](#3-running-evaluations)
4. [DeepEval Metrics Reference](#4-deepeval-metrics-reference)
5. [Dataset Management](#5-dataset-management)
6. [Red Teaming](#6-red-teaming)
7. [Custom Metrics](#7-custom-metrics)
8. [CI/CD Integration](#8-cicd-integration)
9. [API Reference](#9-api-reference)

---

## 1. Getting Started

### 1.1 Installation

```bash
# Clone the repository
git clone <repo-url>
cd agent-eval-mvp

# Install dependencies using Poetry
poetry install

# Or using pip
pip install -e .
```

### 1.2 Configuration

Create a `.env` file with your API keys:

```env
# Required for DeepEval metrics
OPENAI_API_KEY=sk-your-openai-key

# Optional: Confident AI Cloud integration
CONFIDENT_AI_API_KEY=your-confident-ai-key

# Optional: Langfuse observability
LANGFUSE_PUBLIC_KEY=your-langfuse-public-key
LANGFUSE_SECRET_KEY=your-langfuse-secret-key
```

### 1.3 Starting the Application

```bash
# Start the web UI
./start-eval

# Or manually
poetry run uvicorn agent_eval.web.app:app --host 0.0.0.0 --port 8000
```

Access the UI at: http://localhost:8000

---

## 2. Core Concepts

### 2.1 Test Cases

A test case represents a single evaluation scenario:

```python
{
    "input": "What is the capital of France?",
    "expected_output": "Paris",  # Optional
    "context": ["France is a country in Europe. Its capital is Paris."],  # For RAG
    "metadata": {}  # Additional data
}
```

### 2.2 Metrics

DeepEval provides industry-standard metrics for evaluating LLM outputs:

| Category | Metrics |
|----------|---------|
| **RAG** | Faithfulness, Context Precision, Context Recall, Hallucination |
| **Quality** | Answer Relevancy, Summarization, G-Eval |
| **Safety** | Bias, Toxicity |
| **Technical** | JSON Correctness, Tool Correctness |
| **Conversational** | Conversation Quality, Knowledge Retention |

### 2.3 Evaluation Results

Each evaluation returns:
- **Score**: 0-100 scale
- **Passed/Failed**: Based on threshold
- **Reasoning**: Explanation of the score
- **Details**: Metric-specific information

---

## 3. Running Evaluations

### 3.1 Quick Evaluation (Web UI)

1. Navigate to the **Evaluate** page
2. Enter your test input
3. Provide agent response or connect an agent
4. Select metrics to run
5. Click **Run Evaluation**

### 3.2 Dataset-based Evaluation

1. Navigate to **Datasets**
2. Create or import a dataset
3. Go to **Evaluate** and select your dataset
4. Configure metrics and thresholds
5. Run batch evaluation

### 3.3 Programmatic Evaluation

```python
from agent_eval.integrations import get_deepeval_evaluator

evaluator = get_deepeval_evaluator()

# Single metric evaluation
result = evaluator.evaluate_answer_relevancy(
    input_text="What is AI?",
    output_text="AI is artificial intelligence...",
    threshold=0.7
)

print(f"Score: {result.score}")
print(f"Passed: {result.passed}")
print(f"Reason: {result.reason}")
```

### 3.4 Choosing Metrics

| Use Case | Recommended Metrics |
|----------|---------------------|
| RAG Applications | Faithfulness, Context Precision, Context Recall, Hallucination |
| Chatbots | Answer Relevancy, Conversation Quality, Toxicity |
| Summarization | Summarization, Faithfulness |
| Code Generation | JSON Correctness, Tool Correctness |
| Safety Critical | Bias, Toxicity, Hallucination |

---

## 4. DeepEval Metrics Reference

### 4.1 RAG Metrics

#### Faithfulness
Evaluates if the output is grounded in the provided context.

```python
result = evaluator.evaluate_faithfulness(
    input_text="Question about the document",
    output_text="Agent's response",
    context=["Document chunk 1", "Document chunk 2"],
    threshold=0.7
)
```

**Score Interpretation:**
- 1.0: Fully grounded in context
- 0.5: Partially grounded
- 0.0: Contains unsupported claims

#### Context Precision
Evaluates if retrieved documents are relevant.

#### Context Recall
Evaluates if context contains all needed information.

#### Hallucination
Detects made-up facts not in the context.

**Note:** For hallucination, lower scores are better (less hallucination).

### 4.2 Quality Metrics

#### Answer Relevancy
Evaluates if the answer addresses the question.

```python
result = evaluator.evaluate_answer_relevancy(
    input_text="How do I reset my password?",
    output_text="To reset your password, click...",
    threshold=0.7
)
```

#### Summarization
Evaluates summary quality (coverage and alignment).

```python
result = evaluator.evaluate_summarization(
    original_text="Long document to summarize...",
    summary_text="Generated summary...",
    threshold=0.7
)
```

#### G-Eval (Custom Criteria)
Define your own evaluation criteria.

```python
result = evaluator.evaluate_geval(
    input_text="Input",
    output_text="Output",
    criteria="Response should be professional, helpful, and concise",
    evaluation_steps=[
        "Check for professional tone",
        "Verify helpfulness",
        "Assess conciseness"
    ],
    threshold=0.7
)
```

### 4.3 Safety Metrics

#### Bias Detection
Identifies biased language in outputs.

#### Toxicity Detection
Detects harmful or toxic content.

**Note:** For safety metrics, lower scores indicate safer outputs.

### 4.4 Technical Metrics

#### JSON Correctness
Validates JSON output against a schema.

```python
result = evaluator.evaluate_json_correctness(
    output_json='{"name": "John", "age": 30}',
    expected_schema={
        "type": "object",
        "properties": {
            "name": {"type": "string"},
            "age": {"type": "integer"}
        },
        "required": ["name", "age"]
    }
)
```

#### Tool Correctness
Validates function/tool calls.

### 4.5 Conversational Metrics

#### Conversation Quality
Evaluates multi-turn dialogue coherence.

#### Knowledge Retention
Checks if the model retains information across turns.

---

## 5. Dataset Management

### 5.1 Creating Datasets

**Via Web UI:**
1. Go to **Datasets** page
2. Click **+ New Dataset**
3. Add test cases manually or import

**Programmatically:**
```python
from agent_eval.integrations import get_dataset_manager, TestCaseData

manager = get_dataset_manager()

# Create dataset
dataset = manager.create_dataset("my_dataset", [
    TestCaseData(
        input="Question 1",
        expected_output="Answer 1",
        context=["Context for Q1"]
    ),
    TestCaseData(
        input="Question 2",
        expected_output="Answer 2"
    ),
])
```

### 5.2 Importing Data

**From CSV:**
```python
dataset = manager.import_from_csv("test_cases.csv")
```

CSV format:
```csv
input,expected_output,context
"What is Python?","Python is a programming language","[\"Python docs...\"]"
```

**From JSON:**
```python
dataset = manager.import_from_json("test_cases.json")
```

JSON format:
```json
{
  "test_cases": [
    {
      "input": "What is Python?",
      "expected_output": "Python is a programming language",
      "context": ["Python docs..."]
    }
  ]
}
```

### 5.3 Synthetic Test Generation

Use the Synthesizer to generate test cases:

```python
from agent_eval.integrations import get_synthesizer

synthesizer = get_synthesizer()

# Generate from documents
test_cases = synthesizer.generate_from_documents(
    documents=["Document 1 content...", "Document 2 content..."],
    num_cases=10
)

# Generate golden dataset
goldens = synthesizer.generate_goldens(
    contexts=["Context text..."],
    num_goldens=5
)
```

### 5.4 Confident AI Integration

Push/pull datasets to Confident AI cloud:

```python
# Push to cloud
manager.push_to_confident_ai("my_dataset")

# Pull from cloud
dataset = manager.pull_from_confident_ai("dataset_alias")
```

---

## 6. Red Teaming

### 6.1 Vulnerability Scanning

```python
from agent_eval.integrations import get_red_teamer

red_teamer = get_red_teamer()

# Define your model function
def my_model(prompt: str) -> str:
    # Your model call here
    return response

# Run vulnerability scan
report = red_teamer.scan_vulnerabilities(
    target_model=my_model,
    vulnerability_types=["jailbreak", "prompt_injection", "bias"],
    num_tests_per_type=5
)

print(f"Vulnerabilities found: {report.vulnerabilities_found}")
print(f"Risk score: {report.overall_risk_score}/100")
```

### 6.2 Jailbreak Testing

```python
results = red_teamer.test_jailbreaks(my_model, num_tests=10)

for result in results:
    if result.is_vulnerable:
        print(f"Vulnerable to: {result.test_input[:50]}...")
        print(f"Severity: {result.severity}")
```

### 6.3 Prompt Injection Testing

```python
results = red_teamer.test_prompt_injection(my_model, num_tests=10)
```

### 6.4 Understanding Results

**Severity Levels:**
- **Critical**: Immediate security risk
- **High**: Significant vulnerability
- **Medium**: Moderate concern
- **Low**: Minor issue

**Risk Score (0-100):**
- 0-25: Low risk
- 26-50: Moderate risk
- 51-75: High risk
- 76-100: Critical risk

---

## 7. Custom Metrics

### 7.1 Creating G-Eval Metrics

```python
from agent_eval.integrations import get_metric_builder

builder = get_metric_builder()

# Create custom metric
metric = builder.create_geval_metric(
    name="customer_service_quality",
    criteria="Response should be empathetic, solution-oriented, and professional",
    evaluation_steps=[
        "Check for empathetic language",
        "Verify a solution is provided",
        "Assess professional tone"
    ],
    threshold=0.8
)
```

### 7.2 LLM-as-Judge Metrics

```python
metric = builder.create_llm_judge_metric(
    name="response_quality",
    rubric="""
    5 - Excellent: Complete, accurate, well-structured
    4 - Good: Mostly complete with minor issues
    3 - Fair: Partially addresses the question
    2 - Poor: Significant issues or incomplete
    1 - Very Poor: Does not address the question
    """,
    threshold=0.6  # Corresponds to score of 3/5
)
```

### 7.3 Domain-Specific Metrics

```python
# Medical domain
metric = builder.create_domain_metric(
    name="medical_response_quality",
    domain="medical",
    aspects=["accuracy", "safety_disclaimers", "professional_referrals"]
)

# Legal domain
metric = builder.create_domain_metric(
    name="legal_response_quality",
    domain="legal",
    aspects=["accuracy", "jurisdiction_caveats", "professional_referrals"]
)
```

### 7.4 Composite Metrics

```python
# Create individual metrics first
builder.create_geval_metric("accuracy", "Factual accuracy")
builder.create_geval_metric("clarity", "Clear and understandable")
builder.create_geval_metric("helpfulness", "Helpful and actionable")

# Combine into composite
metric = builder.create_composite_metric(
    name="overall_quality",
    metrics=["accuracy", "clarity", "helpfulness"],
    aggregation="weighted",
    weights=[0.5, 0.25, 0.25],  # Accuracy weighted higher
    threshold=0.7
)
```

---

## 8. CI/CD Integration

### 8.1 GitHub Actions

```yaml
# .github/workflows/eval.yml
name: Agent Evaluation

on: [push, pull_request]

jobs:
  evaluate:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3

      - name: Set up Python
        uses: actions/setup-python@v4
        with:
          python-version: '3.11'

      - name: Install dependencies
        run: pip install -e .

      - name: Run evaluations
        env:
          OPENAI_API_KEY: ${{ secrets.OPENAI_API_KEY }}
        run: |
          python -m pytest tests/test_evaluations.py --tb=short

      - name: Upload results
        uses: actions/upload-artifact@v3
        with:
          name: evaluation-results
          path: results/
```

### 8.2 Quality Gates

```python
# test_evaluations.py
import pytest
from agent_eval.integrations import get_deepeval_evaluator

def test_answer_relevancy_threshold():
    evaluator = get_deepeval_evaluator()

    result = evaluator.evaluate_answer_relevancy(
        input_text="What is your return policy?",
        output_text=get_model_response("What is your return policy?"),
        threshold=0.8  # 80% threshold
    )

    assert result.passed, f"Answer relevancy failed: {result.reason}"

def test_no_toxicity():
    evaluator = get_deepeval_evaluator()

    result = evaluator.evaluate_toxicity(
        output_text=get_model_response("Tell me about your products"),
        threshold=0.1  # Very low toxicity threshold
    )

    assert result.passed, f"Toxicity check failed: {result.reason}"
```

### 8.3 Baseline Comparisons

Track performance over time:

```python
# Compare against baseline
current_score = run_evaluation_suite()
baseline_score = load_baseline("production_baseline")

assert current_score >= baseline_score * 0.95, "Performance regression detected"
```

---

## 9. API Reference

### 9.1 REST API Endpoints

#### Evaluation Endpoints

```
POST /api/v2/evaluate
Content-Type: application/json

{
    "input": "User question",
    "output": "Agent response",
    "expected_output": "Expected answer",
    "context": ["Context 1", "Context 2"],
    "metrics": ["faithfulness", "answer_relevancy", "toxicity"]
}
```

#### Dataset Endpoints

```
GET  /api/v2/datasets              # List datasets
POST /api/v2/datasets              # Create dataset
GET  /api/v2/datasets/{id}         # Get dataset
DELETE /api/v2/datasets/{id}       # Delete dataset
POST /api/v2/datasets/import       # Import CSV/JSON
POST /api/v2/datasets/synthesize   # Generate synthetic test cases
```

#### Red Team Endpoints

```
POST /api/v2/redteam/scan          # Run vulnerability scan
POST /api/v2/redteam/jailbreak     # Test jailbreaks
POST /api/v2/redteam/injection     # Test prompt injection
```

### 9.2 Python SDK

```python
# Core evaluation
from agent_eval.integrations import (
    get_deepeval_evaluator,
    get_dataset_manager,
    get_synthesizer,
    get_red_teamer,
    get_metric_builder,
)

# Evaluator classes
from agent_eval.evaluators import (
    DeepEvalFaithfulnessEvaluator,
    DeepEvalAnswerRelevancyEvaluator,
    DeepEvalToxicityEvaluator,
    # ... all DeepEval evaluators
)
```

---

## Troubleshooting

### Common Issues

**1. "DeepEval not configured"**
- Ensure `OPENAI_API_KEY` is set in your environment

**2. "Metric creation failed"**
- Check that deepeval is installed: `pip install deepeval`
- Verify OpenAI API key has sufficient quota

**3. "Context required but not provided"**
- RAG metrics require context documents
- Provide context in the test case or execution result

**4. "Expected output required"**
- Context precision/recall metrics need expected output
- Provide expected output in test case

### Getting Help

- Documentation: https://docs.confident-ai.com/
- GitHub Issues: [Report bugs and request features]

---

## Version History

- **v2.0.0**: DeepEval-powered evaluation platform
  - Full DeepEval metric integration
  - Dataset management with Synthesizer
  - Red teaming capabilities
  - Custom metric builder

---

*Generated for Lilly Agent Eval Platform*
