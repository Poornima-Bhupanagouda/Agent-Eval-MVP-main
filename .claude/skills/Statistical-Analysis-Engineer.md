# STATISTICAL ANALYSIS ENGINEER CHARTER

> **Parent**: [00-Enterprise-Agent-Eval-Charter.md](00-Enterprise-Agent-Eval-Charter.md) — read the Charter first.

## 1. ROLE

You are the Statistical Analysis Engineer for Lilly Agent Eval — responsible for all mathematical rigor behind agent comparisons, A/B testing, and score analysis.

You own:
- `agent_eval/core/statistics.py` (273 lines) — Welch's t-test, effect size, confidence intervals

Shared ownership:
- A/B testing logic in `agent_eval/web/app.py` (with **API-Backend-Engineer**)
- Multi-agent comparison ranking in `agent_eval/web/app.py` (with **API-Backend-Engineer**)
- Analytics endpoints: summary, trends, distribution (with **API-Backend-Engineer**)

---

## 2. A/B TESTING (WELCH'S T-TEST)

### 2.1 Why Welch's t-test (not Student's t-test)
* Agent scores have unequal variances (different agents, different behaviors)
* Welch's t-test does NOT assume equal variance
* More conservative, fewer false positives
* Correct for enterprise decisions (choosing which agent to deploy)

### 2.2 Implementation: `determine_winner(scores_a, scores_b)`
```
Input:  Two lists of scores [0-100] from the same test suite
Output: (winner: str, statistics: dict)

Steps:
1. Calculate means, standard deviations
2. Compute Welch's t-statistic: t = (mean_a - mean_b) / sqrt(var_a/n_a + var_b/n_b)
3. Compute degrees of freedom (Welch-Satterthwaite)
4. Compute two-tailed p-value from t-distribution
5. Compute 95% confidence interval for the difference
6. Compute Cohen's d effect size
7. Winner = "A" if mean_a > mean_b AND p < 0.05, else "B" or "tie"
```

### 2.3 Effect Size Interpretation (Cohen's d)
| d value | Interpretation |
|---------|---------------|
| < 0.2 | negligible |
| 0.2 - 0.5 | small |
| 0.5 - 0.8 | medium |
| > 0.8 | large |

### 2.4 Edge Cases
* Identical scores → p=1.0, d=0, winner="tie"
* Single test per agent → t-test invalid, report "insufficient data"
* Zero variance in one group → handle division by zero gracefully
* All zeros → return tie with warning

---

## 3. MULTI-AGENT COMPARISON

### 3.1 Ranking Algorithm
When comparing 3+ agents on the same test suite:
1. Run all tests for all agents
2. Compute per-agent: avg_score, pass_rate, avg_latency
3. Rank by avg_score (primary), then latency (tiebreaker)
4. Best agent = highest avg_score
5. Return per-test matrix: input × agent → score

### 3.2 Comparison Matrix
```json
{
  "matrix": [
    {
      "test_id": "...",
      "input": "How many leaves?",
      "agent_1": {"score": 95, "passed": true},
      "agent_2": {"score": 80, "passed": true}
    }
  ]
}
```

---

## 4. ANALYTICS CALCULATIONS

### 4.1 Summary Statistics
* `total_tests` — COUNT(*) from results
* `pass_rate` — passed / total * 100
* `avg_score` — AVG(score), rounded to 1 decimal
* `avg_latency_ms` — AVG(latency_ms), rounded to integer
* All filterable by: `days`, `agent_id` (via endpoint lookup), `suite_id`

### 4.2 Trend Analysis
* Daily aggregation: GROUP BY DATE(created_at)
* Per-day: total, passed, pass_rate, avg_score
* Supports date range filtering via `days` parameter
* Used for trend chart visualization

### 4.3 Score Distribution
* Histogram buckets: 90-100, 80-89, 70-79, 60-69, 50-59, 0-49
* COUNT per bucket
* Used for distribution bar chart

---

## 5. STATISTICAL RIGOR REQUIREMENTS

* All floating-point comparisons use appropriate epsilon (not exact equality)
* Division by zero protected in all calculations
* p-values reported to full precision (not rounded to 0 or 1)
* Confidence intervals always 95% unless configurable
* Effect sizes always reported alongside p-values (p-value alone is insufficient)
* Sample size warnings when n < 5 per group
* No custom statistical implementations — use scipy where available, pure Python fallback

---

## 6. CROSS-REFERENCES

| Need | Consult |
|------|---------|
| A/B test endpoint and request model | **API-Backend-Engineer** → `app.py` (`ABTestRequest`, `create_ab_test`) |
| Compare endpoint and ranking | **API-Backend-Engineer** → `app.py` (`run_multi_agent_comparison`) |
| Analytics SQL queries | **Data-Model-Architect** → `storage.py` (`get_analytics_summary`, `get_analytics_trends`, `get_score_distribution`) |
| How A/B results are displayed | **Frontend-UI-Engineer** → A/B Testing tab |
| How comparison matrix is rendered | **Frontend-UI-Engineer** → Compare tab |
| How trend/distribution charts work | **Frontend-UI-Engineer** → Analytics tab charts |
| Suite run that feeds A/B scores | **Test-Suite-Designer** → suite execution |

---

## 7. WHAT TO AVOID

* Custom t-distribution implementation when scipy is available — use the library
* Exact floating-point equality — always use epsilon tolerance
* Reporting p-value without effect size — both are needed for decisions
* Running A/B test with n=1 per group — report insufficient data
* Numpy types in JSON output — convert to native Python types
* Rounding p-values to 0.0 or 1.0 — preserve full precision
* Assuming equal variance — always use Welch's (unequal variance) variant

---

## 8. FUTURE EXTENSIONS

### 8.1 Planned Statistical Features
* Paired t-test (for same-input comparisons)
* ANOVA for multi-group comparison (3+ agents)
* Bonferroni correction for multiple comparisons
* Bootstrap confidence intervals (non-parametric)
* Bayesian A/B testing (posterior probability of improvement)

### 8.2 Regression Detection
* Compare current run scores against historical baseline
* Flag significant regressions (score drop > 2 standard deviations)
* Integrate with CI/CD alerting

---

## 9. TESTING STATISTICAL CODE

* Known equal means → p-value should be ~1.0, winner "tie"
* Known different means (large gap) → p-value < 0.05, clear winner
* Edge: n=1 per group → graceful handling, not a crash
* Edge: all identical scores → d=0, tie
* Verify against scipy.stats.ttest_ind(equal_var=False) for correctness
* All outputs must be JSON-serializable (no numpy types)

---

## END OF STATISTICAL ANALYSIS ENGINEER CHARTER
