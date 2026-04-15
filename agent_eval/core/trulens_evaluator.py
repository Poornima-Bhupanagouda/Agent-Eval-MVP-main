"""
TruLens Evaluator — LLM app feedback functions for Lilly Agent Eval.

TruLens provides feedback functions that judge LLM output quality:
  - Groundedness:      Is the response grounded in the provided context?
  - Coherence:         Is the response logically coherent and well-structured?
  - Harmfulness:       Does the response contain harmful content?
  - Conciseness:       Is the response concise without unnecessary verbosity?
  - Correctness:       Is the answer factually correct?
  - Maliciousness:     Does the response have malicious intent?
  - Helpfulness:       Is the response actually helpful to the user?

Note: answer_relevance is NOT included — DeepEval already handles that.
Note: context_relevance is NOT included — RAGAS handles that for RAG agents.
TruLens focuses on general quality metrics that apply to ALL agent types,
especially non-RAG agents (conversational, tool-using, simple).

Usage:
    evaluator = TruLensEvaluator()
    results = evaluator.evaluate(
        question="What is our leave policy?",
        answer="Employees get 15 days paid leave",
        contexts=["Leave policy: 15 days paid leave per year"],
    )

Configuration:
    Set TRULENS_ENABLED=true in .env to activate.
    Requires: pip install trulens-eval
    Uses the same LLM as DeepEval (DEPLOYMENT_MODEL / LLM_GATEWAY_BASE_URL).
"""

import os
import logging
from typing import Optional, List, Dict, Any
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class TruLensResult:
    """Result from a single TruLens feedback function."""
    metric: str
    score: float       # 0-100
    passed: bool
    reason: str
    scored_by: str = "trulens"


def is_trulens_enabled() -> bool:
    """Check if TruLens evaluation is enabled and importable."""
    if os.getenv("TRULENS_ENABLED", "false").lower() != "true":
        return False
    try:
        from trulens.feedback import Feedback
        return True
    except ImportError:
        try:
            from trulens_eval.feedback import Feedback
            return True
        except ImportError:
            logger.debug("TruLens not installed (pip install trulens-eval)")
            return False


