import os

# Check 1: Are packages installed?
try:
    import ragas
    print(f"RAGAS installed: True (v{ragas.__version__})")
except ImportError as e:
    print(f"RAGAS installed: False ({e})")

try:
    import trulens
    print(f"TruLens installed: True (v{trulens.__version__})")
except ImportError as e:
    try:
        import trulens_eval
        print("TruLens (v0) installed: True")
    except ImportError as e2:
        print(f"TruLens installed: False ({e2})")

# Check 2: Are enabled functions working?
try:
    from agent_eval.core.ragas_evaluator import is_ragas_enabled
    print(f"is_ragas_enabled(): {is_ragas_enabled()}")
except Exception as e:
    print(f"is_ragas_enabled error: {e}")

try:
    from agent_eval.core.trulens_evaluator import is_trulens_enabled
    print(f"is_trulens_enabled(): {is_trulens_enabled()}")
except Exception as e:
    print(f"is_trulens_enabled error: {e}")

# Check 3: Env vars
print(f"RAGAS_ENABLED={os.getenv('RAGAS_ENABLED')}")
print(f"TRULENS_ENABLED={os.getenv('TRULENS_ENABLED')}")
print(f"LLM_GATEWAY_BASE_URL={'set' if os.getenv('LLM_GATEWAY_BASE_URL') else 'not set'}")
print(f"LLM_GATEWAY_KEY={'set' if os.getenv('LLM_GATEWAY_KEY') else 'not set'}")

# Check 4: Try a real RAGAS evaluation
print("\n--- Testing RAGAS evaluation ---")
try:
    from agent_eval.core.ragas_evaluator import RagasEvaluator
    evaluator = RagasEvaluator(threshold=70)
    results = evaluator.evaluate(
        question="What is the sick leave policy?",
        answer="Employees receive 10 sick days per year.",
        contexts=["All employees get 10 sick days per year, separate from PTO."],
        ground_truth="10 sick days per year",
        metrics=["ragas_faithfulness"],
        threshold=70,
    )
    for r in results:
        print(f"  {r.metric}: score={r.score}, scored_by={r.scored_by}")
except Exception as e:
    print(f"  RAGAS evaluation FAILED: {type(e).__name__}: {e}")

# Check 5: Try a real TruLens evaluation
print("\n--- Testing TruLens evaluation ---")
try:
    from agent_eval.core.trulens_evaluator import TruLensEvaluator
    evaluator = TruLensEvaluator(threshold=70)
    results = evaluator.evaluate(
        question="What is the sick leave policy?",
        answer="Employees receive 10 sick days per year.",
        contexts=["All employees get 10 sick days per year."],
        metrics=["trulens_coherence"],
        threshold=70,
    )
    for r in results:
        print(f"  {r.metric}: score={r.score}, scored_by={r.scored_by}")
except Exception as e:
    print(f"  TruLens evaluation FAILED: {type(e).__name__}: {e}")
