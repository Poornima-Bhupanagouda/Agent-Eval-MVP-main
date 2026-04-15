"""
RAGAS Evaluator — RAG Assessment metrics for Lilly Agent Eval.

RAGAS provides specialized RAG pipeline evaluation metrics:
  - Faithfulness:             Is every claim in the answer grounded in context?
  - Context Precision:        Are retrieved chunks ranked by relevance?
  - Context Recall:           Does the context cover all parts of the expected answer?
  - Context Entity Recall:    Do key entities from ground truth appear in context?
  - Answer Correctness:       Is the answer factually correct vs expected?
  - Answer Similarity:        Semantic similarity between answer and ground truth?

Note: answer_relevancy is NOT included here — DeepEval already handles
that metric for ALL agent types. RAGAS focuses on RAG-specific metrics
that DeepEval doesn't cover.

Usage:
    evaluator = RagasEvaluator()
    results = evaluator.evaluate(
        question="What is our leave policy?",
        answer="Employees get 15 days paid leave",
        contexts=["Leave policy: 15 days paid leave per year"],
        ground_truth="15 days paid leave per year",
    )

Configuration:
    Set RAGAS_ENABLED=true in .env to activate.
    Requires: pip install ragas
    Uses the same LLM as DeepEval (DEPLOYMENT_MODEL / LLM_GATEWAY_BASE_URL).
"""

import os
import logging
from typing import Optional, List, Dict, Any
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class RagasResult:
    """Result from a single RAGAS metric."""
    metric: str
    score: float       # 0-100
    passed: bool
    reason: str
    scored_by: str = "ragas"


def is_ragas_enabled() -> bool:
    """Check if RAGAS evaluation is enabled and importable."""
    if os.getenv("RAGAS_ENABLED", "false").lower() != "true":
        return False
    try:
        import ragas
        return True
    except ImportError:
        logger.debug("RAGAS not installed (pip install ragas)")
        return False


