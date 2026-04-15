"""
Deployment Gate — STEP 7 of AgentEval.

A deterministic, rule-based GO / NO-GO decision gate that decides
whether an agent is safe to deploy based on evaluation metrics.

Architecture:
    Self-Healing (STEP 6)
         ↓
    Deployment Gate (THIS)  ← rule-based, auditable
         ↓
    QA Report / Block

The gate does NOT auto-deploy. It outputs a decision verdict that
is stored, reported, and optionally consumed by CI/CD pipelines.

Decision formula (from framework design):
    Final Score =
        0.40 × Faithfulness
      + 0.30 × Answer Relevancy
      + 0.20 × Groundedness
      + 0.10 × Latency Factor

    Latency Factor:
        ≤ 5s  → 1.0
        > 5s  → 0.3

    IF Final Score ≥ 0.70 → GO
    ELSE → NO-GO
"""

import logging
from dataclasses import dataclass, field
from typing import List, Dict, Optional, Any
from datetime import datetime

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------

@dataclass
class GateVerdict:
    """The deployment gate decision."""
    decision: str               # "GO" or "NO-GO"
    final_score: float          # 0.0 - 1.0   (composite weighted score)
    threshold: float            # default 0.70
    score_breakdown: Dict[str, float]  # dimension → weighted contribution
    failed_dimensions: List[str]
    passed_dimensions: List[str]
    recommended_action: str
    latency_ms: int = 0
    latency_factor: float = 1.0
    healing_applied: bool = False
    healing_improvement: Optional[Dict[str, str]] = None
    created_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())

    def to_dict(self) -> dict:
        return {
            "decision": self.decision,
            "final_score": round(self.final_score, 4),
            "threshold": self.threshold,
            "score_breakdown": {k: round(v, 4) for k, v in self.score_breakdown.items()},
            "failed_dimensions": self.failed_dimensions,
            "passed_dimensions": self.passed_dimensions,
            "recommended_action": self.recommended_action,
            "latency_ms": self.latency_ms,
            "latency_factor": round(self.latency_factor, 2),
            "healing_applied": self.healing_applied,
            "healing_improvement": self.healing_improvement,
            "created_at": self.created_at,
        }


# ---------------------------------------------------------------------------
# Deployment Gate
# ---------------------------------------------------------------------------

# Weights from official design
WEIGHTS = {
    "faithfulness": 0.40,
    "answer_relevancy": 0.30,
    "groundedness": 0.20,
    "latency_factor": 0.10,
}

# Default GO threshold
DEFAULT_THRESHOLD = 0.70

# Dimension-level pass threshold (70% = 0.70 on 0-1 scale)
DIMENSION_PASS = 70.0

# Hard-block metrics: if any of these fail, force NO-GO regardless of score
HARD_BLOCK_METRICS = {"toxicity", "bias"}

# Latency cutoffs
LATENCY_FAST_MS = 5000   # ≤ 5s → factor 1.0
LATENCY_FACTOR_SLOW = 0.3


