"""Debug Contextual Relevancy scoring step by step."""
import os
from dotenv import load_dotenv
load_dotenv()

from deepeval.test_case import LLMTestCase
from deepeval.metrics import ContextualRelevancyMetric

# Mimic the evaluator's GPTModel setup
from deepeval.models import GPTModel
import requests

# Get OAuth2 token
token_url = os.getenv("OAUTH_TOKEN_URL")
tok_resp = requests.post(token_url, data={
    "grant_type": "client_credentials",
    "client_id": os.getenv("OAUTH_CLIENT_ID"),
    "client_secret": os.getenv("OAUTH_CLIENT_SECRET"),
    "scope": os.getenv("OAUTH_SCOPE"),
}, timeout=10)
tok_resp.raise_for_status()
token = tok_resp.json()["access_token"]

gateway_key = os.getenv("LLM_GATEWAY_KEY")
gateway_url = os.getenv("LLM_GATEWAY_BASE_URL")

model = GPTModel(
    model=os.getenv("DEPLOYMENT_MODEL"),
    api_key=gateway_key,
    base_url=gateway_url,
    default_headers={
        "Authorization": f"Bearer {token}",
        "X-LLM-Gateway-Key": gateway_key,
    },
)

# Simulate the exact test case from the user's RAG eval
question = "What are the priority sectors under NITI Aayog's AI for All strategy?"
agent_output = "Healthcare\nAgriculture\nEducation\nSmart Cities and Infrastructure\nSmart Mobility and Transportation"
context = [
    "NITI AYOG mainly focused on 5 major areas: Healthcare, Agriculture, Education, Smart Cities and Infrastructure and Smart Mobility and Transportation."
]

print("=" * 60)
print("DEBUG: Contextual Relevancy")
print("=" * 60)
print(f"\nQuestion: {question}")
print(f"\nAgent Output: {agent_output}")
print(f"\nContext: {context}")
print(f"\nretrieval_context type: {type(context)}")
print(f"retrieval_context length: {len(context)}")
print(f"retrieval_context[0] length: {len(context[0])} chars, {len(context[0].split())} words")

# Build test case
test_case = LLMTestCase(
    input=question,
    actual_output=agent_output,
    retrieval_context=context,
)

print(f"\ntest_case.retrieval_context: {test_case.retrieval_context}")

# Run metric with verbose
metric = ContextualRelevancyMetric(
    threshold=0.5,
    model=model,
    verbose_mode=True,
)

print("\n--- Running metric.measure() ---")
metric.measure(test_case)

print(f"\n--- RESULTS ---")
print(f"Score: {metric.score}")
print(f"Reason: {metric.reason}")
print(f"Success: {metric.success}")
print(f"Verdicts list: {metric.verdicts_list}")
for i, verdicts in enumerate(metric.verdicts_list):
    print(f"\n  Context chunk {i}:")
    for v in verdicts.verdicts:
        print(f"    Statement: {v.statement}")
        print(f"    Verdict: {v.verdict}")
        if v.reason:
            print(f"    Reason: {v.reason}")
