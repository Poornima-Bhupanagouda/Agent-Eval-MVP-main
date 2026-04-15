"""
Self-Healing Agent — STEP 6 of AgentEval.

Takes RCA diagnoses and automatically experiments with config/prompt
variants to find a fix, then recommends the best variant.

Architecture:
    Root Cause Analysis (STEP 5)
         ↓
    Self-Healing Engine (THIS)  ← rule-based decision tree
         ↓
    Deployment Gate (STEP 7)

Fix paths:
    1. Config optimization  — retrieval_failure → try chunk_size, overlap, top_k
    2. Prompt optimization  — prompt_failure → try citation/evidence/strict prompts
    3. Planning failure     — flag for developer (no auto-fix, safe boundary)
    4. Performance failure  — flag for developer
    5. Safety failure       — flag for developer (never auto-fix safety)

The agent ONLY changes configuration, not business data.
It does NOT auto-deploy — it produces a recommendation for STEP 7.
"""

import logging
import asyncio
import time
from dataclasses import dataclass, field
from typing import List, Dict, Optional, Any

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------

@dataclass
class VariantResult:
    """Result of testing a single config/prompt variant."""
    variant_id: str
    variant_type: str           # "config" or "prompt"
    parameters: Dict[str, Any]  # The config/prompt that was tested
    scores: Dict[str, float]    # Metric name → score
    composite_score: float      # 0.5 * context_precision + 0.5 * groundedness
    passed: bool
    output_preview: str = ""    # First 200 chars of agent output

    def to_dict(self) -> dict:
        return {
            "variant_id": self.variant_id,
            "variant_type": self.variant_type,
            "parameters": self.parameters,
            "scores": self.scores,
            "composite_score": round(self.composite_score, 2),
            "passed": self.passed,
            "output_preview": self.output_preview,
        }


@dataclass
class HealingRecommendation:
    """The output of the self-healing agent."""
    fix_type: str               # "config_optimization", "prompt_optimization", "manual_review"
    root_cause: str             # From RCA diagnosis
    best_variant: Optional[Dict[str, Any]] = None
    improvement: Optional[Dict[str, str]] = None  # metric → "+0.32" style
    confidence: float = 0.0
    variants_tested: int = 0
    all_variants: List[VariantResult] = field(default_factory=list)
    recommendation: str = ""
    requires_manual_review: bool = False

    def to_dict(self) -> dict:
        return {
            "fix_type": self.fix_type,
            "root_cause": self.root_cause,
            "best_variant": self.best_variant,
            "improvement": self.improvement,
            "confidence": round(self.confidence, 2),
            "variants_tested": self.variants_tested,
            "all_variants": [v.to_dict() for v in self.all_variants],
            "recommendation": self.recommendation,
            "requires_manual_review": self.requires_manual_review,
        }


@dataclass
class HealingResult:
    """Complete self-healing output."""
    healed: bool
    recommendations: List[HealingRecommendation] = field(default_factory=list)
    summary: str = ""
    total_variants_tested: int = 0

    def to_dict(self) -> dict:
        return {
            "healed": self.healed,
            "recommendations": [r.to_dict() for r in self.recommendations],
            "summary": self.summary,
            "total_variants_tested": self.total_variants_tested,
        }


# ---------------------------------------------------------------------------
# Prompt variant library
# ---------------------------------------------------------------------------