class TruLensEvaluator:
    """
    Evaluator using TruLens feedback functions.

    TruLens uses LLM-powered feedback to score response quality.
    Each feedback score is 0.0-1.0, converted to 0-100 for consistency.
    """

    AVAILABLE_METRICS = {
        "trulens_groundedness": "Is every statement in the answer supported by the context?",
        "trulens_coherence": "Is the response logically structured and coherent?",
        "trulens_harmfulness": "Does the response contain harmful content?",
        "trulens_conciseness": "Is the response concise without unnecessary verbosity?",
        "trulens_correctness": "Is the answer factually correct?",
        "trulens_maliciousness": "Does the response contain malicious intent?",
        "trulens_helpfulness": "Is the response helpful and actionable for the user?",
    }

    def __init__(self, threshold: float = 70.0):
        self.threshold = threshold
        self._available = is_trulens_enabled()
        self._provider = None
        self._last_token = None

    def evaluate(
        self,
        question: str,
        answer: str,
        contexts: Optional[List[str]] = None,
        metrics: Optional[List[str]] = None,
        threshold: Optional[float] = None,
    ) -> List[TruLensResult]:
        """
        Run TruLens feedback evaluation on a single Q&A pair.

        Args:
            question:  The user's question
            answer:    The agent's response
            contexts:  Retrieved context chunks
            metrics:   Specific TruLens metrics to run (None = auto-select)
            threshold: Pass threshold 0-100

        Returns:
            List of TruLensResult for each metric
        """
        if not self._available:
            return []

        threshold = threshold or self.threshold

        if metrics is None:
            metrics = self._auto_select(contexts)

        if not metrics:
            return []

        try:
            return self._run_trulens(question, answer, contexts, metrics, threshold)
        except Exception as e:
            logger.error(f"TruLens evaluation failed: {e}")
            return []

    def _auto_select(self, contexts: Optional[List[str]]) -> List[str]:
        """Select TruLens metrics based on available data."""
        # General quality metrics — always run
        selected = [
            "trulens_coherence",
            "trulens_harmfulness",
            "trulens_conciseness",
            "trulens_correctness",
            "trulens_helpfulness",
        ]

        # Context-dependent metrics
        if contexts:
            selected.insert(0, "trulens_groundedness")

        return selected

    def _get_provider(self):
        """Get or create the TruLens LLM provider with OAuth2 support.

        Refreshes the provider when the OAuth2 token has been rotated so
        that the underlying OpenAI client always carries a valid bearer
        token.
        """
        base_url = os.getenv("LLM_GATEWAY_BASE_URL") or os.getenv("OPENAI_API_BASE")
        api_key = os.getenv("LLM_GATEWAY_KEY") or os.getenv("OPENAI_API_KEY")
        model = os.getenv("DEEPEVAL_JUDGE_MODEL") or os.getenv("DEPLOYMENT_MODEL", "gpt-4o-mini")

        # Get OAuth2 token for gateways that require it
        extra_headers = {}
        current_token = None
        try:
            from agent_eval.core.evaluator import Evaluator
            current_token = Evaluator._get_oauth2_token()
            if current_token:
                extra_headers["Authorization"] = f"Bearer {current_token}"
                extra_headers["X-LLM-Gateway-Key"] = api_key
        except Exception:
            pass

        # Return cached provider if token hasn't changed
        if self._provider and current_token == self._last_token:
            return self._provider

        try:
            from trulens.providers.openai import OpenAI as TruLensOpenAI
            kwargs = {"model_engine": model, "timeout": 30}
            if base_url and api_key:
                kwargs["api_key"] = api_key
                kwargs["base_url"] = base_url
            if extra_headers:
                kwargs["default_headers"] = extra_headers
            self._provider = TruLensOpenAI(**kwargs)
            self._last_token = current_token
            # Pre-set capabilities to skip costly probing calls.
            # LLM gateways only support Chat Completions — disable Responses API,
            # structured outputs, and CFG so TruLens doesn't waste LLM calls probing.
            self._provider._set_capabilities({
                "structured_outputs": False,
                "cfg": False,
                "temperature": True,
                "reasoning_effort": False,
            })
            # Reduce retries from default 3 to 1 to avoid long delays on failure
            if hasattr(self._provider, 'endpoint') and hasattr(self._provider.endpoint, 'retries'):
                self._provider.endpoint.retries = 1
        except (ImportError, TypeError):
            try:
                from trulens_eval.feedback.provider import OpenAI as TruLensOpenAI
                kwargs = {"model_engine": model, "timeout": 30}
                if base_url and api_key:
                    kwargs["api_key"] = api_key
                    kwargs["base_url"] = base_url
                self._provider = TruLensOpenAI(**kwargs)
                self._last_token = current_token
            except ImportError:
                logger.error("Cannot create TruLens provider")
                return None

        return self._provider

    def _run_trulens(
        self,
        question: str,
        answer: str,
        contexts: Optional[List[str]],
        metrics: List[str],
        threshold: float,
    ) -> List[TruLensResult]:
        """Execute TruLens feedback functions."""
        provider = self._get_provider()
        if not provider:
            return []

        results = []

        for metric_name in metrics:
            try:
                score = self._run_single_feedback(
                    provider, metric_name, question, answer, contexts,
                )
                if score is None:
                    logger.warning(f"TruLens {metric_name} returned None")
                    continue
                # TruLens scores are 0.0-1.0, convert to 0-100
                score_pct = round(float(score) * 100, 1)
                passed = score_pct >= threshold

                results.append(TruLensResult(
                    metric=metric_name,
                    score=score_pct,
                    passed=passed,
                    reason=f"TruLens {metric_name.replace('trulens_', '')}: {score_pct:.1f}%",
                ))
            except Exception as e:
                logger.warning(f"TruLens {metric_name} failed: {e}")

        return results

    def _run_single_feedback(
        self,
        provider,
        metric_name: str,
        question: str,
        answer: str,
        contexts: Optional[List[str]],
    ) -> float:
        """Run a single TruLens feedback function. Returns 0.0-1.0."""

        if metric_name == "trulens_groundedness":
            if not contexts:
                return 0.0
            combined_context = "\n\n".join(contexts)
            return provider.groundedness_measure_with_cot_reasons(
                source=combined_context,
                statement=answer,
            )

        elif metric_name == "trulens_coherence":
            return provider.coherence(
                text=answer,
            )

        elif metric_name == "trulens_harmfulness":
            raw = provider.harmfulness(
                text=answer,
            )
            # Invert: TruLens returns high = harmful, we want high = safe
            return 1.0 - raw

        elif metric_name == "trulens_conciseness":
            return provider.conciseness(
                text=answer,
            )

        elif metric_name == "trulens_correctness":
            return provider.correctness(
                text=answer,
            )

        elif metric_name == "trulens_maliciousness":
            raw = provider.maliciousness(
                text=answer,
            )
            # Invert: high = malicious, we want high = safe
            return 1.0 - raw

        elif metric_name == "trulens_helpfulness":
            return provider.helpfulness(
                text=answer,
            )

        else:
            logger.warning(f"Unknown TruLens metric: {metric_name}")
            return 0.0
