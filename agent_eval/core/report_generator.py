"""
Report Generator for Lilly Agent Eval.

Generates beautiful HTML reports with Lilly brand design.
"""

import json
from datetime import datetime
from typing import List, Dict, Any, Optional
from dataclasses import dataclass


@dataclass
class ReportData:
    """Data for report generation."""
    title: str
    endpoint: str
    total_tests: int
    passed_tests: int
    failed_tests: int
    avg_score: float
    avg_latency_ms: float
    results: List[Dict[str, Any]]
    generated_at: str = None

    def __post_init__(self):
        if self.generated_at is None:
            self.generated_at = datetime.now().isoformat()


class ReportGenerator:
    """Generate beautiful HTML evaluation reports with Lilly branding."""

    @staticmethod
    def generate_html_report(data: ReportData) -> str:
        """Generate a Lilly-branded HTML report."""

        pass_rate = (data.passed_tests / data.total_tests * 100) if data.total_tests > 0 else 0

        # Generate test results rows
        results_html = ""
        for i, r in enumerate(data.results):
            status_class = "pass" if r.get("passed") else "fail"
            status_icon = "✓" if r.get("passed") else "✗"
            score = r.get("score", 0)

            # Generate evaluations breakdown
            evals_html = ""
            for e in r.get("evaluations", []):
                eval_status = "pass" if e.get("passed") else "fail"
                evals_html += f'''
                    <div class="eval-chip eval-{eval_status}">
                        <span class="eval-name">{e.get("metric", "").replace("_", " ").title()}</span>
                        <span class="eval-score">{e.get("score", 0)}%</span>
                    </div>
                '''

            results_html += f'''
                <div class="result-card {status_class}">
                    <div class="result-header">
                        <div class="result-status {status_class}">
                            <span class="status-icon">{status_icon}</span>
                            <span class="status-text">{"PASSED" if r.get("passed") else "FAILED"}</span>
                        </div>
                        <div class="result-meta">
                            <span class="result-score">{score}%</span>
                            <span class="result-latency">{r.get("latency_ms", 0)}ms</span>
                        </div>
                    </div>
                    <div class="result-content">
                        <div class="result-section">
                            <div class="section-label">Input</div>
                            <div class="section-value input-text">{_escape_html(r.get("input", ""))}</div>
                        </div>
                        <div class="result-section">
                            <div class="section-label">Agent Response</div>
                            <div class="section-value output-text">{_escape_html(r.get("output", ""))}</div>
                        </div>
                        {f'<div class="result-section"><div class="section-label">Expected</div><div class="section-value expected-text">{_escape_html(r.get("expected", ""))}</div></div>' if r.get("expected") else ""}
                    </div>
                    <div class="result-evaluations">
                        {evals_html}
                    </div>
                </div>
            '''

        html = f'''<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{_escape_html(data.title)} | Lilly Agent Eval</title>
    <style>
        * {{
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }}

        :root {{
            --lilly-red: #D52B1E;
            --lilly-red-dark: #B71C1C;
            --lilly-red-light: #FFEBEE;
            --success: #2E7D32;
            --success-light: #E8F5E9;
            --danger: #C62828;
            --danger-light: #FFEBEE;
            --warning: #F57C00;
            --bg: #FAFAFA;
            --card-bg: #FFFFFF;
            --text: #212121;
            --text-secondary: #616161;
            --text-light: #9E9E9E;
            --border: #E0E0E0;
            --border-light: #F5F5F5;
        }}

        body {{
            font-family: 'Segoe UI', -apple-system, BlinkMacSystemFont, 'Roboto', sans-serif;
            background: var(--bg);
            color: var(--text);
            line-height: 1.6;
            min-height: 100vh;
        }}

        .container {{
            max-width: 1100px;
            margin: 0 auto;
            padding: 2rem;
        }}

        /* Header */
        .report-header {{
            background: linear-gradient(135deg, var(--lilly-red) 0%, var(--lilly-red-dark) 100%);
            border-radius: 12px;
            padding: 2rem 2.5rem;
            margin-bottom: 2rem;
            color: white;
            box-shadow: 0 4px 20px rgba(213, 43, 30, 0.3);
        }}

        .header-top {{
            display: flex;
            justify-content: space-between;
            align-items: flex-start;
            margin-bottom: 1.5rem;
        }}

        .brand {{
            display: flex;
            align-items: center;
            gap: 0.75rem;
        }}

        .brand-logo {{
            width: 40px;
            height: 40px;
            background: white;
            border-radius: 8px;
            display: flex;
            align-items: center;
            justify-content: center;
            font-weight: 700;
            color: var(--lilly-red);
            font-size: 1.1rem;
        }}

        .brand-text {{
            font-size: 0.9rem;
            opacity: 0.9;
        }}

        .brand-name {{
            font-weight: 600;
            font-size: 1.1rem;
        }}

        .report-badge {{
            background: rgba(255,255,255,0.2);
            padding: 0.5rem 1rem;
            border-radius: 20px;
            font-size: 0.8rem;
            font-weight: 500;
        }}

        .report-title {{
            font-size: 1.75rem;
            font-weight: 600;
            margin-bottom: 0.5rem;
        }}

        .report-subtitle {{
            opacity: 0.9;
            font-size: 0.95rem;
        }}

        .report-meta {{
            display: flex;
            gap: 2rem;
            margin-top: 1.25rem;
            flex-wrap: wrap;
        }}

        .meta-item {{
            display: flex;
            align-items: center;
            gap: 0.5rem;
            font-size: 0.875rem;
            opacity: 0.9;
        }}

        /* Stats Grid */
        .stats-grid {{
            display: grid;
            grid-template-columns: repeat(5, 1fr);
            gap: 1rem;
            margin-bottom: 2rem;
        }}

        @media (max-width: 900px) {{
            .stats-grid {{
                grid-template-columns: repeat(3, 1fr);
            }}
        }}

        @media (max-width: 600px) {{
            .stats-grid {{
                grid-template-columns: repeat(2, 1fr);
            }}
        }}

        .stat-card {{
            background: var(--card-bg);
            border-radius: 10px;
            padding: 1.25rem;
            border: 1px solid var(--border);
            text-align: center;
            transition: transform 0.2s, box-shadow 0.2s;
        }}

        .stat-card:hover {{
            transform: translateY(-2px);
            box-shadow: 0 4px 15px rgba(0,0,0,0.08);
        }}

        .stat-value {{
            font-size: 2rem;
            font-weight: 700;
            margin-bottom: 0.25rem;
        }}

        .stat-value.success {{ color: var(--success); }}
        .stat-value.danger {{ color: var(--danger); }}
        .stat-value.primary {{ color: var(--lilly-red); }}

        .stat-label {{
            font-size: 0.75rem;
            text-transform: uppercase;
            letter-spacing: 0.05em;
            color: var(--text-secondary);
            font-weight: 500;
        }}

        /* Summary Section */
        .summary-section {{
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 1.5rem;
            margin-bottom: 2rem;
        }}

        @media (max-width: 700px) {{
            .summary-section {{
                grid-template-columns: 1fr;
            }}
        }}

        .summary-card {{
            background: var(--card-bg);
            border-radius: 10px;
            padding: 1.5rem;
            border: 1px solid var(--border);
        }}

        .summary-title {{
            font-size: 0.9rem;
            font-weight: 600;
            color: var(--text);
            margin-bottom: 1rem;
            display: flex;
            align-items: center;
            gap: 0.5rem;
        }}

        /* Pass Rate Circle */
        .pass-rate-container {{
            display: flex;
            align-items: center;
            gap: 2rem;
        }}

        .pass-rate-ring {{
            position: relative;
            width: 120px;
            height: 120px;
            flex-shrink: 0;
        }}

        .pass-rate-ring svg {{
            transform: rotate(-90deg);
        }}

        .pass-rate-ring circle {{
            fill: none;
            stroke-width: 10;
        }}

        .pass-rate-ring .bg {{
            stroke: var(--border-light);
        }}

        .pass-rate-ring .progress {{
            stroke: var(--success);
            stroke-linecap: round;
            transition: stroke-dashoffset 1s ease-out;
        }}

        .pass-rate-ring .progress.low {{
            stroke: var(--danger);
        }}

        .pass-rate-text {{
            position: absolute;
            top: 50%;
            left: 50%;
            transform: translate(-50%, -50%);
            text-align: center;
        }}

        .pass-rate-value {{
            font-size: 1.75rem;
            font-weight: 700;
            color: var(--success);
        }}

        .pass-rate-value.low {{
            color: var(--danger);
        }}

        .pass-rate-label {{
            font-size: 0.7rem;
            color: var(--text-light);
            text-transform: uppercase;
            letter-spacing: 0.05em;
        }}

        .pass-rate-details {{
            flex: 1;
        }}

        .pass-rate-stat {{
            display: flex;
            justify-content: space-between;
            padding: 0.5rem 0;
            border-bottom: 1px solid var(--border-light);
        }}

        .pass-rate-stat:last-child {{
            border-bottom: none;
        }}

        .pass-rate-stat-label {{
            color: var(--text-secondary);
            font-size: 0.875rem;
        }}

        .pass-rate-stat-value {{
            font-weight: 600;
        }}

        .pass-rate-stat-value.success {{ color: var(--success); }}
        .pass-rate-stat-value.danger {{ color: var(--danger); }}

        /* Score Distribution */
        .score-bar {{
            display: flex;
            height: 32px;
            border-radius: 6px;
            overflow: hidden;
            background: var(--border-light);
            margin-bottom: 1rem;
        }}

        .score-bar-segment {{
            display: flex;
            align-items: center;
            justify-content: center;
            font-size: 0.8rem;
            font-weight: 600;
            color: white;
            transition: width 0.5s ease-out;
        }}

        .score-bar-segment.pass {{
            background: var(--success);
        }}

        .score-bar-segment.fail {{
            background: var(--danger);
        }}

        .score-legend {{
            display: flex;
            justify-content: center;
            gap: 2rem;
        }}

        .legend-item {{
            display: flex;
            align-items: center;
            gap: 0.5rem;
            font-size: 0.875rem;
            color: var(--text-secondary);
        }}

        .legend-dot {{
            width: 12px;
            height: 12px;
            border-radius: 3px;
        }}

        .legend-dot.pass {{ background: var(--success); }}
        .legend-dot.fail {{ background: var(--danger); }}

        /* Results Section */
        .results-section {{
            margin-top: 2rem;
        }}

        .section-header {{
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 1rem;
            padding-bottom: 0.75rem;
            border-bottom: 2px solid var(--lilly-red);
        }}

        .section-title {{
            font-size: 1.1rem;
            font-weight: 600;
            color: var(--text);
        }}

        .result-card {{
            background: var(--card-bg);
            border-radius: 10px;
            margin-bottom: 1rem;
            border: 1px solid var(--border);
            overflow: hidden;
            transition: box-shadow 0.2s;
        }}

        .result-card:hover {{
            box-shadow: 0 4px 15px rgba(0,0,0,0.08);
        }}

        .result-card.pass {{
            border-left: 4px solid var(--success);
        }}

        .result-card.fail {{
            border-left: 4px solid var(--danger);
        }}

        .result-header {{
            display: flex;
            justify-content: space-between;
            align-items: center;
            padding: 1rem 1.25rem;
            background: var(--border-light);
        }}

        .result-status {{
            display: flex;
            align-items: center;
            gap: 0.5rem;
            font-weight: 600;
            font-size: 0.875rem;
        }}

        .result-status.pass {{ color: var(--success); }}
        .result-status.fail {{ color: var(--danger); }}

        .status-icon {{
            font-size: 1rem;
        }}

        .result-meta {{
            display: flex;
            gap: 1.5rem;
        }}

        .result-score {{
            font-weight: 700;
            font-size: 1rem;
            color: var(--lilly-red);
        }}

        .result-latency {{
            color: var(--text-light);
            font-size: 0.875rem;
        }}

        .result-content {{
            padding: 1.25rem;
        }}

        .result-section {{
            margin-bottom: 1rem;
        }}

        .result-section:last-child {{
            margin-bottom: 0;
        }}

        .section-label {{
            font-size: 0.7rem;
            text-transform: uppercase;
            letter-spacing: 0.05em;
            color: var(--text-light);
            margin-bottom: 0.375rem;
            font-weight: 600;
        }}

        .section-value {{
            font-size: 0.925rem;
            line-height: 1.6;
            color: var(--text);
        }}

        .input-text {{
            background: var(--bg);
            padding: 0.75rem 1rem;
            border-radius: 6px;
            font-family: 'SF Mono', 'Monaco', 'Menlo', monospace;
            font-size: 0.85rem;
            border: 1px solid var(--border-light);
        }}

        .output-text {{
            background: #FFF8E1;
            padding: 0.75rem 1rem;
            border-radius: 6px;
            border-left: 3px solid #FFB300;
        }}

        .expected-text {{
            background: var(--success-light);
            padding: 0.75rem 1rem;
            border-radius: 6px;
            border-left: 3px solid var(--success);
        }}

        .result-evaluations {{
            display: flex;
            flex-wrap: wrap;
            gap: 0.5rem;
            padding: 1rem 1.25rem;
            background: var(--bg);
            border-top: 1px solid var(--border);
        }}

        .eval-chip {{
            display: inline-flex;
            align-items: center;
            gap: 0.5rem;
            padding: 0.375rem 0.75rem;
            border-radius: 20px;
            font-size: 0.8rem;
        }}

        .eval-chip.eval-pass {{
            background: var(--success-light);
            color: var(--success);
        }}

        .eval-chip.eval-fail {{
            background: var(--danger-light);
            color: var(--danger);
        }}

        .eval-name {{
            font-weight: 500;
        }}

        .eval-score {{
            font-weight: 700;
        }}

        /* Footer */
        .report-footer {{
            text-align: center;
            padding: 2rem;
            color: var(--text-light);
            font-size: 0.875rem;
            border-top: 1px solid var(--border);
            margin-top: 2rem;
        }}

        .footer-brand {{
            font-weight: 600;
            color: var(--lilly-red);
        }}

        .footer-tagline {{
            font-size: 0.8rem;
            margin-top: 0.25rem;
        }}

        /* Print Styles */
        @media print {{
            body {{
                background: white;
            }}

            .container {{
                max-width: 100%;
                padding: 1rem;
            }}

            .report-header {{
                background: var(--lilly-red) !important;
                -webkit-print-color-adjust: exact;
                print-color-adjust: exact;
            }}

            .stat-card, .summary-card, .result-card {{
                break-inside: avoid;
            }}
        }}
    </style>
</head>
<body>
    <div class="container">
        <!-- Header -->
        <header class="report-header">
            <div class="header-top">
                <div class="brand">
                    <div class="brand-logo">Lilly</div>
                    <div>
                        <div class="brand-name">Agent Eval</div>
                        <div class="brand-text">Enterprise Evaluation Platform</div>
                    </div>
                </div>
                <div class="report-badge">Evaluation Report</div>
            </div>
            <h1 class="report-title">{_escape_html(data.title)}</h1>
            <p class="report-subtitle">Automated agent quality assessment</p>
            <div class="report-meta">
                <div class="meta-item">
                    <span>🔗</span>
                    <span>{_escape_html(data.endpoint)}</span>
                </div>
                <div class="meta-item">
                    <span>📅</span>
                    <span>{datetime.fromisoformat(data.generated_at).strftime("%B %d, %Y at %I:%M %p")}</span>
                </div>
                <div class="meta-item">
                    <span>📊</span>
                    <span>{data.total_tests} Test Cases</span>
                </div>
            </div>
        </header>

        <!-- Stats Grid -->
        <div class="stats-grid">
            <div class="stat-card">
                <div class="stat-value {'success' if pass_rate >= 70 else 'danger'}">{pass_rate:.0f}%</div>
                <div class="stat-label">Pass Rate</div>
            </div>
            <div class="stat-card">
                <div class="stat-value success">{data.passed_tests}</div>
                <div class="stat-label">Passed</div>
            </div>
            <div class="stat-card">
                <div class="stat-value danger">{data.failed_tests}</div>
                <div class="stat-label">Failed</div>
            </div>
            <div class="stat-card">
                <div class="stat-value primary">{data.avg_score:.0f}%</div>
                <div class="stat-label">Avg Score</div>
            </div>
            <div class="stat-card">
                <div class="stat-value">{data.avg_latency_ms:.0f}ms</div>
                <div class="stat-label">Avg Latency</div>
            </div>
        </div>

        <!-- Summary Section -->
        <div class="summary-section">
            <div class="summary-card">
                <h3 class="summary-title">📈 Pass Rate Overview</h3>
                <div class="pass-rate-container">
                    <div class="pass-rate-ring">
                        <svg width="120" height="120" viewBox="0 0 120 120">
                            <circle class="bg" cx="60" cy="60" r="52"></circle>
                            <circle class="progress {'low' if pass_rate < 70 else ''}" cx="60" cy="60" r="52"
                                stroke-dasharray="{327 * pass_rate / 100} 327"
                                stroke-dashoffset="0"></circle>
                        </svg>
                        <div class="pass-rate-text">
                            <div class="pass-rate-value {'low' if pass_rate < 70 else ''}">{pass_rate:.0f}%</div>
                            <div class="pass-rate-label">Pass Rate</div>
                        </div>
                    </div>
                    <div class="pass-rate-details">
                        <div class="pass-rate-stat">
                            <span class="pass-rate-stat-label">Total Tests</span>
                            <span class="pass-rate-stat-value">{data.total_tests}</span>
                        </div>
                        <div class="pass-rate-stat">
                            <span class="pass-rate-stat-label">Passed</span>
                            <span class="pass-rate-stat-value success">{data.passed_tests}</span>
                        </div>
                        <div class="pass-rate-stat">
                            <span class="pass-rate-stat-label">Failed</span>
                            <span class="pass-rate-stat-value danger">{data.failed_tests}</span>
                        </div>
                    </div>
                </div>
            </div>

            <div class="summary-card">
                <h3 class="summary-title">📊 Test Distribution</h3>
                <div class="score-bar">
                    <div class="score-bar-segment pass" style="width: {pass_rate}%">
                        {data.passed_tests if data.passed_tests > 0 else ''}
                    </div>
                    <div class="score-bar-segment fail" style="width: {100 - pass_rate}%">
                        {data.failed_tests if data.failed_tests > 0 else ''}
                    </div>
                </div>
                <div class="score-legend">
                    <div class="legend-item">
                        <div class="legend-dot pass"></div>
                        <span>Passed ({data.passed_tests})</span>
                    </div>
                    <div class="legend-item">
                        <div class="legend-dot fail"></div>
                        <span>Failed ({data.failed_tests})</span>
                    </div>
                </div>
            </div>
        </div>

        <!-- Results -->
        <section class="results-section">
            <div class="section-header">
                <h2 class="section-title">📋 Detailed Test Results</h2>
            </div>
            {results_html}
        </section>

        <!-- Footer -->
        <footer class="report-footer">
            <p>Generated by <span class="footer-brand">Lilly Agent Eval</span></p>
            <p class="footer-tagline">Enterprise Agent Evaluation Platform</p>
        </footer>
    </div>

    <script>
        // Animate progress ring on load
        document.addEventListener('DOMContentLoaded', function() {{
            const progress = document.querySelector('.pass-rate-ring .progress');
            if (progress) {{
                const circumference = 2 * Math.PI * 52;
                progress.style.strokeDasharray = circumference;
                progress.style.strokeDashoffset = circumference;
                setTimeout(() => {{
                    progress.style.transition = 'stroke-dashoffset 1s ease-out';
                    progress.style.strokeDashoffset = circumference - (circumference * {pass_rate} / 100);
                }}, 100);
            }}
        }});
    </script>
</body>
</html>'''

        return html

    @staticmethod
    def generate_json_report(data: ReportData) -> str:
        """Generate JSON report."""
        return json.dumps({
            "title": data.title,
            "endpoint": data.endpoint,
            "generated_at": data.generated_at,
            "summary": {
                "total_tests": data.total_tests,
                "passed_tests": data.passed_tests,
                "failed_tests": data.failed_tests,
                "pass_rate": round(data.passed_tests / data.total_tests * 100, 1) if data.total_tests > 0 else 0,
                "avg_score": data.avg_score,
                "avg_latency_ms": data.avg_latency_ms,
            },
            "results": data.results
        }, indent=2)


def _escape_html(text: str) -> str:
    """Escape HTML special characters."""
    if not text:
        return ""
    return (text
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&#39;"))