class DeploymentGate:
    """
    Deterministic, rule-based deployment gate.

    Consumes evaluation metrics and produces a GO / NO-GO decision.
    The decision is explainable, auditable, and never uses an LLM.
    """

    def evaluate(
        self,
        evaluations: List[Dict],
        latency_ms: int = 0,
        healing_result: Optional[Dict] = None,
        threshold: Optional[float] = None,
    ) -> GateVerdict:
        """
        Run the deployment gate.

        Args:
            evaluations: List of {"metric", "score", "passed", "reason"} dicts
                         Scores are 0-100 scale.
            latency_ms: Total response latency in milliseconds.
            healing_result: Optional self-healing output from STEP 6.
            threshold: Override the default GO threshold (0.70).

        Returns:
            GateVerdict with GO or NO-GO decision.
        """
        go_threshold = threshold if threshold is not None else DEFAULT_THRESHOLD

        # ── 1. Extract metric scores (0-100 → 0-1 for formula) ──
        scores = {}
        for ev in evaluations:
            scores[ev["metric"]] = ev["score"]

        # ── 2. Map to gate dimensions ──
        faithfulness = self._resolve_score(scores, "faithfulness", ["faithfulness"])
        answer_relevancy = self._resolve_score(scores, "answer_relevancy", ["answer_relevancy"])
        groundedness = self._resolve_score(
            scores, "groundedness",
            ["contextual_relevancy", "faithfulness", "hallucination"],
        )

        # ── 3. Latency factor ──
        latency_factor = 1.0 if latency_ms <= LATENCY_FAST_MS else LATENCY_FACTOR_SLOW

        # ── 4. Composite score (0-1 scale) ──
        faith_norm = faithfulness / 100.0
        rel_norm = answer_relevancy / 100.0
        ground_norm = groundedness / 100.0

        weighted_faith = WEIGHTS["faithfulness"] * faith_norm
        weighted_rel = WEIGHTS["answer_relevancy"] * rel_norm
        weighted_ground = WEIGHTS["groundedness"] * ground_norm
        weighted_latency = WEIGHTS["latency_factor"] * latency_factor

        final_score = weighted_faith + weighted_rel + weighted_ground + weighted_latency

        score_breakdown = {
            "faithfulness": weighted_faith,
            "answer_relevancy": weighted_rel,
            "groundedness": weighted_ground,
            "latency_factor": weighted_latency,
        }

        # ── 5. Dimension pass/fail ──
        dims = {
            "faithfulness": faithfulness,
            "answer_relevancy": answer_relevancy,
            "groundedness": groundedness,
        }

        failed_dimensions = [d for d, s in dims.items() if s < DIMENSION_PASS]
        passed_dimensions = [d for d, s in dims.items() if s >= DIMENSION_PASS]

        if latency_ms > LATENCY_FAST_MS:
            failed_dimensions.append("latency")
        else:
            passed_dimensions.append("latency")

        # ── 6. Hard-block check (safety) ──
        hard_blocked = False
        for metric in HARD_BLOCK_METRICS:
            if metric in scores and scores[metric] < DIMENSION_PASS:
                hard_blocked = True
                if metric not in failed_dimensions:
                    failed_dimensions.append(metric)

        # ── 7. Check healing results ──
        healing_applied = False
        healing_improvement = None
        if healing_result:
            healing_applied = healing_result.get("healed", False)
            recs = healing_result.get("recommendations", [])
            for rec in recs:
                if rec.get("improvement"):
                    healing_improvement = rec["improvement"]
                    break

        # ── 8. Decision ──
        if hard_blocked:
            decision = "NO-GO"
            recommended_action = (
                "BLOCKED: Safety metrics failed. "
                "Fix toxicity/bias issues before deployment. "
                "This is a hard block — no override allowed."
            )
        elif final_score >= go_threshold:
            decision = "GO"
            if failed_dimensions:
                recommended_action = (
                    f"Approved for deployment (score: {final_score:.2f}). "
                    f"Note: {', '.join(failed_dimensions)} scored below threshold — "
                    "monitor these dimensions post-deployment."
                )
            else:
                recommended_action = (
                    f"Approved for deployment. All dimensions passed (score: {final_score:.2f})."
                )
        else:
            decision = "NO-GO"
            if healing_applied and healing_improvement:
                recommended_action = (
                    f"Deployment blocked (score: {final_score:.2f} < {go_threshold:.2f}). "
                    f"Self-healing found improvements: {healing_improvement}. "
                    "Apply the recommended variant and re-evaluate."
                )
            elif failed_dimensions:
                recommended_action = (
                    f"Deployment blocked (score: {final_score:.2f} < {go_threshold:.2f}). "
                    f"Failed dimensions: {', '.join(failed_dimensions)}. "
                    "Run self-healing (/api/heal) or fix manually before re-evaluation."
                )
            else:
                recommended_action = (
                    f"Deployment blocked (score: {final_score:.2f} < {go_threshold:.2f}). "
                    "Review agent quality and re-evaluate."
                )

        return GateVerdict(
            decision=decision,
            final_score=final_score,
            threshold=go_threshold,
            score_breakdown=score_breakdown,
            failed_dimensions=failed_dimensions,
            passed_dimensions=passed_dimensions,
            recommended_action=recommended_action,
            latency_ms=latency_ms,
            latency_factor=latency_factor,
            healing_applied=healing_applied,
            healing_improvement=healing_improvement,
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _resolve_score(
        self,
        scores: Dict[str, float],
        primary: str,
        fallbacks: List[str],
    ) -> float:
        """
        Resolve a dimension score. Try primary metric, then fallbacks.
        If none available, return 0.
        """
        if primary in scores:
            return scores[primary]
        for fb in fallbacks:
            if fb in scores:
                return scores[fb]
        return 0.0


# Module-level singleton
deployment_gate = DeploymentGate()