class RagasEvaluator:
    """
    Evaluator using RAGAS framework for RAG-specific metrics.

    RAGAS uses LLM-as-judge to evaluate RAG pipeline quality.
    Each metric score is 0.0-1.0, converted to 0-100 for consistency.
    """

    # RAGAS metrics — RAG-specific only (no overlap with DeepEval)
    AVAILABLE_METRICS = {
        "ragas_faithfulness": "Is every claim in the answer supported by the context?",
        "ragas_context_precision": "Are the most relevant context chunks ranked highest?",
        "ragas_context_recall": "Does the context cover all parts of the expected answer?",
        "ragas_context_entity_recall": "Do key entities from the ground truth appear in retrieved context?",
        "ragas_answer_correctness": "Is the answer factually correct compared to ground truth?",
        "ragas_answer_similarity": "Semantic similarity between the answer and ground truth?",
    }

    def __init__(self, threshold: float = 70.0):
        self.threshold = threshold
        self._available = is_ragas_enabled()

    def evaluate(
        self,
        question: str,
        answer: str,
        contexts: Optional[List[str]] = None,
        ground_truth: Optional[str] = None,
        metrics: Optional[List[str]] = None,
        threshold: Optional[float] = None,
    ) -> List[RagasResult]:
        """
        Run RAGAS evaluation on a single Q&A pair.

        Args:
            question:     The user's question
            answer:       The agent's response
            contexts:     Retrieved context chunks (required for context metrics)
            ground_truth: Expected correct answer (required for correctness/recall)
            metrics:      Specific RAGAS metrics to run (None = auto-select)
            threshold:    Pass threshold 0-100

        Returns:
            List of RagasResult for each metric
        """
        if not self._available:
            return []

        threshold = threshold or self.threshold

        # Auto-select metrics based on available data
        if metrics is None:
            metrics = self._auto_select(contexts, ground_truth)

        if not metrics:
            return []

        try:
            return self._run_ragas(question, answer, contexts, ground_truth, metrics, threshold)
        except Exception as e:
            logger.error(f"RAGAS evaluation failed: {e}")
            return []

    def _auto_select(
        self,
        contexts: Optional[List[str]],
        ground_truth: Optional[str],
    ) -> List[str]:
        """Select RAGAS metrics based on available data."""
        selected = []

        if contexts:
            selected.append("ragas_faithfulness")
            selected.append("ragas_context_precision")

        if contexts and ground_truth:
            selected.append("ragas_context_recall")
            selected.append("ragas_context_entity_recall")

        if ground_truth:
            selected.append("ragas_answer_correctness")
            selected.append("ragas_answer_similarity")

        return selected

    def _run_ragas(
        self,
        question: str,
        answer: str,
        contexts: Optional[List[str]],
        ground_truth: Optional[str],
        metrics: List[str],
        threshold: float,
    ) -> List[RagasResult]:
        """Execute RAGAS evaluation — runs each metric individually so one failure doesn't crash all.

        Updated for RAGAS v0.4+ API:
          - Uses SingleTurnSample + EvaluationDataset (not datasets.Dataset)
          - Uses metric classes like Faithfulness() (not lowercase instances)
          - Uses user_input/response/retrieved_contexts/reference field names
        """
        import math
        from ragas import evaluate as ragas_evaluate
        from ragas import SingleTurnSample, EvaluationDataset
        from ragas.metrics.collections import (
            Faithfulness,
            ContextPrecision,
            ContextRecall,
            ContextEntityRecall,
            AnswerCorrectness,
            SemanticSimilarity,
        )

        # Map our metric names to RAGAS v0.4 metric classes and score keys
        metric_map = {
            "ragas_faithfulness": (Faithfulness(), "faithfulness"),
            "ragas_context_precision": (ContextPrecision(), "context_precision"),
            "ragas_context_recall": (ContextRecall(), "context_recall"),
            "ragas_context_entity_recall": (ContextEntityRecall(), "context_entity_recall"),
            "ragas_answer_correctness": (AnswerCorrectness(), "answer_correctness"),
            "ragas_answer_similarity": (SemanticSimilarity(), "semantic_similarity"),
        }

        # Build RAGAS SingleTurnSample (v0.4 API)
        sample_kwargs = {
            "user_input": question,
            "response": answer,
            "retrieved_contexts": contexts or [],
        }
        if ground_truth:
            sample_kwargs["reference"] = ground_truth
            # reference_contexts needed for some metrics (context_recall, entity_recall)
            if contexts:
                sample_kwargs["reference_contexts"] = contexts

        sample = SingleTurnSample(**sample_kwargs)
        dataset = EvaluationDataset(samples=[sample])

        # Configure LLM + embeddings (use same gateway as DeepEval)
        llm_config = self._get_llm_config()

        # Run each metric individually so one failure doesn't crash the batch
        results = []
        for metric_name in metrics:
            if metric_name not in metric_map:
                continue
            ragas_metric, ragas_key = metric_map[metric_name]
            try:
                eval_result = ragas_evaluate(
                    dataset=dataset,
                    metrics=[ragas_metric],
                    **llm_config,
                )
                score_dict = eval_result.to_pandas().iloc[0].to_dict()
                raw_score = score_dict.get(ragas_key, 0.0)

                # Guard against NaN (happens when RAGAS LLM call fails)
                if raw_score is None or (isinstance(raw_score, float) and math.isnan(raw_score)):
                    raw_score = 0.0

                # RAGAS scores are 0.0-1.0, convert to 0-100
                score = round(raw_score * 100, 1)
                passed = score >= threshold

                results.append(RagasResult(
                    metric=metric_name,
                    score=score,
                    passed=passed,
                    reason=f"RAGAS {ragas_key}: {score:.1f}%",
                    scored_by="ragas",
                ))
            except Exception as e:
                logger.warning(f"RAGAS metric {metric_name} failed: {e}")
                # Skip this metric — evaluator will use heuristic fallback for it

        return results

    def _get_llm_config(self) -> Dict[str, Any]:
        """Build LLM + embeddings configuration for RAGAS from environment variables.

        Supports OAuth2 authentication (same as DeepEval) for LLM gateways
        that require Bearer tokens (e.g., Azure AD protected endpoints).
        Configures BOTH the LLM and the embeddings model so that metrics like
        answer_similarity (which need embeddings) also get the auth headers.
        """
        config = {}

        base_url = os.getenv("LLM_GATEWAY_BASE_URL") or os.getenv("OPENAI_API_BASE")
        api_key = os.getenv("LLM_GATEWAY_KEY") or os.getenv("OPENAI_API_KEY")
        model = os.getenv("DEEPEVAL_JUDGE_MODEL") or os.getenv("DEPLOYMENT_MODEL", "gpt-4o-mini")
        embedding_model = os.getenv("EMBEDDING_MODEL", "text-embedding-3-large")

        if base_url and api_key:
            try:
                from langchain_openai import ChatOpenAI, OpenAIEmbeddings
                from ragas.llms import LangchainLLMWrapper
                from ragas.embeddings import LangchainEmbeddingsWrapper

                # Build extra headers (OAuth2 Bearer token if configured)
                extra_headers = {}
                token = self._get_oauth2_token()
                if token:
                    extra_headers["Authorization"] = f"Bearer {token}"
                    extra_headers["X-LLM-Gateway-Key"] = api_key

                # --- LLM ---
                llm_kwargs = {
                    "model": model,
                    "openai_api_key": api_key,
                    "openai_api_base": base_url,
                    "temperature": 0,
                }
                if extra_headers:
                    llm_kwargs["default_headers"] = extra_headers

                llm = ChatOpenAI(**llm_kwargs)
                config["llm"] = LangchainLLMWrapper(llm)

                # --- Embeddings (needed for answer_similarity) ---
                emb_kwargs = {
                    "model": embedding_model,
                    "openai_api_key": api_key,
                    "openai_api_base": base_url,
                }
                if extra_headers:
                    emb_kwargs["default_headers"] = extra_headers

                embeddings = OpenAIEmbeddings(**emb_kwargs)
                config["embeddings"] = LangchainEmbeddingsWrapper(embeddings)
            except ImportError:
                logger.debug("langchain_openai not installed, RAGAS will use defaults")

        return config

    @staticmethod
    def _get_oauth2_token() -> Optional[str]:
        """Get OAuth2 token for LLM gateway (reuses evaluator's cached token if available)."""
        try:
            from agent_eval.core.evaluator import Evaluator
            return Evaluator._get_oauth2_token()
        except Exception:
            return None
