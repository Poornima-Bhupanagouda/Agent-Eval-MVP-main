"""
Evaluator for Lilly Agent Eval.

Simple evaluator powered by DeepEval with smart metric selection.
"""

import os
import time
import asyncio
import logging
import threading
from dataclasses import dataclass
from typing import Optional, List, Any
from concurrent.futures import ThreadPoolExecutor, as_completed

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

logger = logging.getLogger(__name__)


@dataclass
class EvalResult:
    """Result of a single evaluation metric."""
    metric: str
    score: float  # 0-100
    passed: bool
    reason: str
    details: Optional[dict] = None
    scored_by: str = "heuristic"  # "deepeval" or "heuristic"


class Evaluator:
    """
    Simple evaluator powered by DeepEval.

    Features:
    - Smart metric auto-selection based on available data
    - Threshold-based pass/fail
    - Graceful fallback when DeepEval unavailable
    - Cached OAuth2 token and GPTModel for performance
    - Parallel metric execution within a single evaluate() call
    """

    # Metrics that require LLM intelligence (meaning understanding).
    # Everything else is evaluated via fast heuristic keyword matching.
    DEEPEVAL_ONLY_METRICS = {
        "answer_relevancy", "toxicity", "bias",
        "faithfulness", "hallucination", "contextual_relevancy",
    }

    # Shared thread pool for ALL LLM-based evaluations (DeepEval + RAGAS + TruLens).
    # 15 workers allows DeepEval, RAGAS, and TruLens metrics to ALL run in parallel.
    _thread_pool = ThreadPoolExecutor(max_workers=15)

    # Lock for thread-safe GPTModel/OAuth2 token access
    _model_lock = threading.Lock()

    # Cached OAuth2 token and GPTModel (class-level, shared across instances)
    _cached_token: Optional[str] = None
    _cached_token_expiry: float = 0  # epoch seconds
    _cached_gpt_model: Any = None
    _cached_gpt_model_name: Optional[str] = None

    # Available metrics
    METRICS = {
        "answer_relevancy": {
            "name": "Answer Relevancy",
            "description": "Does the answer address the question?",
            "requires": None,
        },
        "toxicity": {
            "name": "Toxicity",
            "description": "Is the response safe and appropriate?",
            "requires": None,
        },
        "bias": {
            "name": "Bias",
            "description": "Does the response show unfair bias?",
            "requires": None,
        },
        "faithfulness": {
            "name": "Faithfulness",
            "description": "Is the answer grounded in the provided context?",
            "requires": "context",
        },
        "hallucination": {
            "name": "Hallucination",
            "description": "Does the response contain made-up facts?",
            "requires": "context",
        },
        "contextual_relevancy": {
            "name": "Contextual Relevancy",
            "description": "Is the context relevant to the question?",
            "requires": "context",
        },
        "similarity": {
            "name": "Semantic Similarity",
            "description": "How similar is the output to the expected answer?",
            "requires": "expected",
        },
        "precision_at_k": {
            "name": "Precision@K",
            "description": "What fraction of retrieved context chunks are relevant?",
            "requires": "context",
        },
        "recall_at_k": {
            "name": "Recall@K",
            "description": "What fraction of relevant info was retrieved?",
            "requires": "context",
        },
        "mrr": {
            "name": "Mean Reciprocal Rank",
            "description": "How early does the first relevant context chunk appear?",
            "requires": "context",
        },
        # Agentic evaluation metrics
        "coherence": {
            "name": "Coherence",
            "description": "Does the response maintain consistency across conversation turns?",
            "requires": "conversation_history",
        },
        "context_retention": {
            "name": "Context Retention",
            "description": "Does the agent remember information from earlier turns?",
            "requires": "conversation_history",
        },
        "tool_correctness": {
            "name": "Tool Correctness",
            "description": "Did the agent call the expected tools?",
            "requires": "expected_tools",
        },
        "tool_args_accuracy": {
            "name": "Tool Args Accuracy",
            "description": "Were the tool call arguments correct?",
            "requires": "expected_tools",
        },
        "tool_sequence": {
            "name": "Tool Sequence",
            "description": "Were tools called in the correct order?",
            "requires": "expected_tools",
        },
        "task_completion": {
            "name": "Task Completion",
            "description": "Did the agent actually complete the requested task?",
            "requires": None,
        },
        "trajectory_score": {
            "name": "Trajectory Score",
            "description": "Does the agent's tool-call sequence match the expected trajectory?",
            "requires": "trajectory",
        },
        "rubric_score": {
            "name": "Rubric Score",
            "description": "How well does the response satisfy custom criteria?",
            "requires": "rubrics",
        },
        # Agentic trace-based metrics (inspect HOW the agent works, not just WHAT it outputs)
        "node_success_rate": {
            "name": "Node Success Rate",
            "description": "Did all pipeline nodes complete without errors?",
            "requires": "trace",
        },
        "step_latency": {
            "name": "Step Latency",
            "description": "Was each processing step within acceptable latency?",
            "requires": "trace",
        },
        "agent_reasoning": {
            "name": "Agent Reasoning",
            "description": "Did the agent follow a logical decision-making process?",
            "requires": "trace",
        },
        # ── Process-level metrics (enabled by LangSmith tracing) ──
        "tool_usage_correctness": {
            "name": "Tool Usage Correctness",
            "description": "Did the agent invoke the right tools for the task?",
            "requires": "trace",
        },
        "tool_order_correctness": {
            "name": "Tool Order Correctness",
            "description": "Were tools invoked in the correct logical order?",
            "requires": "trace",
        },
        "failure_recovery": {
            "name": "Failure Recovery",
            "description": "Did the agent recover gracefully from errors in any step?",
            "requires": "trace",
        },
        "step_count_limit": {
            "name": "Step Count Limit",
            "description": "Did the agent complete within a reasonable number of steps?",
            "requires": "trace",
        },
        "memory_retention": {
            "name": "Memory Retention",
            "description": "Did the agent remember constraints and facts from earlier turns?",
            "requires": "conversation_history",
        },
        # ── RAGAS metrics (RAG-specific, no overlap with DeepEval) ──
        "ragas_faithfulness": {
            "name": "RAGAS Faithfulness",
            "description": "Is every claim in the answer supported by the context? (RAGAS)",
            "requires": "context",
        },
        "ragas_context_precision": {
            "name": "RAGAS Context Precision",
            "description": "Are the most relevant context chunks ranked highest? (RAGAS)",
            "requires": "context",
        },
        "ragas_context_recall": {
            "name": "RAGAS Context Recall",
            "description": "Does the context cover all parts of the expected answer? (RAGAS)",
            "requires": "context",
        },
        "ragas_context_entity_recall": {
            "name": "RAGAS Context Entity Recall",
            "description": "Do key entities from ground truth appear in the retrieved context? (RAGAS)",
            "requires": "context",
        },
        "ragas_answer_correctness": {
            "name": "RAGAS Answer Correctness",
            "description": "Is the answer factually correct compared to ground truth? (RAGAS)",
            "requires": "expected",
        },
        "ragas_answer_similarity": {
            "name": "RAGAS Answer Similarity",
            "description": "Semantic similarity between the answer and the expected ground truth? (RAGAS)",
            "requires": "expected",
        },
        # ── TruLens metrics (general quality, no overlap with DeepEval/RAGAS) ──
        "trulens_groundedness": {
            "name": "TruLens Groundedness",
            "description": "Is every statement supported by the context? (chain-of-thought) (TruLens)",
            "requires": "context",
        },
        "trulens_coherence": {
            "name": "TruLens Coherence",
            "description": "Is the response logically structured? (LLM-powered) (TruLens)",
            "requires": None,
        },
        "trulens_harmfulness": {
            "name": "TruLens Harmfulness",
            "description": "Is the response free from harmful content? (TruLens)",
            "requires": None,
        },
        "trulens_conciseness": {
            "name": "TruLens Conciseness",
            "description": "Is the response concise without unnecessary verbosity? (TruLens)",
            "requires": None,
        },
        "trulens_correctness": {
            "name": "TruLens Correctness",
            "description": "Is the answer factually correct? (TruLens)",
            "requires": None,
        },
        "trulens_maliciousness": {
            "name": "TruLens Maliciousness",
            "description": "Is the response free from malicious intent? (TruLens)",
            "requires": None,
        },
        "trulens_helpfulness": {
            "name": "TruLens Helpfulness",
            "description": "Is the response helpful and actionable for the user? (TruLens)",
            "requires": None,
        },
    }

    def __init__(
        self,
        model: str = "gpt-4o-mini",
        threshold: float = 70.0,
    ):
        """
        Initialize evaluator.

        Args:
            model: LLM model to use for evaluations
            threshold: Default pass threshold (0-100)
        """
        # Use DEEPEVAL_JUDGE_MODEL for scoring (separate from agent model to avoid bias)
        # Falls back to DEPLOYMENT_MODEL, then to parameter
        self.model = os.getenv("DEEPEVAL_JUDGE_MODEL") or os.getenv("DEPLOYMENT_MODEL", model)
        self.threshold = threshold
        self._deepeval_available = self._check_deepeval()

    def _check_deepeval(self) -> bool:
        """Check if DeepEval is available."""
        try:
            import deepeval
            return True
        except ImportError:
            logger.warning("DeepEval not installed. Using heuristic evaluations.")
            return False

    def evaluate(
        self,
        input_text: str,
        output: str,
        expected: Optional[str] = None,
        context: Optional[List[str]] = None,
        metrics: Optional[List[str]] = None,
        threshold: Optional[float] = None,
        tool_calls: Optional[List[dict]] = None,
        expected_tool_calls: Optional[List[dict]] = None,
        conversation_history: Optional[List[dict]] = None,
        trajectory_spec: Optional[dict] = None,
        rubrics: Optional[List[str]] = None,
        agent_type: Optional[str] = None,
        trace: Optional[List[dict]] = None,
        expected_behavior: Optional[dict] = None,
    ) -> List[EvalResult]:
        """
        Run evaluation with smart metric selection.
        DeepEval metrics and heuristic metrics run in PARALLEL for speed.
        """
        if metrics is None:
            metrics = self._auto_select_metrics(expected, context, expected_tool_calls, conversation_history, trajectory_spec, rubrics, agent_type=agent_type, trace=trace, tool_calls=tool_calls, expected_behavior=expected_behavior)

        # RAG agents: always exclude step_latency (generate node naturally dominates)
        if agent_type == "rag" and "step_latency" in metrics:
            metrics = [m for m in metrics if m != "step_latency"]

        threshold = threshold or self.threshold

        # Separate metrics into runnable lists after requirement checks
        deepeval_jobs = []
        heuristic_jobs = []
        ragas_jobs = []
        trulens_jobs = []

        for metric_id in metrics:
            if metric_id not in self.METRICS:
                logger.warning(f"Unknown metric: {metric_id}")
                continue

            metric_info = self.METRICS[metric_id]
            if metric_info["requires"] == "context" and not context:
                continue
            if metric_info["requires"] == "expected" and not expected:
                continue
            if metric_info["requires"] == "expected_tools" and not expected_tool_calls:
                continue
            if metric_info["requires"] == "conversation_history" and not conversation_history:
                continue
            if metric_info["requires"] == "trajectory" and not (trajectory_spec or expected_tool_calls):
                continue
            if metric_info["requires"] == "rubrics" and not rubrics:
                continue
            if metric_info["requires"] == "trace" and not trace:
                continue

            if self._deepeval_available and metric_id in self.DEEPEVAL_ONLY_METRICS:
                deepeval_jobs.append(metric_id)
            elif metric_id.startswith("ragas_"):
                ragas_jobs.append(metric_id)
            elif metric_id.startswith("trulens_"):
                trulens_jobs.append(metric_id)
            else:
                heuristic_jobs.append(metric_id)

        # --- Run heuristic metrics instantly (fast, no LLM) ---
        # OTel: import span helper (no-op if OTel not enabled)
        try:
            from agent_eval.core.otel_tracing import otel_span, record_span_event
        except ImportError:
            otel_span = None
            record_span_event = None

        results = []
        for metric_id in heuristic_jobs:
            if otel_span:
                with otel_span(f"metric.{metric_id}", {"metric.type": "heuristic"}) as span:
                    result = self._run_heuristic_metric(
                        metric_id, input_text, output, expected, context, threshold,
                        tool_calls=tool_calls,
                        expected_tool_calls=expected_tool_calls,
                        conversation_history=conversation_history,
                        trajectory_spec=trajectory_spec,
                        rubrics=rubrics,
                        trace=trace,
                        expected_behavior=expected_behavior,
                    )
                    span.set_attribute("metric.score", result.score)
                    span.set_attribute("metric.passed", result.passed)
                    results.append(result)
            else:
                results.append(self._run_heuristic_metric(
                    metric_id, input_text, output, expected, context, threshold,
                    tool_calls=tool_calls,
                    expected_tool_calls=expected_tool_calls,
                    conversation_history=conversation_history,
                    trajectory_spec=trajectory_spec,
                    rubrics=rubrics,
                    trace=trace,
                    expected_behavior=expected_behavior,
                ))

        # --- Run DeepEval, RAGAS, and TruLens ALL IN PARALLEL ---
        # Instead of running these sequentially (DeepEval → RAGAS → TruLens),
        # submit all LLM-based jobs to the shared thread pool simultaneously.
        # This cuts total wall-clock time from ~sum to ~max of the three.

        if deepeval_jobs:
            # Pre-warm: ensure GPTModel + OAuth2 token are cached before
            # spawning threads (avoids all threads racing to create it).
            self._get_cached_gpt_model(self.model)

        futures = {}

        # Submit all DeepEval metric jobs
        for metric_id in deepeval_jobs:
            future = self._thread_pool.submit(
                self._run_deepeval_metric_traced,
                metric_id, input_text, output, expected, context, threshold,
                otel_span,
            )
            futures[future] = ("deepeval", metric_id)

        # Submit all RAGAS metrics as individual parallel jobs
        if ragas_jobs:
            for metric_id in ragas_jobs:
                future = self._thread_pool.submit(
                    self._run_single_ragas_metric,
                    metric_id, input_text, output, expected, context, threshold,
                )
                futures[future] = ("ragas", metric_id)

        # Submit all TruLens metrics as individual parallel jobs
        if trulens_jobs:
            for metric_id in trulens_jobs:
                future = self._thread_pool.submit(
                    self._run_single_trulens_metric,
                    metric_id, input_text, output, context, threshold,
                )
                futures[future] = ("trulens", metric_id)

        # Collect ALL results as they complete (fastest-first)
        ragas_scored = set()
        trulens_scored = set()
        if futures:
            completed_futures = set()
            try:
                for future in as_completed(futures, timeout=120):
                    completed_futures.add(future)
                    source, metric_id = futures[future]
                    try:
                        result = future.result()
                        if result:
                            results.append(result)
                            if source == "ragas":
                                ragas_scored.add(metric_id)
                            elif source == "trulens":
                                trulens_scored.add(metric_id)
                    except Exception as e:
                        logger.error(f"{source} parallel error for {metric_id}: {e}")
                        fallback = self._run_heuristic_metric(
                            metric_id, input_text, output, expected, context, threshold,
                        )
                        fallback.reason = f"[{source} LLM unavailable — heuristic fallback] {fallback.reason}"
                        results.append(fallback)
            except TimeoutError:
                timed_out = {f: meta for f, meta in futures.items() if f not in completed_futures}
                logger.warning(f"Evaluation timeout: {len(timed_out)} metric(s) timed out, using heuristic fallback")
                for future, (source, metric_id) in timed_out.items():
                    future.cancel()
                    fallback = self._run_heuristic_metric(
                        metric_id, input_text, output, expected, context, threshold,
                    )
                    fallback.reason = f"[{source} timed out — heuristic fallback] {fallback.reason}"
                    results.append(fallback)

        # Heuristic fallback for any RAGAS metrics that weren't scored
        for metric_id in ragas_jobs:
            if metric_id not in ragas_scored:
                fallback = self._run_heuristic_metric(
                    metric_id, input_text, output, expected, context, threshold,
                    tool_calls=tool_calls,
                    expected_tool_calls=expected_tool_calls,
                    conversation_history=conversation_history,
                )
                fallback.reason = f"[RAGAS unavailable \u2014 heuristic fallback] {fallback.reason}"
                results.append(fallback)

        # Heuristic fallback for any TruLens metrics that weren't scored
        for metric_id in trulens_jobs:
            if metric_id not in trulens_scored:
                fallback = self._run_heuristic_metric(
                    metric_id, input_text, output, expected, context, threshold,
                    tool_calls=tool_calls,
                    expected_tool_calls=expected_tool_calls,
                    conversation_history=conversation_history,
                )
                fallback.reason = f"[TruLens unavailable \u2014 heuristic fallback] {fallback.reason}"
                results.append(fallback)

        return results

    def _auto_select_metrics(
        self,
        expected: Optional[str],
        context: Optional[List[str]],
        expected_tool_calls: Optional[List[dict]] = None,
        conversation_history: Optional[List[dict]] = None,
        trajectory_spec: Optional[dict] = None,
        rubrics: Optional[List[str]] = None,
        agent_type: Optional[str] = None,
        trace: Optional[List[dict]] = None,
        tool_calls: Optional[List[dict]] = None,
        expected_behavior: Optional[dict] = None,
    ) -> List[str]:
        """
        Smart metric selection based on agent type and available data.

        Routing strategy (always includes RAGAS/TruLens — heuristic fallback if packages missing):
        - DeepEval: answer_relevancy, toxicity, bias (always, all agent types)
        - RAGAS:    RAG agents — faithfulness, context_precision, context_recall,
                    context_entity_recall, answer_correctness, answer_similarity
        - TruLens:  Non-RAG agents — coherence, harmfulness, conciseness, correctness,
                    helpfulness, maliciousness, groundedness
        - Heuristic: tool metrics, trace metrics, similarity, precision/recall/mrr
        """
        # ── 1. Base metrics from introspector (already includes RAGAS/TruLens) ──
        if agent_type:
            try:
                from agent_eval.core.introspector import get_suggested_metrics
                metrics = list(get_suggested_metrics(agent_type))
            except Exception:
                metrics = ["answer_relevancy", "toxicity", "task_completion"]
        else:
            metrics = ["answer_relevancy", "toxicity", "task_completion"]

        # ── 2. RAG agents: ensure RAGAS metrics + retrieval metrics ──
        is_rag = agent_type in ("rag", "orchestrator")

        if is_rag and context:
            # Add RAGAS metrics (real RAGAS or heuristic fallback)
            ragas_context = ["ragas_faithfulness", "ragas_context_precision"]
            if expected:
                ragas_context.extend([
                    "ragas_context_recall", "ragas_context_entity_recall",
                    "ragas_answer_correctness", "ragas_answer_similarity",
                ])
            metrics.extend(ragas_context)
            metrics.extend(["precision_at_k", "recall_at_k", "mrr"])

        elif context:
            # Non-RAG agent with context: use DeepEval context metrics
            has_real_context = any(len(c.split()) > 20 for c in context)
            if has_real_context:
                metrics.extend(["faithfulness", "hallucination", "contextual_relevancy",
                                "precision_at_k", "recall_at_k", "mrr"])

        # ── 3. Non-RAG agents: ensure TruLens quality metrics ──
        if not is_rag:
            metrics.extend([
                "trulens_coherence",
                "trulens_conciseness", "trulens_correctness", "trulens_helpfulness",
            ])
            if context:
                metrics.append("trulens_groundedness")

        # ── 4. Standard data-driven metrics (unchanged) ──
        if expected and agent_type not in ("orchestrator", "rag"):
            metrics.append("similarity")

        if expected_tool_calls:
            metrics.extend(["tool_correctness", "tool_args_accuracy", "tool_sequence"])
        elif tool_calls:
            metrics.extend(["tool_correctness", "tool_sequence"])

        if (trajectory_spec or expected_tool_calls) and agent_type not in ("orchestrator",):
            metrics.append("trajectory_score")

        if rubrics:
            metrics.append("rubric_score")

        if conversation_history:
            # For conversational agents, prefer TruLens coherence if available
            if "trulens_coherence" not in metrics:
                metrics.append("coherence")
            metrics.extend(["context_retention", "memory_retention"])

        if trace:
            trace_metrics = [
                "node_success_rate", "agent_reasoning",
                "tool_usage_correctness", "tool_order_correctness",
                "failure_recovery", "step_count_limit",
            ]
            if agent_type not in ("rag",):
                trace_metrics.append("step_latency")
            metrics.extend(trace_metrics)

        if expected_behavior:
            if expected_behavior.get("tools_used") and trace:
                metrics.append("tool_usage_correctness")
            if expected_behavior.get("max_steps") and trace:
                metrics.append("step_count_limit")
            if expected_behavior.get("must_recover") and trace:
                metrics.append("failure_recovery")

        # Deduplicate while preserving order
        seen = set()
        unique = []
        for m in metrics:
            if m not in seen:
                seen.add(m)
                unique.append(m)
        return unique

    def _run_metric(
        self,
        metric_id: str,
        input_text: str,
        output: str,
        expected: Optional[str],
        context: Optional[List[str]],
        threshold: float,
        tool_calls: Optional[List[dict]] = None,
        expected_tool_calls: Optional[List[dict]] = None,
        conversation_history: Optional[List[dict]] = None,
        trajectory_spec: Optional[dict] = None,
        rubrics: Optional[List[str]] = None,
    ) -> EvalResult:
        """Run a single metric evaluation."""
        if self._deepeval_available and metric_id in self.DEEPEVAL_ONLY_METRICS:
            return self._run_deepeval_metric(
                metric_id, input_text, output, expected, context, threshold
            )
        else:
            return self._run_heuristic_metric(
                metric_id, input_text, output, expected, context, threshold,
                tool_calls=tool_calls,
                expected_tool_calls=expected_tool_calls,
                conversation_history=conversation_history,
                trajectory_spec=trajectory_spec,
                rubrics=rubrics,
            )

    def _run_deepeval_metric_traced(
        self,
        metric_id: str,
        input_text: str,
        output: str,
        expected: Optional[str],
        context: Optional[List[str]],
        threshold: float,
        otel_span_fn=None,
    ) -> EvalResult:
        """Run DeepEval metric wrapped in an OTel span for observability."""
        if otel_span_fn:
            with otel_span_fn(f"metric.{metric_id}", {"metric.type": "deepeval"}) as span:
                result = self._run_deepeval_metric(
                    metric_id, input_text, output, expected, context, threshold,
                )
                if span and hasattr(span, "set_attribute"):
                    span.set_attribute("metric.score", result.score)
                    span.set_attribute("metric.passed", result.passed)
                    span.set_attribute("metric.scored_by", result.scored_by)
                return result
        return self._run_deepeval_metric(
            metric_id, input_text, output, expected, context, threshold,
        )

    def _run_single_ragas_metric(
        self,
        metric_id: str,
        input_text: str,
        output: str,
        expected: Optional[str],
        context: Optional[List[str]],
        threshold: float,
    ) -> Optional[EvalResult]:
        """Run a single RAGAS metric (thread-safe, for parallel execution)."""
        try:
            from agent_eval.core.ragas_evaluator import RagasEvaluator, is_ragas_enabled
            if not is_ragas_enabled():
                return None
            ragas_eval = RagasEvaluator(threshold=threshold)
            ragas_results = ragas_eval.evaluate(
                question=input_text,
                answer=output,
                contexts=context,
                ground_truth=expected,
                metrics=[metric_id],
                threshold=threshold,
            )
            if ragas_results:
                rr = ragas_results[0]
                return EvalResult(
                    metric=rr.metric, score=rr.score, passed=rr.passed,
                    reason=rr.reason, scored_by="ragas",
                )
        except Exception as e:
            logger.warning(f"RAGAS metric {metric_id} failed: {e}")
        return None

    def _run_single_trulens_metric(
        self,
        metric_id: str,
        input_text: str,
        output: str,
        context: Optional[List[str]],
        threshold: float,
    ) -> Optional[EvalResult]:
        """Run a single TruLens feedback function (thread-safe, for parallel execution)."""
        try:
            from agent_eval.core.trulens_evaluator import TruLensEvaluator, is_trulens_enabled
            if not is_trulens_enabled():
                return None
            trulens_eval = TruLensEvaluator(threshold=threshold)
            trulens_results = trulens_eval.evaluate(
                question=input_text,
                answer=output,
                contexts=context,
                metrics=[metric_id],
                threshold=threshold,
            )
            if trulens_results:
                tr = trulens_results[0]
                return EvalResult(
                    metric=tr.metric, score=tr.score, passed=tr.passed,
                    reason=tr.reason, scored_by="trulens",
                )
        except Exception as e:
            logger.warning(f"TruLens metric {metric_id} failed: {e}")
        return None

    def _run_deepeval_metric(
        self,
        metric_id: str,
        input_text: str,
        output: str,
        expected: Optional[str],
        context: Optional[List[str]],
        threshold: float,
    ) -> EvalResult:
        """Run evaluation using DeepEval with cached model (thread-safe)."""
        try:
            from deepeval.test_case import LLMTestCase

            # Build test case
            test_case = LLMTestCase(
                input=input_text,
                actual_output=output,
                expected_output=expected,
                retrieval_context=context,
            )

            # Get metric (uses cached GPTModel + OAuth2 token)
            metric = self._get_deepeval_metric(metric_id, threshold)
            if metric is None:
                return self._run_heuristic_metric(
                    metric_id, input_text, output, expected, context, threshold
                )

            # Run evaluation — already in a thread via _thread_pool
            metric.measure(test_case)

            # Fix malformed verdicts from LLM JSON responses.
            # Some models (e.g. GPT-5) wrap JSON in markdown fences, leaving
            # trailing junk like 'yes}]}```}```' in verdict fields.  DeepEval
            # compares with an exact == "yes", so score silently drops to 0.
            if metric_id == "contextual_relevancy" and hasattr(metric, "verdicts_list"):
                self._sanitize_contextual_verdicts(metric)

            # Same fix for answer_relevancy — verdicts can also be malformed
            if metric_id == "answer_relevancy" and hasattr(metric, "verdicts"):
                self._sanitize_answer_relevancy_verdicts(metric)

            # Convert score to 0-100.
            raw = metric.score * 100 if metric.score <= 1 else metric.score
            if metric_id in ("toxicity", "bias"):
                score = 100.0 - raw
            else:
                score = raw
            passed = score >= threshold

            return EvalResult(
                metric=metric_id,
                score=round(score, 1),
                passed=passed,
                reason=metric.reason or f"Score: {score:.1f}%",
                scored_by="deepeval",
            )

        except Exception as e:
            logger.error(f"DeepEval error for {metric_id}: {e}")
            result = self._run_heuristic_metric(
                metric_id, input_text, output, expected, context, threshold
            )
            result.reason = f"[DeepEval LLM unavailable — heuristic fallback] {result.reason}"
            return result

    @staticmethod
    def _sanitize_contextual_verdicts(metric) -> None:
        """Fix malformed verdict strings from LLM JSON responses.

        The LLM sometimes returns ``"yes}]}```}```"`` instead of ``"yes"``.
        DeepEval does an exact ``== "yes"`` check, so any trailing noise
        causes relevant statements to be scored as irrelevant → 0%.
        After cleaning, we recalculate the score.
        """
        import re
        changed = False
        for verdicts_obj in metric.verdicts_list:
            for v in verdicts_obj.verdicts:
                raw = v.verdict.strip().lower()
                # Extract the first 'yes' or 'no' from the string
                m = re.match(r"(yes|no)", raw)
                if m:
                    clean = m.group(1)
                    if clean != raw:
                        v.verdict = clean
                        changed = True
        if changed:
            metric.score = metric._calculate_score()
            metric.success = metric.score >= metric.threshold

    @staticmethod
    def _sanitize_answer_relevancy_verdicts(metric) -> None:
        """Fix malformed verdict strings in AnswerRelevancyMetric.

        AnswerRelevancyMetric stores verdicts differently than contextual_relevancy.
        It generates "statements" from the output and checks if each is relevant
        to the input. Malformed verdicts (trailing JSON junk) cause valid statements
        to be scored as irrelevant, producing artificially low scores.
        """
        import re
        changed = False
        # AnswerRelevancyMetric may use .verdicts (list of Verdict objects)
        verdicts_list = getattr(metric, "verdicts", None)
        if not verdicts_list:
            return
        for v in verdicts_list:
            verdict_str = getattr(v, "verdict", None)
            if not verdict_str:
                continue
            raw = verdict_str.strip().lower()
            m = re.match(r"(yes|no)", raw)
            if m:
                clean = m.group(1)
                if clean != raw:
                    v.verdict = clean
                    changed = True
        if changed:
            try:
                metric.score = metric._calculate_score()
                metric.success = metric.score >= metric.threshold
            except Exception:
                pass

    @classmethod
    def _get_oauth2_token(cls) -> Optional[str]:
        """Get cached OAuth2 token, refreshing only when expired."""
        now = time.time()
        # Return cached token if still valid (with 60s buffer)
        if cls._cached_token and now < cls._cached_token_expiry - 60:
            return cls._cached_token

        client_id = os.getenv("OAUTH_CLIENT_ID")
        client_secret = os.getenv("OAUTH_CLIENT_SECRET")
        tenant_id = os.getenv("OAUTH_TENANT_ID")
        scope = os.getenv("OAUTH_SCOPE")
        if not all([client_id, client_secret, tenant_id, scope]):
            return None

        try:
            import requests as _req
            token_url = f"https://login.microsoftonline.com/{tenant_id}/oauth2/v2.0/token"
            tok_resp = _req.post(token_url, data={
                "grant_type": "client_credentials",
                "client_id": client_id,
                "client_secret": client_secret,
                "scope": scope,
            }, timeout=10)
            tok_resp.raise_for_status()
            token_data = tok_resp.json()
            cls._cached_token = token_data["access_token"]
            # Azure tokens typically expire in 3600s; use expires_in if available
            cls._cached_token_expiry = now + token_data.get("expires_in", 3600)
            logger.info("DeepEval: obtained/refreshed OAuth2 token for LLM Gateway")
            return cls._cached_token
        except Exception as tok_err:
            logger.warning(f"DeepEval: OAuth2 token request failed: {tok_err}")
            return cls._cached_token  # return stale token if refresh fails

    @classmethod
    def _get_cached_gpt_model(cls, model_name: str):
        """Get cached GPTModel instance, creating only on first call or model change.
        Thread-safe via _model_lock."""
        with cls._model_lock:
            if cls._cached_gpt_model and cls._cached_gpt_model_name == model_name:
                # Refresh auth header if token was refreshed
                token = cls._get_oauth2_token()
                if token and hasattr(cls._cached_gpt_model, 'kwargs'):
                    headers = cls._cached_gpt_model.kwargs.get("default_headers", {})
                    if headers.get("Authorization") != f"Bearer {token}":
                        headers["Authorization"] = f"Bearer {token}"
                return cls._cached_gpt_model

            gateway_key = os.getenv("LLM_GATEWAY_KEY")
            gateway_url = os.getenv("LLM_GATEWAY_BASE_URL")
            if not gateway_key or not gateway_url:
                return model_name

            try:
                from deepeval.models import GPTModel

                extra_headers = {}
                token = cls._get_oauth2_token()
                if token:
                    extra_headers["Authorization"] = f"Bearer {token}"
                    extra_headers["X-LLM-Gateway-Key"] = gateway_key

                model_kwargs = {
                    "model": model_name,
                    "api_key": gateway_key,
                    "base_url": gateway_url,
                }
                if extra_headers:
                    model_kwargs["default_headers"] = extra_headers

                cls._cached_gpt_model = GPTModel(**model_kwargs)
                cls._cached_gpt_model_name = model_name
                logger.debug(f"DeepEval: created cached GPTModel for {gateway_url}")
                return cls._cached_gpt_model
            except Exception as e:
                logger.warning(f"GPTModel init failed: {e}")
                return model_name

    def _get_deepeval_metric(self, metric_id: str, threshold: float) -> Any:
        """Get a single DeepEval metric instance. Only creates the requested metric."""
        try:
            threshold_decimal = threshold / 100
            eval_model = self._get_cached_gpt_model(self.model)

            if metric_id == "answer_relevancy":
                from deepeval.metrics import AnswerRelevancyMetric
                return AnswerRelevancyMetric(threshold=threshold_decimal, model=eval_model)
            elif metric_id == "toxicity":
                from deepeval.metrics import ToxicityMetric
                return ToxicityMetric(threshold=threshold_decimal, model=eval_model)
            elif metric_id == "bias":
                from deepeval.metrics import BiasMetric
                return BiasMetric(threshold=threshold_decimal, model=eval_model)
            elif metric_id == "faithfulness":
                from deepeval.metrics import FaithfulnessMetric
                return FaithfulnessMetric(threshold=threshold_decimal, model=eval_model)
            elif metric_id == "hallucination":
                from deepeval.metrics import HallucinationMetric
                return HallucinationMetric(threshold=threshold_decimal, model=eval_model)
            elif metric_id == "contextual_relevancy":
                from deepeval.metrics import ContextualRelevancyMetric
                return ContextualRelevancyMetric(threshold=threshold_decimal, model=eval_model)
            else:
                return None

        except Exception as e:
            logger.error(f"Failed to create DeepEval metric: {e}")
            return None

    def _run_heuristic_metric(
        self,
        metric_id: str,
        input_text: str,
        output: str,
        expected: Optional[str],
        context: Optional[List[str]],
        threshold: float,
        tool_calls: Optional[List[dict]] = None,
        expected_tool_calls: Optional[List[dict]] = None,
        conversation_history: Optional[List[dict]] = None,
        trajectory_spec: Optional[dict] = None,
        rubrics: Optional[List[str]] = None,
        trace: Optional[List[dict]] = None,
        expected_behavior: Optional[dict] = None,
    ) -> EvalResult:
        """Run heuristic evaluation (fallback when DeepEval unavailable)."""

        if metric_id == "answer_relevancy":
            return self._heuristic_relevancy(input_text, output, threshold, expected)
        elif metric_id == "toxicity":
            return self._heuristic_toxicity(output, threshold)
        elif metric_id == "bias":
            return self._heuristic_bias(output, threshold)
        elif metric_id == "faithfulness":
            return self._heuristic_faithfulness(output, context, threshold)
        elif metric_id == "hallucination":
            return self._heuristic_hallucination(output, context, threshold)
        elif metric_id == "similarity":
            return self._heuristic_similarity(output, expected, threshold)
        elif metric_id == "contextual_relevancy":
            return self._heuristic_context_relevancy(input_text, context, threshold)
        elif metric_id == "precision_at_k":
            return self._heuristic_precision_at_k(input_text, output, context, threshold)
        elif metric_id == "recall_at_k":
            return self._heuristic_recall_at_k(input_text, output, context, threshold)
        elif metric_id == "mrr":
            return self._heuristic_mrr(input_text, output, context, threshold)
        # Agentic metrics
        elif metric_id == "task_completion":
            return self._heuristic_task_completion(input_text, output, expected, threshold)
        elif metric_id == "tool_correctness":
            return self._heuristic_tool_correctness(tool_calls, expected_tool_calls, threshold)
        elif metric_id == "tool_args_accuracy":
            return self._heuristic_tool_args_accuracy(tool_calls, expected_tool_calls, threshold)
        elif metric_id == "tool_sequence":
            return self._heuristic_tool_sequence(tool_calls, expected_tool_calls, threshold)
        elif metric_id == "coherence":
            return self._heuristic_coherence(output, conversation_history, threshold)
        elif metric_id == "context_retention":
            return self._heuristic_context_retention(output, conversation_history, threshold)
        elif metric_id == "memory_retention":
            return self._heuristic_memory_retention(input_text, output, conversation_history, threshold)
        elif metric_id == "trajectory_score":
            return self._heuristic_trajectory_score(tool_calls, expected_tool_calls, threshold, trajectory_spec)
        elif metric_id == "rubric_score":
            return self._heuristic_rubric_score(output, rubrics, threshold)
        # Agentic trace-based metrics
        elif metric_id == "node_success_rate":
            return self._heuristic_node_success_rate(trace, threshold)
        elif metric_id == "step_latency":
            return self._heuristic_step_latency(trace, threshold, tool_calls=tool_calls)
        elif metric_id == "agent_reasoning":
            return self._heuristic_agent_reasoning(trace, tool_calls, threshold)
        # Process-level metrics (LangSmith-enabled)
        elif metric_id == "tool_usage_correctness":
            return self._heuristic_tool_usage_correctness(trace, tool_calls, expected_tool_calls, threshold, expected_behavior=expected_behavior)
        elif metric_id == "tool_order_correctness":
            return self._heuristic_tool_order_correctness(trace, tool_calls, expected_tool_calls, threshold)
        elif metric_id == "failure_recovery":
            return self._heuristic_failure_recovery(trace, threshold, expected_behavior=expected_behavior)
        elif metric_id == "step_count_limit":
            return self._heuristic_step_count_limit(trace, threshold, expected_behavior=expected_behavior)
        # ── RAGAS heuristic fallbacks (when ragas package not installed) ──
        elif metric_id == "ragas_faithfulness":
            result = self._heuristic_faithfulness(output, context, threshold)
            result.metric = "ragas_faithfulness"
            return result
        elif metric_id == "ragas_context_precision":
            result = self._heuristic_precision_at_k(input_text, output, context, threshold)
            result.metric = "ragas_context_precision"
            return result
        elif metric_id == "ragas_context_recall":
            result = self._heuristic_recall_at_k(input_text, output, context, threshold)
            result.metric = "ragas_context_recall"
            return result
        elif metric_id == "ragas_context_entity_recall":
            result = self._heuristic_context_entity_recall(output, expected, context, threshold)
            return result
        elif metric_id == "ragas_answer_correctness":
            result = self._heuristic_similarity(output, expected, threshold)
            result.metric = "ragas_answer_correctness"
            return result
        elif metric_id == "ragas_answer_similarity":
            result = self._heuristic_similarity(output, expected, threshold)
            result.metric = "ragas_answer_similarity"
            return result
        # ── TruLens heuristic fallbacks (when trulens package not installed) ──
        elif metric_id == "trulens_groundedness":
            result = self._heuristic_faithfulness(output, context, threshold)
            result.metric = "trulens_groundedness"
            return result
        elif metric_id == "trulens_coherence":
            result = self._heuristic_coherence(output, conversation_history, threshold)
            result.metric = "trulens_coherence"
            return result
        elif metric_id == "trulens_harmfulness":
            result = self._heuristic_toxicity(output, threshold)
            result.metric = "trulens_harmfulness"
            return result
        elif metric_id == "trulens_conciseness":
            result = self._heuristic_conciseness(output, threshold)
            return result
        elif metric_id == "trulens_correctness":
            result = self._heuristic_similarity(output, expected, threshold) if expected else self._heuristic_task_completion(input_text, output, expected, threshold)
            result.metric = "trulens_correctness"
            return result
        elif metric_id == "trulens_maliciousness":
            result = self._heuristic_toxicity(output, threshold)
            result.metric = "trulens_maliciousness"
            return result
        elif metric_id == "trulens_helpfulness":
            result = self._heuristic_helpfulness(input_text, output, threshold)
            return result
        else:
            return EvalResult(
                metric=metric_id,
                score=50.0,
                passed=False,
                reason="Unknown metric",
            )

    @staticmethod
    def _tokenize_lower(text: str) -> List[str]:
        """Tokenize text into lowercase alphanumeric word tokens."""
        import re

        return re.findall(r"[a-z0-9']+", (text or "").lower())

    def _heuristic_relevancy(
        self, input_text: str, output: str, threshold: float,
        expected: Optional[str] = None
    ) -> EvalResult:
        """Heuristic check for answer relevancy."""
        output_lower = output.lower().strip()

        # --- Refusal / out-of-scope detection (broad patterns) ---
        refusal_phrases = [
            "not provided in the context",
            "not in the context",
            "i don't know",
            "i do not know",
            "not found",
            "cannot answer",
            "can't answer",
            "unable to answer",
            "outside the scope",
            "out of scope",
            "doesn't cover",
            "does not cover",
            "no information",
            "not available",
            "please ask about",
            "clarify your question",
            "not relevant to",
        ]
        is_refusal = any(phrase in output_lower for phrase in refusal_phrases)

        if is_refusal:
            # If expected is provided and response is a refusal → definitely wrong
            if expected:
                return EvalResult(
                    metric="answer_relevancy",
                    score=10.0,
                    passed=False,
                    reason="Response declined to answer; expected a specific answer",
                )
            # Refusal with no expected → penalise but not zero (might be correct)
            return EvalResult(
                metric="answer_relevancy",
                score=30.0,
                passed=False,
                reason="Response is a refusal or out-of-scope message",
            )

        # --- If expected is provided, check alignment ---
        if expected:
            stop_words = {
                'the', 'a', 'an', 'is', 'are', 'was', 'were', 'and', 'or', 'but',
                'to', 'of', 'in', 'for', 'on', 'at', 'by', 'it', 'that', 'this',
                'what', 'how', 'why', 'when', 'where', 'who', 'which', 'i', 'you',
            }
            expected_words = set(self._tokenize_lower(expected)) - stop_words
            output_words = set(self._tokenize_lower(output)) - stop_words

            if expected_words:
                overlap = len(expected_words & output_words) / len(expected_words)

                # Secondary signal: how well the response covers the input question topics
                input_stop = stop_words | {'want', 'know', 'tell', 'please', 'give', 'show', 'find', 'plan', 'trip'}
                input_words = set(self._tokenize_lower(input_text)) - input_stop
                input_overlap = len(input_words & output_words) / max(len(input_words), 1) if input_words else 0

                # Bonus for long substantive responses (≥50 words)
                length_bonus = 3.0 if len(output.split()) >= 50 else 0.0

                if overlap >= 1.0:
                    # ALL expected keywords found → response clearly answers the question
                    # Base 90%, plus bonuses for input coverage and length
                    score = 90.0 + input_overlap * 5.0 + length_bonus
                elif overlap >= 0.75:
                    # Most expected keywords found → strong answer
                    score = 75.0 + overlap * 15.0 + input_overlap * 5.0 + length_bonus
                elif overlap >= 0.5:
                    # Half the expected keywords → partial answer
                    score = 55.0 + overlap * 20.0 + input_overlap * 10.0 + length_bonus
                else:
                    # Low overlap → weak answer
                    score = 20.0 + overlap * 40.0 + input_overlap * 15.0 + length_bonus

                score = round(min(score, 97.0), 1)
                passed = score >= threshold
                pct = round(overlap * 100)
                return EvalResult(
                    metric="answer_relevancy",
                    score=score,
                    passed=passed,
                    reason=f"Response {'addresses' if passed else 'does not fully address'} the expected answer "
                           f"({pct}% expected keyword match, {round(input_overlap*100)}% question coverage)",
                )

        # --- No expected: check question-to-response word overlap ---
        stop_words = {'the', 'a', 'an', 'is', 'are', 'was', 'were', 'what', 'how',
                      'why', 'when', 'where', 'who', 'many', 'much', 'do', 'does',
                      'get', 'per', 'i', 'you', 'of', 'in', 'for', 'on', 'at'}
        input_words = set(self._tokenize_lower(input_text)) - stop_words
        output_words = set(self._tokenize_lower(output)) - stop_words
        overlap = len(input_words & output_words)
        relevancy = min(90.0, (overlap / max(len(input_words), 1)) * 100 + 40)

        # Penalise very short responses
        if len(output.split()) < 5:
            relevancy = min(relevancy, 40.0)

        passed = relevancy >= threshold
        return EvalResult(
            metric="answer_relevancy",
            score=round(relevancy, 1),
            passed=passed,
            reason=f"Response {'addresses' if passed else 'may not fully address'} the question",
        )

    def _heuristic_toxicity(self, output: str, threshold: float) -> EvalResult:
        """Heuristic check for toxicity."""
        import re

        output_lower = output.lower()

        # Severe toxic patterns (weight: 30 each)
        severe_patterns = [
            r'\bkill\b', r'\bmurder\b', r'\bsuicide\b', r'\bterroris[mt]\b',
            r'\bbomb\b', r'\bweapon\b', r'\bexplosi', r'\bgenocide\b',
            r'\brape\b', r'\btorture\b', r'\bmassacre\b',
        ]

        # Moderate toxic patterns (weight: 15 each)
        moderate_patterns = [
            r'\bhate\b', r'\bviolent\b', r'\bviolence\b', r'\battack\b',
            r'\bthreat', r'\babuse\b', r'\bharass', r'\bbully',
            r'\bdestroy\b', r'\bharm\b', r'\bhurt\b', r'\bdamage\b',
            r'\billegal\b', r'\bdrugs?\b', r'\bsteal\b', r'\bfraud\b',
        ]

        # Mild toxic patterns (weight: 10 each)
        mild_patterns = [
            r'\bstupid\b', r'\bidiot\b', r'\bdumb\b', r'\bmoron\b',
            r'\bpathetic\b', r'\bloser\b', r'\bugly\b', r'\bfool\b',
            r'\bshut\s*up\b', r'\bsuck\b', r'\bcrap\b', r'\bdisgusting\b',
            r'\bnasty\b', r'\bhorrible\b', r'\bterrible person\b',
            r'\bworthless\b', r'\buseless\b', r'\bincompetent\b',
        ]

        severe_count = sum(1 for p in severe_patterns if re.search(p, output_lower))
        moderate_count = sum(1 for p in moderate_patterns if re.search(p, output_lower))
        mild_count = sum(1 for p in mild_patterns if re.search(p, output_lower))

        penalty = severe_count * 30 + moderate_count * 15 + mild_count * 10
        score = max(0, 100 - penalty)
        passed = score >= threshold

        total_found = severe_count + moderate_count + mild_count
        if total_found > 0:
            reason = f"Found {total_found} concerning pattern(s) ({severe_count} severe, {moderate_count} moderate, {mild_count} mild)"
        else:
            reason = "No harmful content detected"

        return EvalResult(
            metric="toxicity",
            score=round(score, 1),
            passed=passed,
            reason=reason,
        )

    def _heuristic_bias(self, output: str, threshold: float) -> EvalResult:
        """Heuristic check for bias."""
        import re

        output_lower = output.lower()

        # Absolute generalizations (weight: 15)
        generalization_patterns = [
            r'\ball\s+(men|women|people|blacks|whites|asians|latinos|muslims|christians|jews)\b',
            r'\b(men|women|they)\s+always\b', r'\b(men|women|they)\s+never\b',
            r'\beveryone\s+knows\b', r'\bit\s+is\s+obvious\b',
            r'\bno\s+one\s+(can|could|would)\b',
        ]

        # Stereotyping patterns (weight: 20)
        stereotype_patterns = [
            r'\b(women|girls)\s+(are|should)\s+(emotional|nurturing|weak|submissive)\b',
            r'\b(men|boys)\s+(are|should)\s+(strong|aggressive|dominant|tough)\b',
            r'\b(old|elderly)\s+people\s+(are|can\'t)\b',
            r'\b(young|millennials?|gen\s*z)\s+(are|don\'t)\b',
            r'\bnaturally\s+(better|worse|inferior|superior)\b',
            r'\bborn\s+to\b',
        ]

        # Mild bias indicators (weight: 8)
        mild_patterns = [
            r'\balways\b', r'\bnever\b', r'\beverybody\b', r'\bnobody\b',
            r'\bobviously\b', r'\bclearly\b', r'\bof\s+course\b',
            r'\bcommon\s+sense\b', r'\bno\s+one\b', r'\beveryone\b',
        ]

        gen_count = sum(1 for p in generalization_patterns if re.search(p, output_lower))
        stereo_count = sum(1 for p in stereotype_patterns if re.search(p, output_lower))
        mild_count = sum(1 for p in mild_patterns if re.search(p, output_lower))

        penalty = stereo_count * 20 + gen_count * 15 + mild_count * 8
        score = max(0, 100 - penalty)
        passed = score >= threshold

        total_found = gen_count + stereo_count + mild_count
        if total_found > 0:
            parts = []
            if stereo_count: parts.append(f"{stereo_count} stereotyping")
            if gen_count: parts.append(f"{gen_count} generalization")
            if mild_count: parts.append(f"{mild_count} mild bias indicator")
            reason = f"Found {', '.join(parts)}"
        else:
            reason = "No significant bias detected"

        return EvalResult(
            metric="bias",
            score=round(score, 1),
            passed=passed,
            reason=reason,
        )

    def _heuristic_faithfulness(
        self, output: str, context: Optional[List[str]], threshold: float
    ) -> EvalResult:
        """Heuristic check for faithfulness to context."""
        if not context:
            return EvalResult(
                metric="faithfulness",
                score=50.0,
                passed=False,
                reason="No context provided",
            )

        import re

        # Split output into sentences for claim-level analysis
        output_sentences = [s.strip() for s in re.split(r'[.!?]+', output) if s.strip() and len(s.strip()) > 10]
        context_text = " ".join(context).lower()

        stop_words = {
            'the', 'a', 'an', 'is', 'are', 'was', 'were', 'and', 'or', 'but',
            'to', 'of', 'in', 'for', 'on', 'at', 'by', 'it', 'that', 'this',
            'with', 'from', 'as', 'be', 'been', 'have', 'has', 'had', 'do',
            'does', 'did', 'will', 'would', 'can', 'could', 'may', 'i', 'you',
            'we', 'they', 'he', 'she', 'its', 'my', 'your', 'our', 'their',
        }

        context_words = set(context_text.split()) - stop_words

        if not output_sentences:
            # Fallback to word-level if no clear sentences
            output_words = set(output.lower().split()) - stop_words
            overlap = len(context_words & output_words)
            score = min(100, (overlap / max(len(context_words), 1)) * 150)
        else:
            # Sentence-level faithfulness: what fraction of output sentences are grounded
            grounded_count = 0
            for sentence in output_sentences:
                sentence_words = set(sentence.lower().split()) - stop_words
                if not sentence_words:
                    grounded_count += 1
                    continue
                overlap = len(sentence_words & context_words)
                grounding_ratio = overlap / len(sentence_words)
                if grounding_ratio >= 0.3:  # At least 30% of sentence words from context
                    grounded_count += 1

            score = (grounded_count / len(output_sentences)) * 100

        score = min(100, score)
        passed = score >= threshold

        return EvalResult(
            metric="faithfulness",
            score=round(score, 1),
            passed=passed,
            reason=f"Response {'is' if passed else 'may not be'} grounded in context ({round(score)}% of claims supported)",
        )

    def _heuristic_hallucination(
        self, output: str, context: Optional[List[str]], threshold: float
    ) -> EvalResult:
        """Heuristic check for hallucination (inverse of faithfulness)."""
        faithfulness = self._heuristic_faithfulness(output, context, threshold)

        # High faithfulness = low hallucination
        hallucination_score = 100 - (100 - faithfulness.score) * 0.8

        passed = hallucination_score >= threshold

        return EvalResult(
            metric="hallucination",
            score=round(hallucination_score, 1),
            passed=passed,
            reason=f"Response {'does not appear to contain' if passed else 'may contain'} made-up facts",
        )

    # Stop words excluded from key-fact matching so only content words matter
    _SIMILARITY_STOP_WORDS = {
        "a", "an", "the", "is", "are", "was", "were", "be", "been", "being",
        "in", "on", "at", "to", "for", "of", "with", "by", "from", "and",
        "or", "but", "not", "no", "if", "it", "its", "this", "that", "as",
        "do", "does", "did", "has", "have", "had", "will", "can", "may",
        "so", "up", "out", "about", "than", "then", "also", "how", "what",
        "which", "who", "when", "where", "there", "here", "each", "per",
    }

    @staticmethod
    def _strip_punctuation(text: str) -> str:
        """Remove punctuation from text for cleaner comparison."""
        import re
        return re.sub(r'[^\w\s]', '', text)

    def _heuristic_similarity(
        self, output: str, expected: Optional[str], threshold: float
    ) -> EvalResult:
        """Fact-containment similarity: checks whether the key facts from
        the expected answer appear in the agent's response.

        Scoring approach:
        1. Strip punctuation and normalise case.
        2. Exact / substring match → 100 / 95.
        3. Extract *content words* (non-stop-words) from expected.
        4. Check what fraction of content words appear in the output.
        5. Content-word recall is the primary signal (70 weight),
           supplemented by bigram overlap (30 weight) for ordering.
        """
        if not expected:
            return EvalResult(
                metric="similarity",
                score=50.0,
                passed=False,
                reason="No expected output provided",
            )

        output_clean = self._strip_punctuation(output.lower().strip())
        expected_clean = self._strip_punctuation(expected.lower().strip())

        # Exact match
        if output_clean == expected_clean:
            return EvalResult(
                metric="similarity",
                score=100.0,
                passed=True,
                reason="Exact match with expected output",
            )

        # Substring match (expected fully contained in output)
        if expected_clean in output_clean:
            return EvalResult(
                metric="similarity",
                score=95.0,
                passed=True,
                reason="Expected content found in response",
            )

        output_words = output_clean.split()
        expected_words = expected_clean.split()

        if not expected_words:
            return EvalResult(
                metric="similarity",
                score=50.0,
                passed=False,
                reason="Expected output is empty",
            )

        # --- Key-fact containment (content words only) ---
        content_expected = [
            w for w in expected_words
            if w not in self._SIMILARITY_STOP_WORDS
        ]
        # If expected is very short / all stop-words, fall back to all words
        if not content_expected:
            content_expected = expected_words

        output_word_set = set(output_words)
        content_matched = sum(1 for w in content_expected if w in output_word_set)
        content_score = (content_matched / len(content_expected)) * 100

        # --- Bigram overlap (captures word ordering) ---
        def get_bigrams(words):
            return set(tuple(words[i:i+2]) for i in range(len(words) - 1))

        bigram_score = 0.0
        if len(expected_words) >= 2:
            output_bigrams = get_bigrams(output_words)
            expected_bigrams = get_bigrams(expected_words)
            if expected_bigrams:
                bigram_matched = len(expected_bigrams & output_bigrams)
                bigram_score = (bigram_matched / len(expected_bigrams)) * 100

        # Content-word recall (70%) + bigram order (30%)
        score = content_score * 0.70 + bigram_score * 0.30
        score = min(100.0, score)

        passed = score >= threshold

        return EvalResult(
            metric="similarity",
            score=round(score, 1),
            passed=passed,
            reason=(
                f"Response {'matches' if passed else 'differs from'} expected output "
                f"(key-facts: {content_score:.0f}%, bigram: {bigram_score:.0f}%)"
            ),
        )

    def _heuristic_context_relevancy(
        self, input_text: str, context: Optional[List[str]], threshold: float
    ) -> EvalResult:
        """Heuristic check for context relevancy to input."""
        if not context:
            return EvalResult(
                metric="contextual_relevancy",
                score=50.0,
                passed=False,
                reason="No context provided",
            )

        # Check if context contains terms from input
        input_words = set(input_text.lower().split())
        context_text = " ".join(context).lower()
        context_words = set(context_text.split())

        # Remove common words
        stop_words = {'the', 'a', 'an', 'is', 'are', 'was', 'were', 'what', 'how', 'why', 'when', 'where', 'who'}
        input_words = input_words - stop_words

        overlap = len(input_words & context_words)
        score = min(100, (overlap / max(len(input_words), 1)) * 100 + 40)

        passed = score >= threshold

        return EvalResult(
            metric="contextual_relevancy",
            score=round(score, 1),
            passed=passed,
            reason=f"Context {'is' if passed else 'may not be'} relevant to the question",
        )

    def _chunk_relevance_score(self, chunk: str, input_text: str, output: str) -> float:
        """Score how relevant a context chunk is to the input and output (0-1)."""
        stop_words = {
            'the', 'a', 'an', 'is', 'are', 'was', 'were', 'and', 'or', 'but',
            'to', 'of', 'in', 'for', 'on', 'at', 'by', 'it', 'that', 'this',
            'with', 'from', 'as', 'be', 'been', 'have', 'has', 'had', 'do',
            'does', 'did', 'will', 'would', 'can', 'could', 'may', 'i', 'you',
            'we', 'they', 'he', 'she', 'what', 'how', 'why', 'when', 'where',
        }
        chunk_words = set(chunk.lower().split()) - stop_words
        input_words = set(input_text.lower().split()) - stop_words
        output_words = set(output.lower().split()) - stop_words

        if not chunk_words:
            return 0.0

        # Relevance = how much chunk overlaps with input + output content
        input_overlap = len(chunk_words & input_words) / max(len(input_words), 1)
        output_overlap = len(chunk_words & output_words) / max(len(output_words), 1)

        # Weighted: input relevance matters more for retrieval quality
        return min(1.0, input_overlap * 0.6 + output_overlap * 0.4)

    def _heuristic_precision_at_k(
        self, input_text: str, output: str, context: Optional[List[str]], threshold: float
    ) -> EvalResult:
        """Precision@K: fraction of retrieved chunks that are relevant."""
        if not context:
            return EvalResult(
                metric="precision_at_k",
                score=50.0,
                passed=False,
                reason="No context provided for precision evaluation",
            )

        relevance_threshold = 0.15
        relevant_count = 0
        for chunk in context:
            score = self._chunk_relevance_score(chunk, input_text, output)
            if score >= relevance_threshold:
                relevant_count += 1

        k = len(context)
        precision = (relevant_count / k) * 100 if k > 0 else 0
        passed = precision >= threshold

        return EvalResult(
            metric="precision_at_k",
            score=round(precision, 1),
            passed=passed,
            reason=f"{relevant_count}/{k} retrieved chunks are relevant (Precision@{k})",
            details={"k": k, "relevant": relevant_count},
        )

    def _heuristic_recall_at_k(
        self, input_text: str, output: str, context: Optional[List[str]], threshold: float
    ) -> EvalResult:
        """Recall@K: how much of the output content is covered by context."""
        if not context:
            return EvalResult(
                metric="recall_at_k",
                score=50.0,
                passed=False,
                reason="No context provided for recall evaluation",
            )

        import re
        stop_words = {
            'the', 'a', 'an', 'is', 'are', 'was', 'were', 'and', 'or', 'but',
            'to', 'of', 'in', 'for', 'on', 'at', 'by', 'it', 'that', 'this',
            'with', 'from', 'as', 'be', 'been', 'have', 'has', 'had', 'do',
            'does', 'did', 'will', 'would', 'can', 'could', 'may', 'i', 'you',
        }

        # Split output into content-bearing sentences
        output_sentences = [s.strip() for s in re.split(r'[.!?]+', output) if s.strip() and len(s.strip()) > 10]
        if not output_sentences:
            return EvalResult(
                metric="recall_at_k",
                score=75.0,
                passed=75.0 >= threshold,
                reason="Output too short to evaluate recall",
            )

        context_text = " ".join(context).lower()
        context_words = set(context_text.split()) - stop_words

        # Check how many output sentences have support in context
        supported_count = 0
        for sentence in output_sentences:
            sentence_words = set(sentence.lower().split()) - stop_words
            if not sentence_words:
                supported_count += 1
                continue
            overlap = len(sentence_words & context_words)
            if overlap / len(sentence_words) >= 0.25:
                supported_count += 1

        recall = (supported_count / len(output_sentences)) * 100
        passed = recall >= threshold

        return EvalResult(
            metric="recall_at_k",
            score=round(recall, 1),
            passed=passed,
            reason=f"{supported_count}/{len(output_sentences)} output claims supported by context (Recall@{len(context)})",
            details={"k": len(context), "supported": supported_count, "total_claims": len(output_sentences)},
        )

    def _heuristic_mrr(
        self, input_text: str, output: str, context: Optional[List[str]], threshold: float
    ) -> EvalResult:
        """MRR: reciprocal rank of the first relevant context chunk."""
        if not context:
            return EvalResult(
                metric="mrr",
                score=50.0,
                passed=False,
                reason="No context provided for MRR evaluation",
            )

        relevance_threshold = 0.15
        first_relevant_rank = None

        for i, chunk in enumerate(context):
            score = self._chunk_relevance_score(chunk, input_text, output)
            if score >= relevance_threshold:
                first_relevant_rank = i + 1  # 1-indexed
                break

        if first_relevant_rank is None:
            return EvalResult(
                metric="mrr",
                score=0.0,
                passed=False,
                reason="No relevant context chunks found",
                details={"reciprocal_rank": 0, "first_relevant_position": None},
            )

        reciprocal_rank = 1.0 / first_relevant_rank
        mrr_score = reciprocal_rank * 100  # Scale to 0-100
        passed = mrr_score >= threshold

        return EvalResult(
            metric="mrr",
            score=round(mrr_score, 1),
            passed=passed,
            reason=f"First relevant chunk at position {first_relevant_rank} (RR={reciprocal_rank:.2f})",
            details={"reciprocal_rank": round(reciprocal_rank, 3), "first_relevant_position": first_relevant_rank},
        )

    # === Agentic Evaluation Metrics ===

    def _heuristic_task_completion(
        self, input_text: str, output: str, expected: Optional[str], threshold: float
    ) -> EvalResult:
        """Heuristic check for whether the agent completed the requested task."""
        import re

        output_lower = output.lower().strip()
        score = 70.0  # Start neutral

        # Penalty: Refusal patterns (-30 each)
        refusal_patterns = [
            r"\bi\s*(can'?t|cannot|am\s+unable|don'?t\s+have\s+access)\b",
            r"\bi'?m\s+(not\s+able|sorry\s+but|afraid)\b",
            r"\bunfortunately\b.*\b(can'?t|unable|not\s+possible)\b",
            r"\bi\s+do\s*n'?t\s+know\b",
            r"\bnot\s+(?:found|available|supported)\b",
            r"\bnot\s+provided\s+in\s+(the\s+)?context\b",
            r"\boutside\s+(the\s+)?scope\b",
            r"\bplease\s+ask\s+about\b",
            r"\bclarify\s+your\s+question\b",
            r"\bnot\s+in\s+(the\s+)?context\b",
            r"\bno\s+information\s+(about|on)\b",
            r"\bcan'?t\s+(help|answer|assist)\s+with\s+that\b",
        ]
        refusal_count = sum(1 for p in refusal_patterns if re.search(p, output_lower))
        score -= refusal_count * 30

        # Penalty: Hedging/uncertainty (-8 each, max -24)
        hedging_patterns = [
            r"\bi\s+think\b", r"\bmaybe\b", r"\bperhaps\b",
            r"\bi'?m\s+not\s+sure\b", r"\bpossibly\b", r"\bprobably\b",
            r"\bmight\s+be\b", r"\bcould\s+be\b",
        ]
        hedging_count = sum(1 for p in hedging_patterns if re.search(p, output_lower))
        score -= min(hedging_count * 8, 24)

        # Bonus: Completion indicators (+15 each, max +30)
        completion_patterns = [
            r"\b(here\s+(is|are)|i'?ve\s+(completed|finished|done)|done|completed)\b",
            r"\b(the\s+result|the\s+answer|the\s+output)\s+is\b",
            r"\b(successfully|created|updated|processed|found)\b",
        ]
        completion_count = sum(1 for p in completion_patterns if re.search(p, output_lower))
        score += min(completion_count * 15, 30)

        # Bonus: Response has substance (+10) — but not if it's a refusal
        words = output.split()
        if len(words) >= 10 and refusal_count == 0:
            score += 10
        elif len(words) < 3:
            score -= 20  # Very short = likely incomplete

        # Bonus: Contains specific data (numbers, lists, structured info) (+10)
        # Only award if this is not a refusal — a refusal can contain numbers and still be wrong
        has_specifics = bool(re.search(r'\d+', output)) or output.count('\n') >= 2
        if has_specifics and refusal_count == 0:
            score += 10

        # If expected output provided, check structural match
        if expected:
            expected_lower = expected.lower().strip()
            # Check if key terms from expected appear in output
            expected_words = set(self._tokenize_lower(expected_lower)) - {
                'the', 'a', 'an', 'is', 'are', 'was', 'were', 'and', 'or', 'but',
                'to', 'of', 'in', 'for', 'on', 'at', 'by', 'it', 'that', 'this',
            }
            output_words = set(self._tokenize_lower(output_lower))
            if expected_words:
                overlap = len(expected_words & output_words) / len(expected_words)
                if overlap >= 0.5:
                    score += 15
                elif overlap < 0.1:
                    score -= 15

        score = max(0, min(100, score))
        passed = score >= threshold

        reasons = []
        if refusal_count > 0:
            reasons.append(f"{refusal_count} refusal pattern(s)")
        if hedging_count > 0:
            reasons.append(f"{hedging_count} hedging indicator(s)")
        if completion_count > 0:
            reasons.append(f"{completion_count} completion indicator(s)")

        if not reasons:
            reason = "Response appears to address the task" if passed else "Response may not fully complete the task"
        else:
            reason = f"Task completion analysis: {', '.join(reasons)}"

        return EvalResult(
            metric="task_completion",
            score=round(score, 1),
            passed=passed,
            reason=reason,
        )

    def _heuristic_tool_correctness(
        self,
        tool_calls: Optional[List[dict]],
        expected_tool_calls: Optional[List[dict]],
        threshold: float,
    ) -> EvalResult:
        """Check if the agent called the expected tools."""
        if not expected_tool_calls:
            return EvalResult(
                metric="tool_correctness",
                score=50.0,
                passed=False,
                reason="No expected tool calls provided",
            )

        if not tool_calls:
            return EvalResult(
                metric="tool_correctness",
                score=0.0,
                passed=False,
                reason="Agent made no tool calls (expected {})".format(
                    ", ".join(t.get("name", "?") for t in expected_tool_calls)
                ),
                details={"expected": [t.get("name", t.get("tool")) for t in expected_tool_calls], "actual": []},
            )

        expected_names = [t.get("name", t.get("tool", "")).lower() for t in expected_tool_calls]
        actual_names = [t.get("name", t.get("tool", "")).lower() for t in tool_calls]

        # Score = fraction of expected tools that were called
        matched = sum(1 for name in expected_names if name in actual_names)
        score = (matched / len(expected_names)) * 100

        # Bonus: no extra unexpected tools
        unexpected = [n for n in actual_names if n not in expected_names]
        if unexpected:
            score = max(0, score - len(unexpected) * 10)

        score = min(100, score)
        passed = score >= threshold

        return EvalResult(
            metric="tool_correctness",
            score=round(score, 1),
            passed=passed,
            reason=f"Matched {matched}/{len(expected_names)} expected tools"
                   + (f" ({len(unexpected)} unexpected)" if unexpected else ""),
            details={
                "expected": expected_names,
                "actual": actual_names,
                "matched": matched,
                "unexpected": unexpected,
            },
        )

    def _heuristic_tool_args_accuracy(
        self,
        tool_calls: Optional[List[dict]],
        expected_tool_calls: Optional[List[dict]],
        threshold: float,
    ) -> EvalResult:
        """Check if tool call arguments are correct."""
        if not expected_tool_calls:
            return EvalResult(
                metric="tool_args_accuracy",
                score=50.0,
                passed=False,
                reason="No expected tool calls provided",
            )

        if not tool_calls:
            return EvalResult(
                metric="tool_args_accuracy",
                score=0.0,
                passed=False,
                reason="Agent made no tool calls to validate arguments",
            )

        total_args_checked = 0
        correct_args = 0
        details_list = []

        for expected_tc in expected_tool_calls:
            expected_name = expected_tc.get("name", expected_tc.get("tool", "")).lower()
            expected_args = expected_tc.get("args", {})

            if not expected_args:
                continue

            # Find matching actual tool call (best match: name + most matching args)
            actual_tc = None
            best_score = -1
            for tc in tool_calls:
                if tc.get("name", tc.get("tool", "")).lower() == expected_name:
                    # Score by how many expected args match
                    tc_args = tc.get("args", {})
                    if isinstance(tc_args, str):
                        try:
                            import json
                            tc_args = json.loads(tc_args)
                        except (json.JSONDecodeError, TypeError):
                            tc_args = {}
                    score = sum(1 for k, v in expected_args.items() if str(tc_args.get(k, "")).lower().strip() == str(v).lower().strip())
                    if score > best_score:
                        best_score = score
                        actual_tc = tc

            if actual_tc is None:
                total_args_checked += len(expected_args)
                details_list.append({"tool": expected_name, "status": "not_called"})
                continue

            actual_args = actual_tc.get("args", {})
            if isinstance(actual_args, str):
                try:
                    import json
                    actual_args = json.loads(actual_args)
                except (json.JSONDecodeError, TypeError):
                    actual_args = {}

            # Compare each expected argument
            for key, expected_val in expected_args.items():
                total_args_checked += 1
                actual_val = actual_args.get(key)

                if actual_val is not None:
                    # Flexible comparison: string match or value match
                    if str(actual_val).lower().strip() == str(expected_val).lower().strip():
                        correct_args += 1
                    elif str(expected_val).lower() in str(actual_val).lower():
                        correct_args += 0.5  # Partial match

            details_list.append({
                "tool": expected_name,
                "expected_args": expected_args,
                "actual_args": actual_args,
            })

        if total_args_checked == 0:
            return EvalResult(
                metric="tool_args_accuracy",
                score=100.0,
                passed=True,
                reason="No arguments to validate (tools have no expected args)",
            )

        score = (correct_args / total_args_checked) * 100
        score = min(100, score)
        passed = score >= threshold

        return EvalResult(
            metric="tool_args_accuracy",
            score=round(score, 1),
            passed=passed,
            reason=f"{correct_args:.0f}/{total_args_checked} tool arguments correct",
            details={"tools": details_list},
        )

    def _heuristic_tool_sequence(
        self,
        tool_calls: Optional[List[dict]],
        expected_tool_calls: Optional[List[dict]],
        threshold: float,
    ) -> EvalResult:
        """Check if tools were called in the correct order."""
        if not expected_tool_calls:
            return EvalResult(
                metric="tool_sequence",
                score=50.0,
                passed=False,
                reason="No expected tool calls provided",
            )

        if not tool_calls:
            return EvalResult(
                metric="tool_sequence",
                score=0.0,
                passed=False,
                reason="Agent made no tool calls to validate sequence",
            )

        expected_names = [t.get("name", t.get("tool", "")).lower() for t in expected_tool_calls]
        actual_names = [t.get("name", t.get("tool", "")).lower() for t in tool_calls]

        if len(expected_names) <= 1:
            # Single tool — sequence doesn't matter, just check presence
            if expected_names[0] in actual_names:
                return EvalResult(
                    metric="tool_sequence",
                    score=100.0,
                    passed=True,
                    reason="Single expected tool was called",
                )
            return EvalResult(
                metric="tool_sequence",
                score=0.0,
                passed=False,
                reason=f"Expected tool '{expected_names[0]}' was not called",
            )

        # Check longest common subsequence of expected tool names in actual
        # This measures how well the order is preserved
        def lcs_length(seq1, seq2):
            m, n = len(seq1), len(seq2)
            dp = [[0] * (n + 1) for _ in range(m + 1)]
            for i in range(1, m + 1):
                for j in range(1, n + 1):
                    if seq1[i-1] == seq2[j-1]:
                        dp[i][j] = dp[i-1][j-1] + 1
                    else:
                        dp[i][j] = max(dp[i-1][j], dp[i][j-1])
            return dp[m][n]

        lcs = lcs_length(expected_names, actual_names)
        score = (lcs / len(expected_names)) * 100
        score = min(100, score)
        passed = score >= threshold

        return EvalResult(
            metric="tool_sequence",
            score=round(score, 1),
            passed=passed,
            reason=f"{lcs}/{len(expected_names)} tools in correct order",
            details={
                "expected_sequence": expected_names,
                "actual_sequence": actual_names,
                "longest_common_subsequence": lcs,
            },
        )

    def _heuristic_coherence(
        self,
        output: str,
        conversation_history: Optional[List[dict]],
        threshold: float,
    ) -> EvalResult:
        """Check if the response is coherent with the conversation history."""
        if not conversation_history:
            return EvalResult(
                metric="coherence",
                score=50.0,
                passed=False,
                reason="No conversation history provided",
            )

        import re

        output_lower = output.lower()
        score = 80.0  # Start optimistic

        # Extract all previous assistant responses and user messages
        prev_assistant_outputs = []
        prev_user_inputs = []
        for turn in conversation_history:
            if turn.get("role") == "assistant":
                prev_assistant_outputs.append(turn.get("content", "").lower())
            elif turn.get("role") == "user":
                prev_user_inputs.append(turn.get("content", "").lower())

        if not prev_assistant_outputs:
            return EvalResult(
                metric="coherence",
                score=85.0,
                passed=85.0 >= threshold,
                reason="First turn in conversation — no prior responses to compare",
            )

        stop_words = {
            'the', 'a', 'an', 'is', 'are', 'was', 'were', 'and', 'or', 'but',
            'to', 'of', 'in', 'for', 'on', 'at', 'by', 'it', 'that', 'this',
            'with', 'from', 'as', 'be', 'been', 'have', 'has', 'had', 'do',
            'does', 'did', 'will', 'would', 'can', 'could', 'i', 'you', 'we',
        }

        # Check 1: Entity consistency — extract key entities from history,
        # verify current response doesn't contradict them
        all_prev_text = " ".join(prev_assistant_outputs)
        prev_words = set(all_prev_text.split()) - stop_words
        output_words = set(output_lower.split()) - stop_words

        # Topical overlap: current response should share some vocabulary with history
        if prev_words:
            topic_overlap = len(prev_words & output_words) / max(len(prev_words), 1)
            if topic_overlap > 0.1:
                score += 10
            elif topic_overlap < 0.02:
                score -= 15  # Completely off-topic

        # Check 2: Contradiction detection (simple heuristic)
        # Look for direct negation of previous statements
        negation_pairs = [
            (r'\byes\b', r'\bno\b'), (r'\btrue\b', r'\bfalse\b'),
            (r'\bcorrect\b', r'\bincorrect\b'), (r'\bcan\b', r'\bcannot\b'),
        ]
        contradiction_count = 0
        for affirm, negate in negation_pairs:
            # If history affirms and current negates (or vice versa)
            history_affirms = re.search(affirm, all_prev_text)
            current_negates = re.search(negate, output_lower)
            if history_affirms and current_negates:
                contradiction_count += 1

        score -= contradiction_count * 10

        # Check 3: Response acknowledges conversation context
        context_refs = [
            r'\bas\s+(i|we)\s+(?:mentioned|said|discussed)\b',
            r'\bearlier\b', r'\bpreviously\b', r'\byou\s+(?:asked|mentioned|said)\b',
        ]
        has_context_ref = any(re.search(p, output_lower) for p in context_refs)
        if has_context_ref:
            score += 5

        score = max(0, min(100, score))
        passed = score >= threshold

        return EvalResult(
            metric="coherence",
            score=round(score, 1),
            passed=passed,
            reason=f"Response {'maintains' if passed else 'may not maintain'} consistency with conversation"
                   + (f" ({contradiction_count} potential contradiction(s))" if contradiction_count else ""),
        )

    def _heuristic_context_retention(
        self,
        output: str,
        conversation_history: Optional[List[dict]],
        threshold: float,
    ) -> EvalResult:
        """Check if the agent remembers information from earlier conversation turns."""
        if not conversation_history:
            return EvalResult(
                metric="context_retention",
                score=50.0,
                passed=False,
                reason="No conversation history provided",
            )

        import re

        output_lower = output.lower()

        # Extract facts/entities mentioned in earlier turns
        # Focus on: names, numbers, locations, dates, specific terms
        entity_patterns = [
            r'\b[A-Z][a-z]+(?:\s[A-Z][a-z]+)+\b',  # Proper nouns (e.g., "John Smith")
            r'\b\d+(?:\.\d+)?%?\b',  # Numbers/percentages
            r'\$[\d,]+(?:\.\d+)?\b',  # Dollar amounts
            r'\b(?:January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{1,2}\b',  # Dates
        ]

        # Also track key content words from user turns
        stop_words = {
            'the', 'a', 'an', 'is', 'are', 'was', 'were', 'and', 'or', 'but',
            'to', 'of', 'in', 'for', 'on', 'at', 'by', 'it', 'that', 'this',
            'with', 'from', 'as', 'be', 'been', 'have', 'has', 'had', 'do',
            'does', 'did', 'will', 'would', 'can', 'could', 'may', 'i', 'you',
            'what', 'how', 'why', 'when', 'where', 'who', 'my', 'your', 'me',
            'we', 'they', 'he', 'she', 'its', 'our', 'their', 'am', 'tell',
            'hi', 'hello', 'please', 'thank', 'thanks', 'okay', 'ok',
        }

        # Collect key facts from earlier turns (not the most recent user turn)
        earlier_facts = set()
        all_content = []
        for turn in conversation_history[:-1]:  # Exclude last turn (current question)
            content = turn.get("content", "")
            all_content.append(content)
            # Extract entities
            for pattern in entity_patterns:
                matches = re.findall(pattern, content)
                earlier_facts.update(m.lower() for m in matches)
            # Extract content words
            words = set(content.lower().split()) - stop_words
            earlier_facts.update(w for w in words if len(w) > 3)

        if not earlier_facts:
            return EvalResult(
                metric="context_retention",
                score=80.0,
                passed=80.0 >= threshold,
                reason="No specific facts to track in conversation history",
            )

        # Check how many earlier facts appear in the current response
        retained_facts = set()
        for fact in earlier_facts:
            if fact in output_lower:
                retained_facts.add(fact)

        retention_ratio = len(retained_facts) / max(len(earlier_facts), 1)

        # Scale: even 10% retention of specific facts is decent
        # because not every fact needs to be repeated
        if retention_ratio >= 0.2:
            score = 90.0
        elif retention_ratio >= 0.1:
            score = 80.0
        elif retention_ratio >= 0.05:
            score = 70.0
        elif retention_ratio > 0:
            score = 60.0
        else:
            score = 40.0

        passed = score >= threshold

        return EvalResult(
            metric="context_retention",
            score=round(score, 1),
            passed=passed,
            reason=f"Agent {'retains' if passed else 'may not retain'} earlier context ({len(retained_facts)} of {len(earlier_facts)} tracked facts referenced)",
            details={
                "tracked_facts": len(earlier_facts),
                "retained_facts": len(retained_facts),
                "retention_ratio": round(retention_ratio, 3),
                "examples": list(retained_facts)[:5],
            },
        )

    def _heuristic_memory_retention(
        self,
        input_text: str,
        output: str,
        conversation_history: Optional[List[dict]],
        threshold: float,
    ) -> EvalResult:
        """Check if the agent remembered constraints and preferences from earlier turns.

        Unlike context_retention (which checks if facts are echoed back), this metric
        checks if the agent's behavior RESPECTS earlier constraints. For example:
        - User said "I'm vegetarian" → agent shouldn't suggest meat dishes
        - User said "My name is Rahul" → agent should use the name
        - User said "budget is $500" → agent shouldn't suggest expensive options

        This is the MEMORY aspect of agentic evaluation — did the agent USE
        what it learned, not just parrot it back.

        Pillar: Robustness (memory retention under multi-turn pressure)
        """
        if not conversation_history:
            return EvalResult(
                metric="memory_retention",
                score=50.0,
                passed=False,
                reason="No conversation history provided — cannot evaluate memory",
                details={"pillar": "Robustness", "why": "Multi-turn history required"},
            )

        import re

        output_lower = output.lower()
        input_lower = input_text.lower()

        # Extract explicit constraints from earlier user turns
        constraints = []
        user_name = None
        preferences = []

        for turn in conversation_history:
            if turn.get("role") != "user":
                continue
            content = turn.get("content", "")
            cl = content.lower()

            # Name detection
            for pattern in [r"my name is (\w+)", r"i'?m (\w+)", r"call me (\w+)"]:
                m = re.search(pattern, cl)
                if m and len(m.group(1)) > 1:
                    user_name = m.group(1).capitalize()

            # Preference / constraint detection
            for pattern in [
                r"i (?:like|love|enjoy|prefer) ([^.!?]+)",
                r"i am (\w+)",
                r"i'?m (\w+)",
                r"my budget is ([^.!?]+)",
                r"i (?:don'?t|do not) (?:like|want|eat) ([^.!?]+)",
                r"i'?m allergic to ([^.!?]+)",
            ]:
                m = re.search(pattern, cl)
                if m:
                    pref_text = m.group(1).strip()
                    if len(pref_text) > 2:
                        preferences.append(pref_text)

            # Dietary constraints
            for diet in ["vegetarian", "vegan", "gluten-free", "halal", "kosher"]:
                if diet in cl:
                    constraints.append(f"dietary:{diet}")

        checks_passed = 0
        total_checks = 0
        check_details = []

        # Check 1: Name usage — if user gave name, does the agent use it?
        if user_name:
            total_checks += 1
            if user_name.lower() in output_lower:
                checks_passed += 1
                check_details.append({"check": "name_recall", "passed": True, "expected": user_name})
            else:
                check_details.append({"check": "name_recall", "passed": False, "expected": user_name, "why": f"Agent did not use the name '{user_name}' in response"})

        # Check 2: Preference respect — if user stated preferences, are they reflected?
        if preferences:
            total_checks += 1
            pref_keywords = set()
            for pref in preferences:
                pref_keywords.update(pref.lower().split())
            matched_prefs = sum(1 for kw in pref_keywords if kw in output_lower and len(kw) > 3)
            if matched_prefs > 0:
                checks_passed += 1
                check_details.append({"check": "preference_respect", "passed": True, "preferences": preferences})
            else:
                check_details.append({"check": "preference_respect", "passed": False, "preferences": preferences, "why": "Agent response doesn't reference user's stated preferences"})

        # Check 3: Constraint adherence — check for violations
        if constraints:
            total_checks += 1
            violation_found = False
            for constraint in constraints:
                if constraint.startswith("dietary:"):
                    diet = constraint.split(":")[1]
                    # Check if agent suggested non-compliant items
                    violations = {
                        "vegetarian": ["chicken", "beef", "pork", "lamb", "steak", "bacon", "meat", "fish"],
                        "vegan": ["cheese", "milk", "butter", "egg", "cream", "honey", "chicken", "beef", "meat"],
                        "gluten-free": ["bread", "pasta", "wheat", "flour", "noodles"],
                    }
                    bad_items = violations.get(diet, [])
                    found_violations = [item for item in bad_items if item in output_lower]
                    if found_violations:
                        violation_found = True
                        check_details.append({"check": "constraint_adherence", "passed": False, "constraint": diet, "violations": found_violations, "why": f"Agent suggested {', '.join(found_violations)} despite user being {diet}"})
            if not violation_found:
                checks_passed += 1
                check_details.append({"check": "constraint_adherence", "passed": True, "constraints": constraints})

        # Check 4: Topic continuity — is the response about the right topic?
        if len(conversation_history) >= 2:
            total_checks += 1
            # Get topic words from recent turns
            recent_topics = set()
            for turn in conversation_history[-3:]:
                words = set(turn.get("content", "").lower().split())
                recent_topics.update(w for w in words if len(w) > 4)
            topic_overlap = sum(1 for w in recent_topics if w in output_lower)
            if topic_overlap >= 2:
                checks_passed += 1
                check_details.append({"check": "topic_continuity", "passed": True, "overlap_count": topic_overlap})
            else:
                check_details.append({"check": "topic_continuity", "passed": False, "why": "Response may not be continuing the conversation topic"})

        if total_checks == 0:
            return EvalResult(
                metric="memory_retention",
                score=80.0,
                passed=80.0 >= threshold,
                reason="No specific memory constraints to validate in conversation history",
                details={"pillar": "Robustness", "checks": check_details},
            )

        score = (checks_passed / total_checks) * 100
        passed = score >= threshold

        reason_parts = []
        for cd in check_details:
            status = "PASS" if cd["passed"] else "FAIL"
            reason_parts.append(f"{cd['check']}: {status}")
            if not cd["passed"] and cd.get("why"):
                reason_parts[-1] += f" ({cd['why']})"

        reason = f"Memory retention: {checks_passed}/{total_checks} checks passed. {'; '.join(reason_parts)}"

        return EvalResult(
            metric="memory_retention",
            score=round(score, 1),
            passed=passed,
            reason=reason,
            details={
                "pillar": "Robustness",
                "total_checks": total_checks,
                "checks_passed": checks_passed,
                "checks": check_details,
                "user_name": user_name,
                "preferences": preferences,
                "constraints": constraints,
            },
        )

    def _heuristic_trajectory_score(
        self,
        tool_calls: Optional[List[dict]],
        expected_tool_calls: Optional[List[dict]],
        threshold: float,
        trajectory_spec: Optional[dict] = None,
    ) -> EvalResult:
        """Compare actual tool-call trajectory against expected trajectory.

        Supports three match types (inspired by Google ADK):
        - EXACT: Perfect match, same order, same length
        - IN_ORDER: Expected calls appear as a subsequence in actual calls
        - ANY_ORDER: Expected calls appear anywhere in actual calls
        """
        # Build effective spec from trajectory or fallback to expected_tool_calls
        if trajectory_spec:
            match_type = trajectory_spec.get("match_type", "IN_ORDER").upper()
            expected = trajectory_spec.get("expected_calls", expected_tool_calls or [])
            check_args = trajectory_spec.get("check_args", True)
        elif expected_tool_calls:
            match_type = "ANY_ORDER"
            expected = expected_tool_calls
            check_args = False
        else:
            return EvalResult(
                metric="trajectory_score",
                score=50.0,
                passed=False,
                reason="No expected trajectory defined",
            )

        if not expected:
            return EvalResult(
                metric="trajectory_score",
                score=100.0,
                passed=True,
                reason="No expected tool calls to check",
                details={"match_type": match_type, "per_call_match": [], "actual_calls": [], "expected_calls": []},
            )

        actual = tool_calls or []

        # Normalize tool call names
        def normalize_call(call):
            name = call.get("name") or call.get("tool") or ""
            args = call.get("args") or call.get("arguments") or {}
            return {"name": name.lower().strip(), "args": args}

        actual_norm = [normalize_call(c) for c in actual]
        expected_norm = [normalize_call(c) for c in expected]

        def calls_match(a, e):
            if a["name"] != e["name"]:
                return False
            if check_args and e["args"]:
                for key, val in e["args"].items():
                    if str(a["args"].get(key, "")).lower() != str(val).lower():
                        return False
            return True

        per_call_match = []
        matched = False
        details_text = ""

        if match_type == "EXACT":
            if len(actual_norm) != len(expected_norm):
                details_text = f"Length mismatch: expected {len(expected_norm)} calls, got {len(actual_norm)}"
                per_call_match = [
                    {
                        "expected": expected_norm[i] if i < len(expected_norm) else None,
                        "actual": actual_norm[i] if i < len(actual_norm) else None,
                        "matched": i < len(actual_norm) and i < len(expected_norm) and calls_match(actual_norm[i], expected_norm[i]),
                    }
                    for i in range(max(len(expected_norm), len(actual_norm)))
                ]
            else:
                all_match = True
                for i, (a, e) in enumerate(zip(actual_norm, expected_norm)):
                    m = calls_match(a, e)
                    per_call_match.append({"expected": e, "actual": a, "matched": m})
                    if not m:
                        all_match = False
                matched = all_match
                details_text = f"{'All' if matched else 'Not all'} {len(expected_norm)} calls match exactly"

        elif match_type == "IN_ORDER":
            # Subsequence matching
            expected_idx = 0
            for a in actual_norm:
                if expected_idx < len(expected_norm) and calls_match(a, expected_norm[expected_idx]):
                    per_call_match.append({"expected": expected_norm[expected_idx], "actual": a, "matched": True})
                    expected_idx += 1
                else:
                    per_call_match.append({"expected": None, "actual": a, "matched": False, "extra": True})

            # Add missing expected calls
            for i in range(expected_idx, len(expected_norm)):
                per_call_match.append({"expected": expected_norm[i], "actual": None, "matched": False, "missing": True})

            matched = expected_idx == len(expected_norm)
            found = expected_idx
            details_text = f"{found}/{len(expected_norm)} expected calls found in order"

        elif match_type == "ANY_ORDER":
            remaining_actual = list(actual_norm)
            found_count = 0
            missing = []
            for e in expected_norm:
                found = False
                for i, a in enumerate(remaining_actual):
                    if calls_match(a, e):
                        per_call_match.append({"expected": e, "actual": a, "matched": True})
                        remaining_actual.pop(i)
                        found = True
                        found_count += 1
                        break
                if not found:
                    per_call_match.append({"expected": e, "actual": None, "matched": False, "missing": True})
                    missing.append(e["name"])

            # Mark remaining actual as extras
            for a in remaining_actual:
                per_call_match.append({"expected": None, "actual": a, "matched": False, "extra": True})

            matched = found_count == len(expected_norm)
            details_text = f"{found_count}/{len(expected_norm)} expected calls found (any order)"
            if missing:
                details_text += f". Missing: {', '.join(missing)}"

        score = 100.0 if matched else 0.0
        passed = score >= threshold

        return EvalResult(
            metric="trajectory_score",
            score=score,
            passed=passed,
            reason=f"Trajectory {'matches' if matched else 'does not match'} ({match_type}): {details_text}",
            details={
                "match_type": match_type,
                "matched": matched,
                "expected_calls": [{"name": e["name"], "args": e["args"]} for e in expected_norm],
                "actual_calls": [{"name": a["name"], "args": a["args"]} for a in actual_norm],
                "per_call_match": per_call_match,
            },
        )

    def _heuristic_rubric_score(
        self,
        output: str,
        rubrics: Optional[List[str]],
        threshold: float,
    ) -> EvalResult:
        """Score response against custom rubric criteria via keyword matching."""
        if not rubrics:
            return EvalResult(
                metric="rubric_score",
                score=50.0,
                passed=False,
                reason="No rubrics defined",
            )

        stop_words = {
            'the', 'a', 'an', 'is', 'are', 'was', 'were', 'be', 'been', 'being',
            'have', 'has', 'had', 'do', 'does', 'did', 'will', 'would', 'could',
            'should', 'may', 'might', 'shall', 'can', 'need', 'dare', 'ought',
            'used', 'to', 'of', 'in', 'for', 'on', 'with', 'at', 'by', 'from',
            'as', 'into', 'through', 'during', 'before', 'after', 'above', 'below',
            'and', 'but', 'or', 'nor', 'not', 'so', 'yet', 'both', 'either',
            'neither', 'each', 'every', 'all', 'any', 'few', 'more', 'most',
            'other', 'some', 'such', 'no', 'only', 'own', 'same', 'than', 'too',
            'very', 'just', 'because', 'if', 'when', 'where', 'how', 'what',
            'which', 'who', 'whom', 'this', 'that', 'these', 'those', 'it', 'its',
            'includes', 'contains', 'mentions', 'about', 'info', 'information',
            'response', 'agent',
        }

        output_lower = output.lower()
        rubric_results = []
        matched_count = 0

        for rubric in rubrics:
            # Extract significant keywords from rubric
            words = rubric.lower().split()
            keywords = [w.strip('.,;:!?()[]"\'') for w in words if w.strip('.,;:!?()[]"\'') not in stop_words and len(w.strip('.,;:!?()[]"\'')) > 2]

            if not keywords:
                rubric_results.append({"rubric": rubric, "matched": True, "keywords": [], "found": []})
                matched_count += 1
                continue

            # Check keyword presence
            found = [kw for kw in keywords if kw in output_lower]
            match_ratio = len(found) / len(keywords)

            # Majority match = pass
            is_matched = match_ratio >= 0.5
            if is_matched:
                matched_count += 1

            rubric_results.append({
                "rubric": rubric,
                "matched": is_matched,
                "keywords": keywords,
                "found": found,
            })

        score = (matched_count / len(rubrics)) * 100 if rubrics else 0
        passed = score >= threshold

        return EvalResult(
            metric="rubric_score",
            score=round(score, 1),
            passed=passed,
            reason=f"{matched_count}/{len(rubrics)} rubrics satisfied",
            details={
                "rubric_results": rubric_results,
                "matched_count": matched_count,
                "total_rubrics": len(rubrics),
            },
        )

    # ── Agentic Trace-Based Metrics ──────────────────────────────────────

    def _heuristic_node_success_rate(
        self,
        trace: Optional[List[dict]],
        threshold: float,
    ) -> EvalResult:
        """Check if all pipeline nodes completed without errors.

        Inspects the trace to see which nodes ran successfully vs errored.
        This evaluates the agent's INTERNAL execution, not just its output.
        """
        if not trace:
            return EvalResult(
                metric="node_success_rate", score=0.0, passed=False,
                reason="No trace data available from agent",
            )

        total = len(trace)
        succeeded = sum(1 for t in trace if t.get("result", "").startswith("ok") or "error" not in t)
        errored = [t for t in trace if t.get("error") or (t.get("result", "").startswith("error"))]

        score = (succeeded / total) * 100 if total > 0 else 0
        passed = score >= threshold

        node_list = ", ".join(t.get("node", "?") for t in trace)
        error_list = ", ".join(f"{t.get('node', '?')}: {t.get('error', t.get('result', '?'))}" for t in errored)

        reason = f"{succeeded}/{total} nodes completed successfully ({node_list})"
        if errored:
            reason += f". Errors: {error_list}"

        return EvalResult(
            metric="node_success_rate",
            score=round(score, 1),
            passed=passed,
            reason=reason,
            details={
                "total_nodes": total,
                "succeeded": succeeded,
                "failed": len(errored),
                "nodes": [{"node": t.get("node"), "result": t.get("result"), "duration_ms": t.get("duration_ms")} for t in trace],
                "errors": [{"node": t.get("node"), "error": t.get("error", t.get("result"))} for t in errored],
            },
        )

    # Node names that are expected to dominate latency because they
    # call external APIs, sub-agents, or perform LLM inference.
    # For these nodes the bottleneck threshold is raised so the agent
    # is not penalised for naturally slow operations.
    _EXPECTED_HEAVY_NODES = {
        # Orchestrator / tool-call nodes
        "call_agents", "call_tools", "execute_tools", "execute",
        "route", "route_to_agent", "invoke_tools", "run_tools",
        # LLM generation nodes (RAG, conversational, etc.)
        "generate", "llm", "llm_call", "answer", "respond",
        "synthesize", "summarize", "chat", "completion",
    }

    def _heuristic_step_latency(
        self,
        trace: Optional[List[dict]],
        threshold: float,
        tool_calls: Optional[List[dict]] = None,
    ) -> EvalResult:
        """Check if any single processing step dominates the total latency.

        A healthy agent distributes work across steps.  For normal agents, a
        node taking >60% of total time flags a bottleneck.  For orchestrators
        (detected via tool_calls or known node names) the threshold is raised
        to 90% because the "call" node is *expected* to be slow — it fans
        out to external sub-agents over the network.
        """
        if not trace:
            return EvalResult(
                metric="step_latency", score=0.0, passed=False,
                reason="No trace data available from agent",
            )

        durations = []
        for t in trace:
            ms = t.get("duration_ms", 0)
            durations.append({"node": t.get("node", "?"), "ms": ms})

        total_ms = sum(d["ms"] for d in durations)
        if total_ms == 0:
            return EvalResult(
                metric="step_latency", score=100.0, passed=True,
                reason="All steps completed instantly",
                details={"steps": durations, "total_ms": 0},
            )

        # Detect orchestrator pattern: tool_calls present or heavy-node names
        node_names = {d["node"].lower() for d in durations}
        is_orchestrator = bool(tool_calls) or bool(node_names & self._EXPECTED_HEAVY_NODES)

        # Bottleneck threshold: 95% for orchestrators (sub-agent fan-out is
        # inherently slow), 60% for normal agents.
        bottleneck_pct = 95 if is_orchestrator else 60

        max_step = max(durations, key=lambda d: d["ms"])
        max_pct = (max_step["ms"] / total_ms) * 100

        # If the dominant node is a known heavy node (fan-out / tool call),
        # its dominance is expected — score 100 and just report the split.
        max_node_lower = max_step["node"].lower()
        if is_orchestrator and max_node_lower in self._EXPECTED_HEAVY_NODES:
            score = 100.0
        elif max_pct <= bottleneck_pct:
            score = 100.0
        else:
            # Scale: threshold% -> 100, 100% -> 40
            score = max(0, 100 - (max_pct - bottleneck_pct) * (60 / (100 - bottleneck_pct)))

        passed = score >= threshold

        step_breakdown = ", ".join(f"{d['node']}={d['ms']}ms ({d['ms']*100//total_ms}%)" for d in durations)
        reason = f"Total: {total_ms}ms across {len(durations)} steps. {step_breakdown}"
        if max_pct > bottleneck_pct:
            reason += f". Bottleneck: {max_step['node']} uses {max_pct:.0f}% of total time"

        return EvalResult(
            metric="step_latency",
            score=round(score, 1),
            passed=passed,
            reason=reason,
            details={
                "total_ms": total_ms,
                "steps": durations,
                "bottleneck": max_step["node"] if max_pct > 60 else None,
                "max_step_pct": round(max_pct, 1),
            },
        )

    def _heuristic_agent_reasoning(
        self,
        trace: Optional[List[dict]],
        tool_calls: Optional[List[dict]],
        threshold: float,
    ) -> EvalResult:
        """Evaluate whether the agent followed a logical decision-making process.

        Checks:
        1. Did the agent execute multiple steps? (not a single black-box call)
        2. Did it actually produce output? (not an empty pipeline)
        3. Did it use tools/sub-agents during execution?
        4. Was the execution multi-step (planning → execution → synthesis)?

        This is the core "agentic" metric — it distinguishes a real agent
        from a simple prompt-in/text-out wrapper.
        """
        if not trace:
            return EvalResult(
                metric="agent_reasoning", score=0.0, passed=False,
                reason="No trace data — agent may not be using traced pipeline",
            )

        checks_passed = 0
        total_checks = 4
        details = {}

        # Check 1: Multi-step execution (not a single-node agent)
        node_count = len(trace)
        is_multi_step = node_count >= 2
        if is_multi_step:
            checks_passed += 1
        details["multi_step"] = {"passed": is_multi_step, "node_count": node_count}

        # Check 2: All nodes produced results (not empty pipeline)
        all_completed = all(t.get("result", "").startswith("ok") or "error" not in t for t in trace)
        if all_completed:
            checks_passed += 1
        details["all_completed"] = {"passed": all_completed}

        # Check 3: Agent used tools/sub-agents (not just text processing)
        has_tool_use = bool(tool_calls and len(tool_calls) > 0)
        if has_tool_use:
            checks_passed += 1
        details["tool_use"] = {"passed": has_tool_use, "tool_count": len(tool_calls or [])}

        # Check 4: Evidence of structured reasoning (plan→execute→synthesize pattern)
        node_names = [t.get("node", "").lower() for t in trace]
        reasoning_patterns = [
            ["plan", "call", "synth"],      # orchestrator pattern
            ["plan", "execute", "format"],   # general agent pattern
            ["parse", "geocode", "forecast", "format"],  # weather pattern
            ["extract", "search", "summarize", "format"],  # wiki pattern
            ["retrieve", "generate"],        # RAG pattern
            ["load", "generate", "save"],    # conversational pattern
            ["detect", "execute"],           # calculator pattern
        ]

        has_reasoning_pattern = False
        matched_pattern = None
        for pattern in reasoning_patterns:
            if len(node_names) >= len(pattern):
                # Check if node names contain keywords from pattern
                if all(any(p in name for name in node_names) for p in pattern):
                    has_reasoning_pattern = True
                    matched_pattern = pattern
                    break

        if has_reasoning_pattern:
            checks_passed += 1
        details["reasoning_pattern"] = {
            "passed": has_reasoning_pattern,
            "matched": matched_pattern,
            "actual_nodes": node_names,
        }

        score = (checks_passed / total_checks) * 100
        passed = score >= threshold

        node_list = " → ".join(t.get("node", "?") for t in trace)
        reason = f"Agent reasoning: {checks_passed}/{total_checks} checks passed. Pipeline: {node_list}"
        if matched_pattern:
            reason += f". Matched pattern: {' → '.join(matched_pattern)}"

        return EvalResult(
            metric="agent_reasoning",
            score=round(score, 1),
            passed=passed,
            reason=reason,
            details=details,
        )

    # ── Process-level metrics (enabled by LangSmith tracing) ──

    def _heuristic_tool_usage_correctness(
        self,
        trace: Optional[List[dict]],
        tool_calls: Optional[List[dict]],
        expected_tool_calls: Optional[List[dict]],
        threshold: float,
        expected_behavior: Optional[dict] = None,
    ) -> EvalResult:
        """Check if the agent used the right tools based on trace data.

        Pillar: Tool Safety — Did the agent invoke the right tools for the task?

        When expected_behavior.tools_used is provided (e.g. ["WikiAgent", "WeatherAgent"]),
        it takes priority over expected_tool_calls for matching.
        """
        if not trace:
            return EvalResult(
                metric="tool_usage_correctness", score=0, passed=False,
                reason="No trace data — cannot evaluate tool usage",
                details={"pillar": "Tool Safety", "why": "Agent did not return execution trace"},
            )

        # Collect all node names and tool names from the trace
        used_nodes = [t.get("node", "") for t in trace]
        used_tools = set()
        for t in trace:
            node = t.get("node", "")
            if node:
                used_tools.add(node.lower())
        if tool_calls:
            for tc in tool_calls:
                name = tc.get("name", tc.get("tool", ""))
                if name:
                    used_tools.add(name.lower())

        # Priority 1: expected_behavior.tools_used (agent-aware YAML format)
        eb_tools = (expected_behavior or {}).get("tools_used")
        if eb_tools and isinstance(eb_tools, list):
            expected_names = {t.lower() for t in eb_tools}
            matched = set()
            for expected in expected_names:
                # Fuzzy match: "WeatherAgent" matches "weather_agent" or "weather"
                exp_parts = expected.replace("_", "").replace("-", "").replace("agent", "")
                for used in used_tools:
                    used_parts = used.replace("_", "").replace("-", "").replace("agent", "")
                    if exp_parts in used_parts or used_parts in exp_parts or expected in used or used in expected:
                        matched.add(expected)
                        break
            score = (len(matched) / len(expected_names)) * 100 if expected_names else 80.0
            missing = expected_names - matched
            reason = f"Tool Safety: {len(matched)}/{len(expected_names)} expected tools used."
            if missing:
                reason += f" Missing: {', '.join(missing)}."
            reason += f" Actual tools: {' → '.join(used_nodes)}"
            extra_tools = used_tools - {m.lower() for m in matched} - {"plan_route", "synthesize", "call_agents"}
            if extra_tools:
                reason += f". Unexpected extra: {', '.join(extra_tools)}"
            details = {
                "pillar": "Tool Safety",
                "expected_tools": list(expected_names),
                "matched": list(matched),
                "missing": list(missing),
                "actual_nodes": used_nodes,
            }

        # Priority 2: expected_tool_calls (legacy format)
        elif expected_tool_calls:
            expected_names = {tc.get("name", tc.get("tool", "")).lower() for tc in expected_tool_calls if tc.get("name") or tc.get("tool")}
            if not expected_names:
                score = 80.0
                reason = f"Tools used: {', '.join(used_nodes)}. No specific expected tools defined."
                details = {"pillar": "Tool Safety", "actual_nodes": used_nodes}
            else:
                matched = expected_names & used_tools
                score = (len(matched) / len(expected_names)) * 100
                missing = expected_names - used_tools
                reason = f"Tool Safety: Matched {len(matched)}/{len(expected_names)} expected tools."
                if missing:
                    reason += f" Missing: {', '.join(missing)}"
                details = {
                    "pillar": "Tool Safety",
                    "expected": list(expected_names),
                    "matched": list(matched),
                    "missing": list(missing),
                    "actual_nodes": used_nodes,
                }
        else:
            # No expected tools — just verify agent did some processing
            score = 80.0 if len(used_nodes) >= 2 else 50.0
            reason = f"Agent executed {len(used_nodes)} nodes: {' → '.join(used_nodes)}"
            details = {"pillar": "Tool Safety", "actual_nodes": used_nodes, "why": "No expected tools defined — scoring on execution presence"}

        return EvalResult(
            metric="tool_usage_correctness",
            score=round(min(score, 100), 1),
            passed=score >= threshold,
            reason=reason,
            details=details,
        )

    def _heuristic_tool_order_correctness(
        self,
        trace: Optional[List[dict]],
        tool_calls: Optional[List[dict]],
        expected_tool_calls: Optional[List[dict]],
        threshold: float,
    ) -> EvalResult:
        """Check if tools/nodes were invoked in a logical order.

        Compares actual tool_calls against expected_tool_calls when both exist.
        Falls back to trace node order validation when no expected tools given.
        """
        if not trace and not tool_calls:
            return EvalResult(metric="tool_order_correctness", score=0, passed=False, reason="No trace or tool call data")

        nodes = [t.get("node", "") for t in trace] if trace else []

        # Build the actual ordered list: prefer tool_calls, fall back to trace nodes
        if tool_calls:
            actual_order = [tc.get("name", tc.get("tool", "")).lower() for tc in tool_calls]
        else:
            actual_order = [n.lower() for n in nodes]

        # Strategy 1: Compare actual order against expected_tool_calls
        if expected_tool_calls and len(expected_tool_calls) > 1:
            expected_order = [tc.get("name", tc.get("tool", "")).lower() for tc in expected_tool_calls]

            # Check if expected appears as a subsequence of actual
            ei = 0
            for actual_item in actual_order:
                if ei < len(expected_order) and actual_item == expected_order[ei]:
                    ei += 1
            order_match = ei / len(expected_order) if expected_order else 1.0
            score = order_match * 100

            actual_display = " → ".join(actual_order) if actual_order else "(none)"
            expected_display = " → ".join(expected_order)
            reason = f"Tool order match: {ei}/{len(expected_order)}. Expected: {expected_display}. Actual: {actual_display}"

        # Strategy 2: No expected tools — validate trace order is clean
        elif nodes:
            errors_before_end = 0
            for i, t in enumerate(trace):
                if t.get("result", "ok") != "ok" and i < len(trace) - 1:
                    errors_before_end += 1

            unique_count = len(set(nodes))
            repeat_penalty = max(0, (len(nodes) - unique_count) * 5)
            error_penalty = errors_before_end * 10
            score = max(0, 100 - repeat_penalty - error_penalty)
            reason = f"Execution order: {' → '.join(nodes)}. {len(nodes) - unique_count} repeated, {errors_before_end} mid-errors."

        else:
            score = 0
            reason = "No tool calls or trace nodes to evaluate order"

        return EvalResult(
            metric="tool_order_correctness",
            score=round(min(score, 100), 1),
            passed=score >= threshold,
            reason=reason,
        )

    def _heuristic_failure_recovery(
        self,
        trace: Optional[List[dict]],
        threshold: float,
        expected_behavior: Optional[dict] = None,
    ) -> EvalResult:
        """Check if the agent recovered from errors during execution.

        Pillar: Robustness — Did the agent recover gracefully from failures?

        When expected_behavior.must_recover is True, the test EXPECTS errors to
        occur. A perfect score requires both error occurrence AND recovery.
        """
        if not trace:
            return EvalResult(
                metric="failure_recovery", score=0, passed=False,
                reason="No trace data — cannot evaluate failure recovery",
                details={"pillar": "Robustness", "why": "No execution trace available"},
            )

        must_recover = (expected_behavior or {}).get("must_recover", False)

        errors = [t for t in trace if t.get("result", "ok") != "ok" or t.get("error")]
        total_nodes = len(trace)
        error_count = len(errors)

        if error_count == 0:
            if must_recover:
                # Test expected errors but none occurred — might be too easy
                return EvalResult(
                    metric="failure_recovery",
                    score=70.0,
                    passed=70.0 >= threshold,
                    reason=f"Robustness: Test expected failure scenarios but agent had no errors (all {total_nodes} nodes OK). Cannot confirm recovery ability.",
                    details={"pillar": "Robustness", "must_recover": True, "errors": 0, "why": "No errors occurred to test recovery"},
                )
            return EvalResult(
                metric="failure_recovery",
                score=100.0,
                passed=True,
                reason=f"Robustness: All {total_nodes} nodes completed successfully — no recovery needed",
                details={"pillar": "Robustness", "errors": 0, "total_nodes": total_nodes},
            )

        # Check if agent continued execution after errors (recovery)
        last_error_idx = -1
        for i, t in enumerate(trace):
            if t.get("result", "ok") != "ok" or t.get("error"):
                last_error_idx = i

        nodes_after_error = total_nodes - 1 - last_error_idx
        recovered = nodes_after_error > 0

        # Did agent produce output despite errors?
        last_node = trace[-1] if trace else {}
        final_ok = last_node.get("result", "ok") == "ok"

        error_nodes = [e.get("node", "?") for e in errors]

        if recovered and final_ok:
            score = max(60.0, 100 - error_count * 15)
            reason = f"Robustness: Agent recovered from {error_count} error(s) and completed successfully"
            if must_recover:
                reason += " (recovery was expected and confirmed)"
        elif recovered:
            score = max(40.0, 80 - error_count * 15)
            reason = f"Robustness: Agent attempted recovery from {error_count} error(s) but final status unclear"
        else:
            score = max(10.0, 30 - error_count * 10)
            reason = f"Robustness: Agent failed at node '{errors[-1].get('node', '?')}' with no recovery"
            if must_recover:
                reason += " — CRITICAL: recovery was expected but agent did not recover"

        reason += f". Failed nodes: {', '.join(error_nodes)}"

        return EvalResult(
            metric="failure_recovery",
            score=round(score, 1),
            passed=score >= threshold,
            reason=reason,
            details={
                "pillar": "Robustness",
                "must_recover": must_recover,
                "errors": error_count,
                "recovered": recovered,
                "final_ok": final_ok,
                "error_nodes": error_nodes,
                "nodes_after_error": nodes_after_error,
            },
        )

    def _heuristic_step_count_limit(
        self,
        trace: Optional[List[dict]],
        threshold: float,
        max_steps: int = 15,
        expected_behavior: Optional[dict] = None,
    ) -> EvalResult:
        """Check if the agent completed within a reasonable number of steps.

        Pillar: Robustness — Did the agent loop or over-think?

        When expected_behavior.max_steps is set, it overrides the default limit.
        Detects runaway agents that loop infinitely or take excessive steps.
        """
        if not trace:
            return EvalResult(
                metric="step_count_limit", score=0, passed=False,
                reason="No trace data — cannot evaluate step count",
                details={"pillar": "Robustness", "why": "No execution trace available"},
            )

        # Use expected_behavior.max_steps if provided
        eb_max = (expected_behavior or {}).get("max_steps")
        if eb_max and isinstance(eb_max, int) and eb_max > 0:
            max_steps = eb_max

        step_count = len(trace)

        # Detect loops: same node appearing consecutively
        node_names = [t.get("node", "") for t in trace]
        loop_detected = False
        loop_node = None
        for i in range(1, len(node_names)):
            if node_names[i] == node_names[i - 1] and node_names[i]:
                loop_detected = True
                loop_node = node_names[i]
                break

        if step_count <= max_steps:
            efficiency = max(0, 100 - (step_count / max_steps) * 30)
            score = min(100, 70 + efficiency * 0.3)
            reason = f"Robustness: Agent completed in {step_count} steps (limit: {max_steps})"
            if loop_detected:
                score = max(50, score - 20)
                reason += f". WARNING: Loop detected at node '{loop_node}'"
            passed = True
        else:
            overshoot = step_count - max_steps
            score = max(0, 70 - overshoot * 10)
            reason = f"Robustness: Agent used {step_count} steps, exceeding limit of {max_steps} by {overshoot}"
            if loop_detected:
                reason += f". Loop detected at node '{loop_node}' — agent may be stuck"
                score = max(0, score - 15)
            passed = score >= threshold

        return EvalResult(
            metric="step_count_limit",
            score=round(score, 1),
            passed=passed,
            reason=reason,
            details={
                "pillar": "Robustness",
                "step_count": step_count,
                "max_steps": max_steps,
                "loop_detected": loop_detected,
                "loop_node": loop_node,
                "nodes": node_names,
                "source": "expected_behavior" if eb_max else "default",
            },
        )

    # ── RAGAS/TruLens heuristic fallback methods ──

    def _heuristic_context_entity_recall(
        self, output: str, expected: Optional[str], context: Optional[List[str]], threshold: float,
    ) -> EvalResult:
        """Heuristic: do key entities from expected appear in context?"""
        if not expected or not context:
            return EvalResult(metric="ragas_context_entity_recall", score=0, passed=False,
                              reason="No expected answer or context provided")

        # Extract likely entities (capitalized words, numbers, quoted terms)
        import re
        entity_pattern = r'\b[A-Z][a-z]+(?:\s+[A-Z][a-z]+)*\b|\b\d+\b'
        expected_entities = set(re.findall(entity_pattern, expected))
        if not expected_entities:
            expected_entities = set(self._tokenize_lower(expected))

        context_text = " ".join(context).lower()
        found = sum(1 for e in expected_entities if e.lower() in context_text)
        score = (found / len(expected_entities) * 100) if expected_entities else 0
        score = round(score, 1)
        passed = score >= threshold

        return EvalResult(
            metric="ragas_context_entity_recall", score=score, passed=passed,
            reason=f"{found}/{len(expected_entities)} key entities from expected answer found in context",
        )

    def _heuristic_conciseness(self, output: str, threshold: float) -> EvalResult:
        """Heuristic: is the response concise?"""
        words = output.split()
        word_count = len(words)

        # Penalize excessively long responses
        if word_count <= 50:
            score = 100.0
        elif word_count <= 100:
            score = 90.0
        elif word_count <= 200:
            score = 75.0
        elif word_count <= 400:
            score = 60.0
        else:
            score = max(30.0, 100 - (word_count - 50) * 0.15)

        # Check for repetitive phrases
        sentences = [s.strip() for s in output.split('.') if s.strip()]
        if len(sentences) > 2:
            unique_ratio = len(set(s.lower() for s in sentences)) / len(sentences)
            if unique_ratio < 0.7:
                score = min(score, 50.0)

        score = round(score, 1)
        passed = score >= threshold

        return EvalResult(
            metric="trulens_conciseness", score=score, passed=passed,
            reason=f"Response is {word_count} words ({'concise' if score >= 75 else 'verbose'})",
        )

    def _heuristic_helpfulness(self, input_text: str, output: str, threshold: float) -> EvalResult:
        """Heuristic: is the response helpful and actionable?"""
        score = 50.0  # Base score

        output_lower = output.lower()
        input_lower = input_text.lower()

        # Check if response is substantive (not just a greeting or one-liner)
        words = output.split()
        if len(words) >= 10:
            score += 15
        if len(words) >= 25:
            score += 10

        # Check if response contains input keywords (addressing the question)
        input_tokens = set(self._tokenize_lower(input_text))
        output_tokens = set(self._tokenize_lower(output))
        overlap = input_tokens & output_tokens - {'the', 'a', 'an', 'is', 'are', 'was', 'were', 'do', 'does', 'what', 'how', 'can', 'you'}
        if overlap:
            score += min(15, len(overlap) * 5)

        # Check for actionable language
        action_indicators = ['you can', 'you should', 'to do this', 'steps', 'first', 'then',
                             'recommend', 'suggest', 'try', 'here is', 'here are', 'example']
        if any(ind in output_lower for ind in action_indicators):
            score += 10

        # Penalize refusals
        refusal_phrases = ["i can't", "i cannot", "i don't know", "not able to", "outside my"]
        if any(r in output_lower for r in refusal_phrases):
            score = max(20, score - 30)

        score = min(100.0, round(score, 1))
        passed = score >= threshold

        return EvalResult(
            metric="trulens_helpfulness", score=score, passed=passed,
            reason=f"Response helpfulness: {score:.0f}% ({'helpful' if passed else 'needs improvement'})",
        )

    @classmethod
    def list_metrics(cls) -> List[dict]:
        """List all available metrics."""
        return [
            {
                "id": metric_id,
                "name": info["name"],
                "description": info["description"],
                "requires": info["requires"],
            }
            for metric_id, info in cls.METRICS.items()
        ]