PROMPT_VARIANTS = {
    "citation_enforced": {
        "id": "citation_enforced",
        "label": "Citation-enforced prompt",
        "system_prompt_suffix": (
            "\n\nIMPORTANT: You MUST cite specific passages from the provided context "
            "to support every claim in your answer. Use direct quotes where possible. "
            "If the context does not contain the information, say 'The provided context "
            "does not contain this information.'"
        ),
    },
    "evidence_first": {
        "id": "evidence_first",
        "label": "Evidence-first prompt",
        "system_prompt_suffix": (
            "\n\nFormat your response as follows:\n"
            "1. First, list the relevant evidence from the provided context\n"
            "2. Then, provide your answer based ONLY on that evidence\n"
            "3. If no relevant evidence exists, state that clearly"
        ),
    },
    "context_only_strict": {
        "id": "context_only_strict",
        "label": "Strict context-only prompt",
        "system_prompt_suffix": (
            "\n\nCRITICAL RULE: Answer using ONLY information from the provided context. "
            "Do NOT use any prior knowledge. Do NOT make assumptions. "
            "If the answer is not in the context, respond with: "
            "'I cannot answer this based on the available information.'"
        ),
    },
    "direct_answer": {
        "id": "direct_answer",
        "label": "Direct answer prompt",
        "system_prompt_suffix": (
            "\n\nProvide a direct, concise answer to the question using the provided context. "
            "Do not include unnecessary preamble or caveats. Be factual and specific."
        ),
    },
}

# ---------------------------------------------------------------------------
# Config variant library
# ---------------------------------------------------------------------------

CONFIG_VARIANTS = [
    {"chunk_size": 100, "overlap": 10, "top_k": 3},
    {"chunk_size": 200, "overlap": 40, "top_k": 3},
    {"chunk_size": 300, "overlap": 40, "top_k": 5},
    {"chunk_size": 400, "overlap": 80, "top_k": 5},
]


# ---------------------------------------------------------------------------
# Self-Healing Agent
# ---------------------------------------------------------------------------

