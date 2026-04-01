"""
Statistical analysis for A/B testing.

Provides Welch's t-test for comparing agent performance with unequal variances.
"""

from dataclasses import dataclass
from typing import List, Tuple, Optional
import math


@dataclass
class StatisticalResult:
    """Result of a statistical comparison."""
    test_name: str
    statistic: float
    p_value: float
    significant: bool
    confidence_interval: Tuple[float, float]
    effect_size: float  # Cohen's d
    mean_a: float
    mean_b: float
    sample_size_a: int
    sample_size_b: int
    warnings: Optional[List[str]] = None

    def to_dict(self) -> dict:
        result = {
            "test_name": self.test_name,
            "statistic": round(self.statistic, 4),
            "p_value": round(self.p_value, 4),
            "significant": self.significant,
            "confidence_interval": (round(self.confidence_interval[0], 2), round(self.confidence_interval[1], 2)),
            "effect_size": round(self.effect_size, 3),
            "effect_interpretation": interpret_effect_size(self.effect_size),
            "mean_a": round(self.mean_a, 2),
            "mean_b": round(self.mean_b, 2),
            "sample_size_a": self.sample_size_a,
            "sample_size_b": self.sample_size_b,
        }
        if self.warnings:
            result["warnings"] = self.warnings
        return result


def interpret_effect_size(d: float) -> str:
    """Interpret Cohen's d effect size."""
    d = abs(d)
    if d < 0.2:
        return "negligible"
    elif d < 0.5:
        return "small"
    elif d < 0.8:
        return "medium"
    else:
        return "large"


def welch_t_test(scores_a: List[float], scores_b: List[float], significance_level: float = 0.05) -> StatisticalResult:
    """
    Perform Welch's t-test for comparing two groups.

    Welch's t-test is robust when sample sizes and variances differ,
    making it ideal for comparing agent performance.

    Args:
        scores_a: Scores from agent A (control)
        scores_b: Scores from agent B (treatment)
        significance_level: p-value threshold for significance (default 0.05)

    Returns:
        StatisticalResult with test statistics and interpretation
    """
    n_a = len(scores_a)
    n_b = len(scores_b)

    # Handle edge cases
    if n_a < 2 or n_b < 2:
        return StatisticalResult(
            test_name="welch_t_test",
            statistic=0.0,
            p_value=1.0,
            significant=False,
            confidence_interval=(0.0, 0.0),
            effect_size=0.0,
            mean_a=sum(scores_a) / n_a if n_a > 0 else 0,
            mean_b=sum(scores_b) / n_b if n_b > 0 else 0,
            sample_size_a=n_a,
            sample_size_b=n_b,
        )

    # Calculate means
    mean_a = sum(scores_a) / n_a
    mean_b = sum(scores_b) / n_b

    # Calculate variances
    var_a = sum((x - mean_a) ** 2 for x in scores_a) / (n_a - 1)
    var_b = sum((x - mean_b) ** 2 for x in scores_b) / (n_b - 1)

    # Standard error of the difference
    se = math.sqrt(var_a / n_a + var_b / n_b)

    if se == 0:
        # No variance - can't compute meaningful statistics
        return StatisticalResult(
            test_name="welch_t_test",
            statistic=0.0,
            p_value=1.0,
            significant=False,
            confidence_interval=(mean_b - mean_a, mean_b - mean_a),
            effect_size=0.0,
            mean_a=mean_a,
            mean_b=mean_b,
            sample_size_a=n_a,
            sample_size_b=n_b,
        )

    # t-statistic
    t_stat = (mean_b - mean_a) / se

    # Welch-Satterthwaite degrees of freedom
    numerator = (var_a / n_a + var_b / n_b) ** 2
    denominator = (var_a / n_a) ** 2 / (n_a - 1) + (var_b / n_b) ** 2 / (n_b - 1)
    df = numerator / denominator if denominator > 0 else 1

    # Two-tailed p-value
    p_value = _t_distribution_p_value(abs(t_stat), df)

    # 95% confidence interval for the difference (B - A)
    t_critical = _t_critical_value(df, significance_level)
    margin = t_critical * se
    ci_lower = (mean_b - mean_a) - margin
    ci_upper = (mean_b - mean_a) + margin

    # Cohen's d effect size (using pooled standard deviation)
    pooled_var = ((n_a - 1) * var_a + (n_b - 1) * var_b) / (n_a + n_b - 2)
    pooled_std = math.sqrt(pooled_var) if pooled_var > 0 else 1
    effect_size = (mean_b - mean_a) / pooled_std

    # Generate warnings for small samples or approximation limitations
    warnings = []
    if n_a < 5 or n_b < 5:
        warnings.append(f"Small sample size (n_a={n_a}, n_b={n_b}). Results may be unreliable. Recommend n >= 5 per group.")
    if df < 10:
        warnings.append(f"Low degrees of freedom ({df:.1f}). p-value is approximate.")
    if n_a < 30 or n_b < 30:
        warnings.append("Sample sizes below 30: t-test assumes approximately normal score distributions.")

    return StatisticalResult(
        test_name="welch_t_test",
        statistic=t_stat,
        p_value=p_value,
        significant=p_value < significance_level,
        confidence_interval=(ci_lower, ci_upper),
        effect_size=effect_size,
        mean_a=mean_a,
        mean_b=mean_b,
        sample_size_a=n_a,
        sample_size_b=n_b,
        warnings=warnings if warnings else None,
    )