class SelfHealingAgent:
    """
    Self-Healing agent that experiments with prompt and config variants
    to find the best fix for a diagnosed root cause.

    Pipeline (decision-tree-style nodes):
        1. classify_fix_path   — decide config vs. prompt vs. manual
        2. generate_variants   — create variant list
        3. test_variants       — re-run agent + evaluate each
        4. select_best         — pick winner by composite score

    The agent does NOT auto-deploy. It outputs a recommendation.
    """

    # Composite score formula weights (from design spec)
    WEIGHT_CONTEXT_PRECISION = 0.5
    WEIGHT_GROUNDEDNESS = 0.5

    # Root causes that are safe to auto-optimize
    AUTO_HEALABLE = {
        "retrieval_failure": "config",
        "prompt_failure": "prompt",
    }

    # Root causes that require manual review
    MANUAL_REVIEW = {
        "wrong_tool_selected", "wrong_tool_order", "planning_failure",
        "performance_failure", "safety_failure", "memory_failure",
        "robustness_failure", "unclassified_failure",
    }

    async def heal(
        self,
        rca_diagnoses: List[Dict],
        original_scores: Dict[str, float],
        endpoint: str,
        input_text: str,
        expected: Optional[str] = None,
        context: Optional[List[str]] = None,
        metrics: Optional[List[str]] = None,
        threshold: Optional[float] = None,
        agent_type: Optional[str] = None,
        executor: Optional[Any] = None,
        evaluator: Optional[Any] = None,
    ) -> HealingResult:
        """
        Run the full self-healing pipeline.

        Args:
            rca_diagnoses: List of RCA diagnosis dicts (from RCAResult.to_dict()["diagnoses"])
            original_scores: Dict of metric_name → score from the failed run
            endpoint: Agent endpoint URL to re-test against
            input_text: Original test input
            expected: Expected output (for evaluation)
            context: RAG context chunks
            metrics: Metrics to evaluate
            threshold: Pass threshold
            agent_type: Agent type for metric auto-selection
            executor: Executor instance (for re-running agent)
            evaluator: Evaluator instance (for re-scoring)

        Returns:
            HealingResult with recommendations
        """
        recommendations = []
        total_variants = 0

        for diag in rca_diagnoses:
            root_cause = diag.get("root_cause", "unknown")

            # Node 1: Classify fix path
            fix_path = self._classify_fix_path(root_cause)

            if fix_path == "manual":
                # Not auto-healable — produce manual review recommendation
                recommendations.append(self._manual_review_recommendation(diag))
                continue

            if executor is None or evaluator is None:
                # Can't test variants without executor/evaluator
                rec = self._manual_review_recommendation(diag)
                rec.recommendation = (
                    f"Auto-healing available for {root_cause} but executor/evaluator not provided. "
                    "Run via /api/heal endpoint with a live agent to test variants."
                )
                recommendations.append(rec)
                continue

            # Node 2: Generate variants
            variants = self._generate_variants(fix_path, root_cause)

            # Node 3: Test each variant
            variant_results = await self._test_variants(
                variants=variants,
                fix_path=fix_path,
                endpoint=endpoint,
                input_text=input_text,
                expected=expected,
                context=context,
                metrics=metrics,
                threshold=threshold,
                agent_type=agent_type,
                executor=executor,
                evaluator=evaluator,
            )
            total_variants += len(variant_results)

            # Node 4: Select best variant
            rec = self._select_best(
                variant_results=variant_results,
                original_scores=original_scores,
                root_cause=root_cause,
                fix_path=fix_path,
            )
            recommendations.append(rec)

        # Build summary
        healed = any(r.confidence > 0.5 and not r.requires_manual_review for r in recommendations)
        summary = self._build_summary(recommendations, healed)

        return HealingResult(
            healed=healed,
            recommendations=recommendations,
            summary=summary,
            total_variants_tested=total_variants,
        )

    # ------------------------------------------------------------------
    # Node 1: Classify fix path
    # ------------------------------------------------------------------

    def _classify_fix_path(self, root_cause: str) -> str:
        """Decide whether to optimize config, prompt, or flag for manual review."""
        if root_cause in self.AUTO_HEALABLE:
            return self.AUTO_HEALABLE[root_cause]
        return "manual"

    # ------------------------------------------------------------------
    # Node 2: Generate variants
    # ------------------------------------------------------------------

    def _generate_variants(self, fix_path: str, root_cause: str) -> List[Dict]:
        """Generate config or prompt variants to test."""
        if fix_path == "config":
            return [
                {"variant_id": f"config_{i+1}", "variant_type": "config", "params": cfg}
                for i, cfg in enumerate(CONFIG_VARIANTS)
            ]
        elif fix_path == "prompt":
            return [
                {
                    "variant_id": pv["id"],
                    "variant_type": "prompt",
                    "params": pv,
                }
                for pv in PROMPT_VARIANTS.values()
            ]
        return []

    # ------------------------------------------------------------------
    # Node 3: Test variants
    # ------------------------------------------------------------------

    async def _test_variants(
        self,
        variants: List[Dict],
        fix_path: str,
        endpoint: str,
        input_text: str,
        expected: Optional[str],
        context: Optional[List[str]],
        metrics: Optional[List[str]],
        threshold: Optional[float],
        agent_type: Optional[str],
        executor: Any,
        evaluator: Any,
    ) -> List[VariantResult]:
        """Test each variant by re-running the agent and evaluating."""
        results = []

        for variant in variants:
            try:
                result = await self._test_single_variant(
                    variant=variant,
                    fix_path=fix_path,
                    endpoint=endpoint,
                    input_text=input_text,
                    expected=expected,
                    context=context,
                    metrics=metrics,
                    threshold=threshold,
                    agent_type=agent_type,
                    executor=executor,
                    evaluator=evaluator,
                )
                results.append(result)
            except Exception as e:
                logger.warning(f"Failed to test variant {variant.get('variant_id')}: {e}")
                # Create a failed variant result
                results.append(VariantResult(
                    variant_id=variant.get("variant_id", "unknown"),
                    variant_type=variant.get("variant_type", "unknown"),
                    parameters=variant.get("params", {}),
                    scores={},
                    composite_score=0.0,
                    passed=False,
                    output_preview=f"Error: {e}",
                ))

        return results

    async def _test_single_variant(
        self,
        variant: Dict,
        fix_path: str,
        endpoint: str,
        input_text: str,
        expected: Optional[str],
        context: Optional[List[str]],
        metrics: Optional[List[str]],
        threshold: Optional[float],
        agent_type: Optional[str],
        executor: Any,
        evaluator: Any,
    ) -> VariantResult:
        """Test a single variant: execute + evaluate."""
        params = variant.get("params", {})

        # Build the modified input/context for this variant
        modified_input = input_text
        modified_context = context

        if fix_path == "prompt":
            # For prompt variants, append prompt suffix to input
            suffix = params.get("system_prompt_suffix", "")
            if suffix:
                modified_input = f"{input_text}\n\n[System instruction: {suffix.strip()}]"

        elif fix_path == "config":
            # For config variants, modify context chunking
            if context:
                chunk_size = params.get("chunk_size", 300)
                overlap = params.get("overlap", 40)
                top_k = params.get("top_k", 5)
                modified_context = self._rechunk_context(context, chunk_size, overlap, top_k)

        # Execute agent with modified input
        exec_result = await executor.execute(
            endpoint=endpoint,
            input_text=modified_input,
            context=modified_context,
        )

        # Evaluate the result
        eval_results = await asyncio.to_thread(
            evaluator.evaluate,
            input_text=input_text,  # Original input for fair comparison
            output=exec_result.output,
            expected=expected,
            context=modified_context,
            metrics=metrics,
            threshold=threshold,
            agent_type=agent_type,
            tool_calls=exec_result.tool_calls,
            trace=exec_result.trace,
        )

        # Extract scores
        scores = {r.metric: r.score for r in eval_results}
        all_passed = all(r.passed for r in eval_results)

        # Calculate composite score
        composite = self._composite_score(scores)

        return VariantResult(
            variant_id=variant.get("variant_id", "unknown"),
            variant_type=variant.get("variant_type", "unknown"),
            parameters=params,
            scores=scores,
            composite_score=composite,
            passed=all_passed,
            output_preview=exec_result.output[:200] if exec_result.output else "",
        )

    def _rechunk_context(
        self, context: List[str], chunk_size: int, overlap: int, top_k: int
    ) -> List[str]:
        """Re-chunk context with different parameters."""
        # Combine all context into one string
        full_text = "\n".join(context)

        if not full_text:
            return context

        # Split into chunks with overlap
        chunks = []
        start = 0
        while start < len(full_text):
            end = start + chunk_size
            chunk = full_text[start:end].strip()
            if chunk:
                chunks.append(chunk)
            start = end - overlap
            if overlap <= 0:
                start = end

        # Return top_k chunks (in a real system, you'd rank by relevance)
        return chunks[:top_k]

    # ------------------------------------------------------------------
    # Node 4: Select best variant
    # ------------------------------------------------------------------

    def _select_best(
        self,
        variant_results: List[VariantResult],
        original_scores: Dict[str, float],
        root_cause: str,
        fix_path: str,
    ) -> HealingRecommendation:
        """Select the best variant by composite score."""
        if not variant_results:
            return HealingRecommendation(
                fix_type=f"{fix_path}_optimization",
                root_cause=root_cause,
                confidence=0.0,
                recommendation="No variants could be tested.",
                requires_manual_review=True,
            )

        # Sort by composite score (highest first)
        sorted_results = sorted(variant_results, key=lambda v: v.composite_score, reverse=True)
        best = sorted_results[0]

        # Calculate original composite for comparison
        original_composite = self._composite_score(original_scores)

        # Calculate improvement
        improvement = {}
        for metric, new_score in best.scores.items():
            old_score = original_scores.get(metric)
            if old_score is not None:
                diff = new_score - old_score
                if abs(diff) > 0.1:
                    improvement[metric] = f"{'+' if diff > 0 else ''}{diff:.1f}"

        # Determine confidence based on improvement
        score_delta = best.composite_score - original_composite
        if score_delta > 20:
            confidence = 0.9
        elif score_delta > 10:
            confidence = 0.75
        elif score_delta > 5:
            confidence = 0.6
        elif score_delta > 0:
            confidence = 0.4
        else:
            confidence = 0.2

        improved = score_delta > 0

        fix_type = f"{fix_path}_optimization"
        if improved:
            recommendation = (
                f"Variant '{best.variant_id}' improved composite score by "
                f"{score_delta:+.1f} points ({original_composite:.0f} → {best.composite_score:.0f}). "
                f"Apply this {fix_path} change to improve agent quality."
            )
        else:
            recommendation = (
                f"Tested {len(variant_results)} {fix_path} variants but none improved the composite score. "
                f"Best variant '{best.variant_id}' scored {best.composite_score:.0f} "
                f"(original: {original_composite:.0f}). "
                "Manual investigation of the agent logic is recommended."
            )

        return HealingRecommendation(
            fix_type=fix_type,
            root_cause=root_cause,
            best_variant=best.parameters if improved else None,
            improvement=improvement if improved else None,
            confidence=round(confidence, 2),
            variants_tested=len(variant_results),
            all_variants=sorted_results,
            recommendation=recommendation,
            requires_manual_review=not improved,
        )

    # ------------------------------------------------------------------
    # Manual review (for non-auto-healable root causes)
    # ------------------------------------------------------------------

    def _manual_review_recommendation(self, diag: Dict) -> HealingRecommendation:
        """Create a manual-review recommendation for root causes we can't auto-fix."""
        root_cause = diag.get("root_cause", "unknown")
        category = diag.get("category", "Unknown")
        evidence = diag.get("evidence", [])
        rca_recommendation = diag.get("recommendation", "")

        return HealingRecommendation(
            fix_type="manual_review",
            root_cause=root_cause,
            confidence=0.0,
            recommendation=(
                f"[{category}] {root_cause} requires manual review. "
                f"RCA evidence: {'; '.join(evidence[:3])}. "
                f"Suggested action: {rca_recommendation}"
            ),
            requires_manual_review=True,
        )

    # ------------------------------------------------------------------
    # Scoring
    # ------------------------------------------------------------------

    def _composite_score(self, scores: Dict[str, float]) -> float:
        """
        Calculate composite score.
        Formula: 0.5 × context_precision + 0.5 × groundedness

        Falls back to available metrics if these specific ones aren't present.
        """
        # Map metric names to our scoring terms
        context_precision = (
            scores.get("contextual_relevancy")
            or scores.get("precision_at_k")
            or scores.get("context_precision")
            or 0.0
        )
        groundedness = (
            scores.get("faithfulness")
            or scores.get("hallucination")
            or scores.get("groundedness")
            or 0.0
        )

        # If neither key metric available, use average of all scores
        if context_precision == 0.0 and groundedness == 0.0 and scores:
            return sum(scores.values()) / len(scores)

        return (
            self.WEIGHT_CONTEXT_PRECISION * context_precision
            + self.WEIGHT_GROUNDEDNESS * groundedness
        )

    # ------------------------------------------------------------------
    # Summary
    # ------------------------------------------------------------------

    def _build_summary(self, recommendations: List[HealingRecommendation], healed: bool) -> str:
        """Build human-readable summary."""
        if not recommendations:
            return "No healing actions taken."

        parts = []
        for r in recommendations:
            if r.requires_manual_review:
                parts.append(f"[{r.root_cause}] Requires manual review")
            else:
                parts.append(
                    f"[{r.root_cause}] Fixed via {r.fix_type} "
                    f"(confidence: {r.confidence:.0%}, {r.variants_tested} variants tested)"
                )

        status = "Self-healing successful" if healed else "Manual review needed"
        return f"{status}. {'; '.join(parts)}."


# Module-level singleton
healing_agent = SelfHealingAgent()