def _t_distribution_p_value(t: float, df: float) -> float:
    """
    Approximate two-tailed p-value from t-distribution.

    Uses approximation that's accurate for df > 4.
    For small df, uses a more conservative estimate.
    """
    if df <= 0:
        return 1.0

    # Approximation using the normal distribution for large df
    if df > 30:
        return 2 * (1 - _normal_cdf(abs(t)))

    # For smaller df, use approximation that accounts for heavier tails
    # This is a simplified approximation of the t-distribution CDF
    x = df / (df + t * t)

    # Regularized incomplete beta function approximation
    if t == 0:
        return 1.0

    # Use normal approximation with correction for df
    corrected_t = abs(t) * math.sqrt((df - 2) / df) if df > 2 else abs(t)
    p = 2 * (1 - _normal_cdf(corrected_t))

    # Apply conservative adjustment for small samples
    if df < 10:
        p = min(1.0, p * 1.1)

    return min(1.0, max(0.0, p))


def _normal_cdf(x: float) -> float:
    """Cumulative distribution function of standard normal."""
    return 0.5 * (1 + math.erf(x / math.sqrt(2)))


def _t_critical_value(df: float, alpha: float = 0.05) -> float:
    """
    Approximate t critical value for two-tailed test.

    Uses approximation based on normal distribution with correction.
    """
    # For 95% CI (alpha=0.05), two-tailed critical values
    if df >= 120:
        return 1.96
    elif df >= 60:
        return 2.0
    elif df >= 30:
        return 2.04
    elif df >= 20:
        return 2.09
    elif df >= 15:
        return 2.13
    elif df >= 10:
        return 2.23
    elif df >= 5:
        return 2.57
    else:
        return 2.78


def determine_winner(
    scores_a: List[float],
    scores_b: List[float],
    significance_level: float = 0.05,
    min_samples: int = 5,
) -> Tuple[Optional[str], StatisticalResult]:
    """
    Determine the winner between two agents.

    Args:
        scores_a: Scores from agent A (control)
        scores_b: Scores from agent B (treatment)
        significance_level: p-value threshold (default 0.05)
        min_samples: Minimum samples required for significance testing

    Returns:
        Tuple of (winner, statistical_result)
        winner is "A", "B", "tie", or None (insufficient data)
    """
    if len(scores_a) < min_samples or len(scores_b) < min_samples:
        result = welch_t_test(scores_a, scores_b, significance_level)
        return None, result

    result = welch_t_test(scores_a, scores_b, significance_level)

    if not result.significant:
        return "tie", result

    # Winner is the one with higher mean
    winner = "B" if result.mean_b > result.mean_a else "A"
    return winner, result


def calculate_summary_stats(scores: List[float]) -> dict:
    """Calculate summary statistics for a list of scores."""
    if not scores:
        return {
            "count": 0,
            "mean": 0,
            "std": 0,
            "min": 0,
            "max": 0,
            "median": 0,
        }

    n = len(scores)
    mean = sum(scores) / n
    variance = sum((x - mean) ** 2 for x in scores) / (n - 1) if n > 1 else 0
    std = math.sqrt(variance)

    sorted_scores = sorted(scores)
    median = sorted_scores[n // 2] if n % 2 == 1 else (sorted_scores[n // 2 - 1] + sorted_scores[n // 2]) / 2

    return {
        "count": n,
        "mean": round(mean, 2),
        "std": round(std, 2),
        "min": round(min(scores), 2),
        "max": round(max(scores), 2),
        "median": round(median, 2),
    }
