"""
SQLite storage for Lilly Agent Eval.

Simple, single-file database for tests, suites, results, and batches.
"""

import sqlite3
import json
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Tuple
import os

from agent_eval.core.models import (
    Test, Suite, Result, Batch, EvalMetric,
    RegisteredAgent, ABComparison, MultiAgentBatch,
    AgentChain, ChainStep, ChainResult, ChainStepResult, ChainRun,
    ConversationTest, ConversationTurn, ConversationResult, ConversationTurnResult,
    Workflow, WorkflowAgent,
)


class Storage:
    """Simple SQLite storage for all evaluation data."""

    def __init__(self, db_path: Optional[str] = None):
        """
        Initialize storage.

        Args:
            db_path: Path to SQLite database. Defaults to ~/.agent_eval/data.db
                     Can also be set via LILLY_EVAL_DB environment variable.
        """
        if db_path is None:
            db_path = os.environ.get("LILLY_EVAL_DB")

        if db_path is None:
            db_dir = Path.home() / ".agent_eval"
            db_dir.mkdir(exist_ok=True)
            db_path = str(db_dir / "data.db")

        self.db_path = db_path
        self._init_db()

    def _get_conn(self) -> sqlite3.Connection:
        """Get database connection with row factory."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    @contextmanager
    def _conn(self):
        """Context-managed database connection (auto-closes on exit)."""
        conn = self._get_conn()
        try:
            yield conn
        finally:
            conn.close()

    def _init_db(self):
        """Initialize database schema."""
        conn = self._get_conn()
        conn.executescript("""
            -- Test Suites
            CREATE TABLE IF NOT EXISTS suites (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                description TEXT,
                endpoint TEXT,
                created_at TEXT,
                updated_at TEXT
            );

            -- Test Cases
            CREATE TABLE IF NOT EXISTS tests (
                id TEXT PRIMARY KEY,
                suite_id TEXT,
                name TEXT,
                input TEXT NOT NULL,
                expected TEXT,
                context TEXT,
                metrics TEXT,
                created_at TEXT,
                FOREIGN KEY (suite_id) REFERENCES suites(id) ON DELETE CASCADE
            );

            -- Evaluation Results
            CREATE TABLE IF NOT EXISTS results (
                id TEXT PRIMARY KEY,
                test_id TEXT,
                suite_id TEXT,
                batch_id TEXT,
                endpoint TEXT,
                input TEXT,
                output TEXT,
                score REAL,
                passed INTEGER,
                latency_ms INTEGER,
                evaluations TEXT,
                created_at TEXT
            );

            -- Batch Runs
            CREATE TABLE IF NOT EXISTS batches (
                id TEXT PRIMARY KEY,
                name TEXT,
                total_tests INTEGER,
                passed_tests INTEGER,
                avg_score REAL,
                created_at TEXT,
                completed_at TEXT
            );

            -- Indexes for common queries
            CREATE INDEX IF NOT EXISTS idx_results_created_at ON results(created_at DESC);
            CREATE INDEX IF NOT EXISTS idx_results_suite_id ON results(suite_id);
            CREATE INDEX IF NOT EXISTS idx_results_batch_id ON results(batch_id);
            CREATE INDEX IF NOT EXISTS idx_tests_suite_id ON tests(suite_id);

            -- Registered Agents (Multi-Agent Testing)
            CREATE TABLE IF NOT EXISTS agents (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                endpoint TEXT NOT NULL,
                description TEXT,
                agent_type TEXT DEFAULT 'simple',
                domain TEXT DEFAULT 'general',
                capabilities TEXT,
                auth_type TEXT DEFAULT 'none',
                auth_config TEXT,
                version TEXT,
                tags TEXT,
                is_active INTEGER DEFAULT 1,
                last_tested_at TEXT,
                created_at TEXT,
                updated_at TEXT
            );

            -- A/B Comparisons
            CREATE TABLE IF NOT EXISTS ab_comparisons (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                agent_a_id TEXT NOT NULL,
                agent_b_id TEXT NOT NULL,
                suite_id TEXT,
                status TEXT DEFAULT 'pending',
                agent_a_results TEXT,
                agent_b_results TEXT,
                winner TEXT,
                p_value REAL,
                effect_size REAL,
                created_at TEXT,
                completed_at TEXT
            );

            -- Multi-Agent Batches
            CREATE TABLE IF NOT EXISTS multi_agent_batches (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                agent_ids TEXT NOT NULL,
                suite_id TEXT,
                status TEXT DEFAULT 'pending',
                agent_results TEXT,
                best_agent_id TEXT,
                created_at TEXT,
                completed_at TEXT
            );

            -- Additional indexes
            CREATE INDEX IF NOT EXISTS idx_agents_active ON agents(is_active);
            CREATE INDEX IF NOT EXISTS idx_ab_status ON ab_comparisons(status);

            -- Agent Chains (Chain Testing)
            CREATE TABLE IF NOT EXISTS chains (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                description TEXT,
                steps TEXT NOT NULL,
                fail_fast INTEGER DEFAULT 0,
                created_at TEXT,
                updated_at TEXT
            );

            -- Chain Runs (executions of chains)
            CREATE TABLE IF NOT EXISTS chain_runs (
                id TEXT PRIMARY KEY,
                chain_id TEXT NOT NULL,
                name TEXT NOT NULL,
                suite_id TEXT,
                status TEXT DEFAULT 'pending',
                total_tests INTEGER DEFAULT 0,
                passed_tests INTEGER DEFAULT 0,
                avg_latency_ms REAL DEFAULT 0,
                routing_accuracy REAL,
                results TEXT,
                created_at TEXT,
                completed_at TEXT,
                FOREIGN KEY (chain_id) REFERENCES chains(id)
            );

            CREATE INDEX IF NOT EXISTS idx_chain_runs_chain_id ON chain_runs(chain_id);

            -- Conversation Tests (Multi-Turn)
            CREATE TABLE IF NOT EXISTS conversation_tests (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                description TEXT,
                endpoint TEXT,
                turns TEXT NOT NULL,
                context TEXT,
                suite_id TEXT,
                created_at TEXT
            );

            -- Conversation Results
            CREATE TABLE IF NOT EXISTS conversation_results (
                id TEXT PRIMARY KEY,
                conversation_id TEXT NOT NULL,
                endpoint TEXT NOT NULL,
                turn_results TEXT NOT NULL,
                total_turns INTEGER DEFAULT 0,
                passed_turns INTEGER DEFAULT 0,
                avg_score REAL DEFAULT 0,
                total_latency_ms INTEGER DEFAULT 0,
                coherence_score REAL DEFAULT 0,
                context_retention_score REAL DEFAULT 0,
                created_at TEXT,
                FOREIGN KEY (conversation_id) REFERENCES conversation_tests(id)
            );

            CREATE INDEX IF NOT EXISTS idx_conv_results_conv_id ON conversation_results(conversation_id);

            -- Workflows (multi-agent workflow definitions)
            CREATE TABLE IF NOT EXISTS workflows (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                description TEXT,
                orchestrator TEXT NOT NULL,
                sub_agents TEXT NOT NULL,
                test_suite_path TEXT,
                source TEXT DEFAULT 'yaml',
                source_file TEXT,
                created_at TEXT,
                updated_at TEXT
            );

            CREATE INDEX IF NOT EXISTS idx_workflows_name ON workflows(name);

            -- Baselines (for regression detection)
            CREATE TABLE IF NOT EXISTS baselines (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                agent_endpoint TEXT,
                suite_id TEXT,
                metrics_snapshot TEXT,
                total_tests INTEGER DEFAULT 0,
                passed_tests INTEGER DEFAULT 0,
                avg_score REAL DEFAULT 0,
                created_at TEXT
            );
        """)
        conn.commit()

        # Migrations — add columns idempotently
        for migration in [
            "ALTER TABLE results ADD COLUMN trajectory_data TEXT",
            "ALTER TABLE results ADD COLUMN rubric_data TEXT",
            "ALTER TABLE results ADD COLUMN expected TEXT",
        ]:
            try:
                conn.execute(migration)
                conn.commit()
            except Exception:
                pass  # Column already exists

        conn.close()

    # === Suite Operations ===

    def save_suite(self, suite: Suite) -> str:
        """Save a test suite."""
        conn = self._get_conn()
        conn.execute("""
            INSERT OR REPLACE INTO suites (id, name, description, endpoint, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (suite.id, suite.name, suite.description, suite.endpoint,
              suite.created_at, suite.updated_at))
        conn.commit()
        conn.close()
        return suite.id

    def get_suite(self, suite_id: str) -> Optional[Suite]:
        """Get a suite by ID with its tests."""
        conn = self._get_conn()
        row = conn.execute("SELECT * FROM suites WHERE id = ?", (suite_id,)).fetchone()
        if not row:
            conn.close()
            return None

        suite = Suite(
            id=row["id"],
            name=row["name"],
            description=row["description"],
            endpoint=row["endpoint"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

        # Load tests
        test_rows = conn.execute(
            "SELECT * FROM tests WHERE suite_id = ?", (suite_id,)
        ).fetchall()
        for tr in test_rows:
            suite.tests.append(Test(
                id=tr["id"],
                suite_id=tr["suite_id"],
                name=tr["name"],
                input=tr["input"],
                expected=tr["expected"],
                context=json.loads(tr["context"]) if tr["context"] else None,
                metrics=json.loads(tr["metrics"]) if tr["metrics"] else None,
                created_at=tr["created_at"],
            ))

        conn.close()
        return suite

    def list_suites(self) -> List[Suite]:
        """List all suites with test counts."""
        conn = self._get_conn()
        rows = conn.execute("""
            SELECT s.*, COUNT(t.id) as test_count
            FROM suites s
            LEFT JOIN tests t ON s.id = t.suite_id
            GROUP BY s.id
            ORDER BY s.updated_at DESC
        """).fetchall()

        suites = []
        for row in rows:
            suite = Suite(
                id=row["id"],
                name=row["name"],
                description=row["description"],
                endpoint=row["endpoint"],
                created_at=row["created_at"],
                updated_at=row["updated_at"],
            )
            # Add placeholder tests for count
            suite.tests = [None] * row["test_count"]
            suites.append(suite)

        conn.close()
        return suites

    def delete_suite(self, suite_id: str) -> bool:
        """Delete a suite and its tests."""
        conn = self._get_conn()
        conn.execute("DELETE FROM tests WHERE suite_id = ?", (suite_id,))
        conn.execute("DELETE FROM suites WHERE id = ?", (suite_id,))
        conn.commit()
        conn.close()
        return True

    # === Test Operations ===

    def save_test(self, test: Test) -> str:
        """Save a test case."""
        conn = self._get_conn()
        conn.execute("""
            INSERT OR REPLACE INTO tests (id, suite_id, name, input, expected, context, metrics, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            test.id, test.suite_id, test.name, test.input, test.expected,
            json.dumps(test.context) if test.context else None,
            json.dumps(test.metrics) if test.metrics else None,
            test.created_at
        ))
        conn.commit()
        conn.close()
        return test.id

    def delete_test(self, test_id: str) -> bool:
        """Delete a test case."""
        conn = self._get_conn()
        conn.execute("DELETE FROM tests WHERE id = ?", (test_id,))
        conn.commit()
        conn.close()
        return True

    # === Result Operations ===

    def save_result(self, result: Result) -> str:
        """Save an evaluation result."""
        conn = self._get_conn()
        evaluations_json = json.dumps([
            {"metric": e.metric, "score": e.score, "passed": e.passed, "reason": e.reason}
            for e in result.evaluations
        ])
        trajectory_json = json.dumps(result.trajectory_result) if result.trajectory_result else None
        rubric_json = json.dumps(result.rubric_results) if result.rubric_results else None
        conn.execute("""
            INSERT INTO results (id, test_id, suite_id, batch_id, endpoint, input, output,
                                score, passed, latency_ms, evaluations, created_at,
                                trajectory_data, rubric_data, expected)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            result.id, result.test_id, result.suite_id, result.batch_id,
            result.endpoint, result.input, result.output, result.score,
            1 if result.passed else 0, result.latency_ms, evaluations_json,
            result.created_at, trajectory_json, rubric_json, result.expected
        ))
        conn.commit()
        conn.close()
        return result.id

    def get_history(self, limit: int = 50) -> List[Result]:
        """Get recent evaluation results."""
        conn = self._get_conn()
        rows = conn.execute("""
            SELECT * FROM results ORDER BY created_at DESC LIMIT ?
        """, (limit,)).fetchall()

        results = []
        for row in rows:
            evals_data = json.loads(row["evaluations"]) if row["evaluations"] else []
            evaluations = [
                EvalMetric(
                    metric=e["metric"],
                    score=e["score"],
                    passed=e["passed"],
                    reason=e["reason"]
                )
                for e in evals_data
            ]
            results.append(Result(
                id=row["id"],
                test_id=row["test_id"],
                suite_id=row["suite_id"],
                batch_id=row["batch_id"],
                endpoint=row["endpoint"],
                input=row["input"],
                output=row["output"],
                score=row["score"],
                passed=bool(row["passed"]),
                latency_ms=row["latency_ms"],
                evaluations=evaluations,
                created_at=row["created_at"],
            ))

        conn.close()
        return results

    def get_history_paginated(
        self,
        page: int = 1,
        per_page: int = 20,
        days: int = 90,
        status: Optional[str] = None,
        agent_id: Optional[str] = None,
    ) -> Tuple[List[Result], int]:
        """Get paginated evaluation results with filters."""
        conn = self._get_conn()

        # Build query with filters
        where_clauses = []
        params = []

        # Date filter (last N days)
        where_clauses.append("created_at >= datetime('now', ?)")
        params.append(f'-{days} days')

        # Status filter
        if status == 'passed':
            where_clauses.append("passed = 1")
        elif status == 'failed':
            where_clauses.append("passed = 0")

        # Agent filter (by endpoint pattern - agent_id stored in endpoint)
        if agent_id:
            # Get agent endpoint to filter
            agent = self.get_agent(agent_id)
            if agent:
                where_clauses.append("endpoint = ?")
                params.append(agent.endpoint)

        where_sql = " AND ".join(where_clauses) if where_clauses else "1=1"

        # Get total count
        count_sql = f"SELECT COUNT(*) FROM results WHERE {where_sql}"
        total = conn.execute(count_sql, params).fetchone()[0]

        # Get paginated results
        offset = (page - 1) * per_page
        query_params = params + [per_page, offset]
        rows = conn.execute(f"""
            SELECT * FROM results
            WHERE {where_sql}
            ORDER BY created_at DESC
            LIMIT ? OFFSET ?
        """, query_params).fetchall()

        results = []
        for row in rows:
            evals_data = json.loads(row["evaluations"]) if row["evaluations"] else []
            evaluations = [
                EvalMetric(
                    metric=e["metric"],
                    score=e["score"],
                    passed=e["passed"],
                    reason=e["reason"]
                )
                for e in evals_data
            ]
            results.append(Result(
                id=row["id"],
                test_id=row["test_id"],
                suite_id=row["suite_id"],
                batch_id=row["batch_id"],
                endpoint=row["endpoint"],
                input=row["input"],
                output=row["output"],
                score=row["score"],
                passed=bool(row["passed"]),
                latency_ms=row["latency_ms"],
                evaluations=evaluations,
                created_at=row["created_at"],
            ))

        conn.close()
        return results, total

    def get_results_by_suite(self, suite_id: str, limit: int = 100) -> List[Result]:
        """Get results for a specific suite."""
        conn = self._get_conn()
        rows = conn.execute("""
            SELECT * FROM results WHERE suite_id = ? ORDER BY created_at DESC LIMIT ?
        """, (suite_id, limit)).fetchall()

        results = []
        for row in rows:
            evals_data = json.loads(row["evaluations"]) if row["evaluations"] else []
            evaluations = [
                EvalMetric(metric=e["metric"], score=e["score"], passed=e["passed"], reason=e["reason"])
                for e in evals_data
            ]
            results.append(Result(
                id=row["id"],
                test_id=row["test_id"],
                suite_id=row["suite_id"],
                batch_id=row["batch_id"],
                endpoint=row["endpoint"],
                input=row["input"],
                output=row["output"],
                score=row["score"],
                passed=bool(row["passed"]),
                latency_ms=row["latency_ms"],
                evaluations=evaluations,
                created_at=row["created_at"],
            ))

        conn.close()
        return results

    # === Batch Operations ===

    def save_batch(self, batch: Batch) -> str:
        """Save a batch run."""
        conn = self._get_conn()
        conn.execute("""
            INSERT OR REPLACE INTO batches (id, name, total_tests, passed_tests, avg_score, created_at, completed_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (batch.id, batch.name, batch.total_tests, batch.passed_tests,
              batch.avg_score, batch.created_at, batch.completed_at))
        conn.commit()
        conn.close()
        return batch.id

    def get_batch(self, batch_id: str) -> Optional[Batch]:
        """Get a batch by ID."""
        conn = self._get_conn()
        row = conn.execute("SELECT * FROM batches WHERE id = ?", (batch_id,)).fetchone()
        conn.close()
        if not row:
            return None
        return Batch(
            id=row["id"],
            name=row["name"],
            total_tests=row["total_tests"],
            passed_tests=row["passed_tests"],
            avg_score=row["avg_score"],
            created_at=row["created_at"],
            completed_at=row["completed_at"],
        )

    def get_batch_results(self, batch_id: str) -> List[Result]:
        """Get all results for a specific batch."""
        conn = self._get_conn()
        rows = conn.execute(
            "SELECT * FROM results WHERE batch_id = ? ORDER BY created_at DESC",
            (batch_id,)
        ).fetchall()
        conn.close()
        return [self._row_to_result(row) for row in rows]

    def get_suite_results(self, suite_id: str) -> List[Result]:
        """Get all results for a specific suite."""
        return self.get_results_by_suite(suite_id)

    def get_result(self, result_id: str) -> Optional[Result]:
        """Get a single result by ID."""
        conn = self._get_conn()
        row = conn.execute("SELECT * FROM results WHERE id = ?", (result_id,)).fetchone()
        conn.close()
        if not row:
            return None
        return self._row_to_result(row)

    def _row_to_result(self, row) -> Result:
        """Convert a database row to a Result object."""
        keys = row.keys()
        trajectory_data = None
        rubric_data = None
        if "trajectory_data" in keys and row["trajectory_data"]:
            try:
                trajectory_data = json.loads(row["trajectory_data"])
            except (json.JSONDecodeError, TypeError):
                pass
        if "rubric_data" in keys and row["rubric_data"]:
            try:
                rubric_data = json.loads(row["rubric_data"])
            except (json.JSONDecodeError, TypeError):
                pass

        # Deserialise evaluations as EvalMetric objects (not raw dicts)
        evals_data = []
        if row["evaluations"]:
            try:
                raw = json.loads(row["evaluations"])
                evals_data = [
                    EvalMetric(
                        metric=e.get("metric", ""),
                        score=e.get("score", 0),
                        passed=bool(e.get("passed", False)),
                        reason=e.get("reason", ""),
                    )
                    for e in (raw if isinstance(raw, list) else [])
                ]
            except (json.JSONDecodeError, TypeError, AttributeError):
                pass

        return Result(
            id=row["id"],
            test_id=row["test_id"],
            suite_id=row["suite_id"],
            batch_id=row["batch_id"],
            endpoint=row["endpoint"],
            input=row["input"],
            output=row["output"],
            expected=row["expected"] if "expected" in keys else None,
            score=row["score"],
            passed=bool(row["passed"]),
            latency_ms=row["latency_ms"],
            evaluations=evals_data,
            trajectory_result=trajectory_data,
            rubric_results=rubric_data,
            created_at=row["created_at"],
        )

    # === Analytics ===

    def get_analytics_summary(self, days: int = 30, agent_id: str = None, suite_id: str = None) -> dict:
        """Get summary statistics for analytics dashboard."""
        conn = self._get_conn()

        # Build WHERE clause for filtering
        conditions = ["created_at >= datetime('now', ?)"]
        params = [f'-{days} days']
        if agent_id:
            agent_row = conn.execute("SELECT endpoint FROM agents WHERE id = ?", (agent_id,)).fetchone()
            if agent_row:
                conditions.append("endpoint = ?")
                params.append(agent_row["endpoint"])
        if suite_id:
            conditions.append("suite_id = ?")
            params.append(suite_id)
        where = " AND ".join(conditions)

        # Total counts
        total_tests = conn.execute(f"SELECT COUNT(*) FROM results WHERE {where}", params).fetchone()[0]
        passed_tests = conn.execute(f"SELECT COUNT(*) FROM results WHERE {where} AND passed = 1", params).fetchone()[0]
        total_suites = conn.execute("SELECT COUNT(*) FROM suites").fetchone()[0]

        # Average score
        avg_score_row = conn.execute(f"SELECT AVG(score) FROM results WHERE {where}", params).fetchone()
        avg_score = avg_score_row[0] if avg_score_row[0] else 0

        # Average latency
        avg_latency_row = conn.execute(f"SELECT AVG(latency_ms) FROM results WHERE {where}", params).fetchone()
        avg_latency = avg_latency_row[0] if avg_latency_row[0] else 0

        conn.close()

        return {
            "total_tests": total_tests,
            "passed_tests": passed_tests,
            "failed_tests": total_tests - passed_tests,
            "pass_rate": (passed_tests / total_tests * 100) if total_tests > 0 else 0,
            "avg_score": round(avg_score, 1),
            "avg_latency_ms": round(avg_latency),
            "total_suites": total_suites,
        }

    def get_analytics_trends(self, days: int = 30, agent_id: str = None, suite_id: str = None) -> List[dict]:
        """Get daily pass rate trends."""
        conn = self._get_conn()

        conditions = ["created_at >= datetime('now', ?)"]
        params = [f'-{days} days']
        if agent_id:
            agent_row = conn.execute("SELECT endpoint FROM agents WHERE id = ?", (agent_id,)).fetchone()
            if agent_row:
                conditions.append("endpoint = ?")
                params.append(agent_row["endpoint"])
        if suite_id:
            conditions.append("suite_id = ?")
            params.append(suite_id)
        where = " AND ".join(conditions)

        rows = conn.execute(f"""
            SELECT
                DATE(created_at) as date,
                COUNT(*) as total,
                SUM(CASE WHEN passed = 1 THEN 1 ELSE 0 END) as passed,
                AVG(score) as avg_score,
                AVG(latency_ms) as avg_latency
            FROM results
            WHERE {where}
            GROUP BY DATE(created_at)
            ORDER BY date
        """, params).fetchall()

        conn.close()

        return [
            {
                "date": row["date"],
                "total": row["total"],
                "passed": row["passed"],
                "pass_rate": (row["passed"] / row["total"] * 100) if row["total"] > 0 else 0,
                "avg_score": round(row["avg_score"], 1) if row["avg_score"] else 0,
                "avg_latency": round(row["avg_latency"]) if row["avg_latency"] else 0,
            }
            for row in rows
        ]

    def get_score_distribution(self, days: int = 30, agent_id: str = None, suite_id: str = None) -> dict:
        """Get score distribution for histogram."""
        conn = self._get_conn()

        conditions = ["created_at >= datetime('now', ?)"]
        params = [f'-{days} days']
        if agent_id:
            agent_row = conn.execute("SELECT endpoint FROM agents WHERE id = ?", (agent_id,)).fetchone()
            if agent_row:
                conditions.append("endpoint = ?")
                params.append(agent_row["endpoint"])
        if suite_id:
            conditions.append("suite_id = ?")
            params.append(suite_id)
        where = " AND ".join(conditions)

        rows = conn.execute(f"""
            SELECT
                CASE
                    WHEN score >= 90 THEN '90-100'
                    WHEN score >= 80 THEN '80-89'
                    WHEN score >= 70 THEN '70-79'
                    WHEN score >= 60 THEN '60-69'
                    WHEN score >= 50 THEN '50-59'
                    ELSE '0-49'
                END as bucket,
                COUNT(*) as count
            FROM results
            WHERE {where}
            GROUP BY bucket
            ORDER BY bucket DESC
        """, params).fetchall()

        conn.close()

        return {row["bucket"]: row["count"] for row in rows}

    # === Agent Registry Operations ===

    def save_agent(self, agent: RegisteredAgent) -> str:
        """Save or update a registered agent."""
        conn = self._get_conn()
        conn.execute("""
            INSERT OR REPLACE INTO agents
            (id, name, endpoint, description, agent_type, domain, capabilities,
             auth_type, auth_config, version, tags, is_active, last_tested_at, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            agent.id, agent.name, agent.endpoint, agent.description,
            agent.agent_type, agent.domain,
            json.dumps(agent.capabilities) if agent.capabilities else None,
            agent.auth_type,
            json.dumps(agent.auth_config) if agent.auth_config else None,
            agent.version,
            json.dumps(agent.tags) if agent.tags else None,
            1 if agent.is_active else 0,
            agent.last_tested_at, agent.created_at, agent.updated_at
        ))
        conn.commit()
        conn.close()
        return agent.id

    def get_agent(self, agent_id: str) -> Optional[RegisteredAgent]:
        """Get agent by ID."""
        conn = self._get_conn()
        row = conn.execute("SELECT * FROM agents WHERE id = ?", (agent_id,)).fetchone()
        conn.close()
        if not row:
            return None
        return self._row_to_agent(row)

    def get_agent_by_endpoint(self, endpoint: str) -> Optional[RegisteredAgent]:
        """Find agent by endpoint URL (avoids duplicate registrations)."""
        conn = self._get_conn()
        row = conn.execute("SELECT * FROM agents WHERE endpoint = ?", (endpoint,)).fetchone()
        conn.close()
        if not row:
            return None
        return self._row_to_agent(row)

    def list_agents(self, active_only: bool = True, tag: Optional[str] = None) -> List[RegisteredAgent]:
        """List all registered agents."""
        conn = self._get_conn()
        if active_only:
            rows = conn.execute(
                "SELECT * FROM agents WHERE is_active = 1 ORDER BY updated_at DESC"
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM agents ORDER BY updated_at DESC"
            ).fetchall()
        conn.close()

        agents = [self._row_to_agent(row) for row in rows]

        # Filter by tag if specified
        if tag:
            agents = [a for a in agents if a.tags and tag in a.tags]

        return agents

    def delete_agent(self, agent_id: str) -> bool:
        """Delete an agent."""
        conn = self._get_conn()
        conn.execute("DELETE FROM agents WHERE id = ?", (agent_id,))
        conn.commit()
        conn.close()
        return True

    def update_agent_last_tested(self, agent_id: str) -> None:
        """Update the last_tested_at timestamp for an agent."""
        conn = self._get_conn()
        conn.execute(
            "UPDATE agents SET last_tested_at = ? WHERE id = ?",
            (datetime.utcnow().isoformat(), agent_id)
        )
        conn.commit()
        conn.close()

    def _row_to_agent(self, row) -> RegisteredAgent:
        """Convert a database row to a RegisteredAgent object."""
        return RegisteredAgent(
            id=row["id"],
            name=row["name"],
            endpoint=row["endpoint"],
            description=row["description"],
            agent_type=row["agent_type"] or "simple",
            domain=row["domain"] or "general",
            capabilities=json.loads(row["capabilities"]) if row["capabilities"] else None,
            auth_type=row["auth_type"] or "none",
            auth_config=json.loads(row["auth_config"]) if row["auth_config"] else None,
            version=row["version"],
            tags=json.loads(row["tags"]) if row["tags"] else None,
            is_active=bool(row["is_active"]),
            last_tested_at=row["last_tested_at"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    # === A/B Comparison Operations ===

    def save_ab_comparison(self, comparison: ABComparison) -> str:
        """Save an A/B comparison."""
        conn = self._get_conn()
        conn.execute("""
            INSERT OR REPLACE INTO ab_comparisons
            (id, name, agent_a_id, agent_b_id, suite_id, status,
             agent_a_results, agent_b_results, winner, p_value, effect_size,
             created_at, completed_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            comparison.id, comparison.name, comparison.agent_a_id, comparison.agent_b_id,
            comparison.suite_id, comparison.status,
            json.dumps(comparison.agent_a_results) if comparison.agent_a_results else None,
            json.dumps(comparison.agent_b_results) if comparison.agent_b_results else None,
            comparison.winner, comparison.p_value, comparison.effect_size,
            comparison.created_at, comparison.completed_at
        ))
        conn.commit()
        conn.close()
        return comparison.id

    def get_ab_comparison(self, comparison_id: str) -> Optional[ABComparison]:
        """Get A/B comparison by ID."""
        conn = self._get_conn()
        row = conn.execute(
            "SELECT * FROM ab_comparisons WHERE id = ?", (comparison_id,)
        ).fetchone()
        conn.close()
        if not row:
            return None
        return self._row_to_ab_comparison(row)

    def list_ab_comparisons(self, limit: int = 50) -> List[ABComparison]:
        """List recent A/B comparisons."""
        conn = self._get_conn()
        rows = conn.execute(
            "SELECT * FROM ab_comparisons ORDER BY created_at DESC LIMIT ?",
            (limit,)
        ).fetchall()
        conn.close()
        return [self._row_to_ab_comparison(row) for row in rows]

    def _row_to_ab_comparison(self, row) -> ABComparison:
        """Convert a database row to an ABComparison object."""
        return ABComparison(
            id=row["id"],
            name=row["name"],
            agent_a_id=row["agent_a_id"],
            agent_b_id=row["agent_b_id"],
            suite_id=row["suite_id"],
            status=row["status"],
            agent_a_results=json.loads(row["agent_a_results"]) if row["agent_a_results"] else None,
            agent_b_results=json.loads(row["agent_b_results"]) if row["agent_b_results"] else None,
            winner=row["winner"],
            p_value=row["p_value"],
            effect_size=row["effect_size"],
            created_at=row["created_at"],
            completed_at=row["completed_at"],
        )

    # === Multi-Agent Batch Operations ===

    def save_multi_batch(self, batch: MultiAgentBatch) -> str:
        """Save a multi-agent batch comparison."""
        conn = self._get_conn()
        conn.execute("""
            INSERT OR REPLACE INTO multi_agent_batches
            (id, name, agent_ids, suite_id, status, agent_results, best_agent_id, created_at, completed_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            batch.id, batch.name,
            json.dumps(batch.agent_ids),
            batch.suite_id, batch.status,
            json.dumps(batch.agent_results) if batch.agent_results else None,
            batch.best_agent_id, batch.created_at, batch.completed_at
        ))
        conn.commit()
        conn.close()
        return batch.id

    def get_multi_batch(self, batch_id: str) -> Optional[MultiAgentBatch]:
        """Get multi-agent batch by ID."""
        conn = self._get_conn()
        row = conn.execute(
            "SELECT * FROM multi_agent_batches WHERE id = ?", (batch_id,)
        ).fetchone()
        conn.close()
        if not row:
            return None
        return MultiAgentBatch(
            id=row["id"],
            name=row["name"],
            agent_ids=json.loads(row["agent_ids"]),
            suite_id=row["suite_id"],
            status=row["status"],
            agent_results=json.loads(row["agent_results"]) if row["agent_results"] else {},
            best_agent_id=row["best_agent_id"],
            created_at=row["created_at"],
            completed_at=row["completed_at"],
        )

    def list_multi_batches(self, limit: int = 50) -> List[MultiAgentBatch]:
        """List recent multi-agent batches."""
        conn = self._get_conn()
        rows = conn.execute(
            "SELECT * FROM multi_agent_batches ORDER BY created_at DESC LIMIT ?",
            (limit,)
        ).fetchall()
        conn.close()
        return [
            MultiAgentBatch(
                id=row["id"],
                name=row["name"],
                agent_ids=json.loads(row["agent_ids"]),
                suite_id=row["suite_id"],
                status=row["status"],
                agent_results=json.loads(row["agent_results"]) if row["agent_results"] else {},
                best_agent_id=row["best_agent_id"],
                created_at=row["created_at"],
                completed_at=row["completed_at"],
            )
            for row in rows
        ]

    # === Agent Chain Operations ===

    def save_chain(self, chain: AgentChain) -> str:
        """Save or update an agent chain."""
        conn = self._get_conn()
        steps_json = json.dumps([s.to_dict() for s in chain.steps])
        conn.execute("""
            INSERT OR REPLACE INTO chains
            (id, name, description, steps, fail_fast, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (
            chain.id, chain.name, chain.description, steps_json,
            1 if chain.fail_fast else 0, chain.created_at, chain.updated_at
        ))
        conn.commit()
        conn.close()
        return chain.id

    def get_chain(self, chain_id: str) -> Optional[AgentChain]:
        """Get chain by ID."""
        conn = self._get_conn()
        row = conn.execute("SELECT * FROM chains WHERE id = ?", (chain_id,)).fetchone()
        conn.close()
        if not row:
            return None
        return self._row_to_chain(row)

    def list_chains(self) -> List[AgentChain]:
        """List all agent chains."""
        conn = self._get_conn()
        rows = conn.execute("SELECT * FROM chains ORDER BY updated_at DESC").fetchall()
        conn.close()
        return [self._row_to_chain(row) for row in rows]

    def delete_chain(self, chain_id: str) -> bool:
        """Delete a chain."""
        conn = self._get_conn()
        conn.execute("DELETE FROM chain_runs WHERE chain_id = ?", (chain_id,))
        conn.execute("DELETE FROM chains WHERE id = ?", (chain_id,))
        conn.commit()
        conn.close()
        return True

    def _row_to_chain(self, row) -> AgentChain:
        """Convert a database row to an AgentChain object."""
        steps_data = json.loads(row["steps"]) if row["steps"] else []
        steps = [
            ChainStep(
                agent_id=s["agent_id"],
                order=s.get("order", i),
                input_mapping=s.get("input_mapping", "previous_output"),
                input_template=s.get("input_template"),
                expected_routing=s.get("expected_routing"),
            )
            for i, s in enumerate(steps_data)
        ]
        return AgentChain(
            id=row["id"],
            name=row["name"],
            description=row["description"],
            steps=steps,
            fail_fast=bool(row["fail_fast"]),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    # === Chain Run Operations ===

    def save_chain_run(self, run: ChainRun) -> str:
        """Save a chain run."""
        conn = self._get_conn()
        results_json = json.dumps([r.to_dict() for r in run.results]) if run.results else None
        conn.execute("""
            INSERT OR REPLACE INTO chain_runs
            (id, chain_id, name, suite_id, status, total_tests, passed_tests,
             avg_latency_ms, routing_accuracy, results, created_at, completed_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            run.id, run.chain_id, run.name, run.suite_id, run.status,
            run.total_tests, run.passed_tests, run.avg_latency_ms,
            run.routing_accuracy, results_json, run.created_at, run.completed_at
        ))
        conn.commit()
        conn.close()
        return run.id

    def get_chain_run(self, run_id: str) -> Optional[ChainRun]:
        """Get chain run by ID."""
        conn = self._get_conn()
        row = conn.execute("SELECT * FROM chain_runs WHERE id = ?", (run_id,)).fetchone()
        conn.close()
        if not row:
            return None
        return self._row_to_chain_run(row)

    def list_chain_runs(self, chain_id: Optional[str] = None, limit: int = 50) -> List[ChainRun]:
        """List chain runs, optionally filtered by chain_id."""
        conn = self._get_conn()
        if chain_id:
            rows = conn.execute(
                "SELECT * FROM chain_runs WHERE chain_id = ? ORDER BY created_at DESC LIMIT ?",
                (chain_id, limit)
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM chain_runs ORDER BY created_at DESC LIMIT ?",
                (limit,)
            ).fetchall()
        conn.close()
        return [self._row_to_chain_run(row) for row in rows]

    def _row_to_chain_run(self, row) -> ChainRun:
        """Convert a database row to a ChainRun object."""
        results_data = json.loads(row["results"]) if row["results"] else []
        results = []
        for r in results_data:
            step_results = [
                ChainStepResult(
                    agent_id=s["agent_id"],
                    agent_name=s["agent_name"],
                    input=s["input"],
                    output=s["output"],
                    latency_ms=s["latency_ms"],
                    success=s["success"],
                    error=s.get("error"),
                )
                for s in r.get("step_results", [])
            ]
            results.append(ChainResult(
                id=r.get("id", ""),
                chain_id=r["chain_id"],
                test_input=r["test_input"],
                final_output=r["final_output"],
                step_results=step_results,
                total_latency_ms=r.get("total_latency_ms", 0),
                success=r.get("success", True),
                routing_correct=r.get("routing_correct"),
                created_at=r.get("created_at", ""),
            ))
        return ChainRun(
            id=row["id"],
            chain_id=row["chain_id"],
            name=row["name"],
            suite_id=row["suite_id"],
            status=row["status"],
            total_tests=row["total_tests"],
            passed_tests=row["passed_tests"],
            avg_latency_ms=row["avg_latency_ms"],
            routing_accuracy=row["routing_accuracy"],
            results=results,
            created_at=row["created_at"],
            completed_at=row["completed_at"],
        )

    # === Workflow Operations ===

    def save_workflow(self, workflow: Workflow) -> str:
        """Save or update a workflow."""
        conn = self._get_conn()
        conn.execute("""
            INSERT OR REPLACE INTO workflows
            (id, name, description, orchestrator, sub_agents, test_suite_path,
             source, source_file, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            workflow.id, workflow.name, workflow.description,
            json.dumps(workflow.orchestrator.to_dict()),
            json.dumps([a.to_dict() for a in workflow.sub_agents]),
            workflow.test_suite_path, workflow.source, workflow.source_file,
            workflow.created_at, workflow.updated_at,
        ))
        conn.commit()
        conn.close()
        return workflow.id

    def get_workflow(self, workflow_id: str) -> Optional[Workflow]:
        """Get workflow by ID."""
        conn = self._get_conn()
        row = conn.execute("SELECT * FROM workflows WHERE id = ?", (workflow_id,)).fetchone()
        conn.close()
        if not row:
            return None
        return self._row_to_workflow(row)

    def get_workflow_by_name(self, name: str) -> Optional[Workflow]:
        """Find workflow by name (avoids duplicate YAML registrations)."""
        conn = self._get_conn()
        row = conn.execute("SELECT * FROM workflows WHERE name = ?", (name,)).fetchone()
        conn.close()
        if not row:
            return None
        return self._row_to_workflow(row)

    def list_workflows(self) -> List[Workflow]:
        """List all workflows."""
        conn = self._get_conn()
        rows = conn.execute("SELECT * FROM workflows ORDER BY updated_at DESC").fetchall()
        conn.close()
        return [self._row_to_workflow(row) for row in rows]

    def delete_workflow(self, workflow_id: str) -> bool:
        """Delete a workflow."""
        conn = self._get_conn()
        conn.execute("DELETE FROM workflows WHERE id = ?", (workflow_id,))
        conn.commit()
        conn.close()
        return True

    def _row_to_workflow(self, row) -> Workflow:
        """Convert a database row to a Workflow object."""
        orch_data = json.loads(row["orchestrator"]) if row["orchestrator"] else {}
        orchestrator = WorkflowAgent(
            name=orch_data.get("name", ""),
            endpoint=orch_data.get("endpoint", ""),
            health_path=orch_data.get("health_path", "/health"),
            role="orchestrator",
            tags=orch_data.get("tags"),
        )
        sub_data = json.loads(row["sub_agents"]) if row["sub_agents"] else []
        sub_agents = [
            WorkflowAgent(
                name=s.get("name", ""),
                endpoint=s.get("endpoint", ""),
                health_path=s.get("health_path", "/health"),
                role="sub_agent",
                tags=s.get("tags"),
            )
            for s in sub_data
        ]
        return Workflow(
            id=row["id"],
            name=row["name"],
            description=row["description"],
            orchestrator=orchestrator,
            sub_agents=sub_agents,
            test_suite_path=row["test_suite_path"],
            source=row["source"],
            source_file=row["source_file"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    # === Conversation Test Operations ===

    def save_conversation_test(self, conv: ConversationTest) -> str:
        """Save a conversation test."""
        conn = self._get_conn()
        turns_json = json.dumps([t.to_dict() for t in conv.turns])
        conn.execute("""
            INSERT OR REPLACE INTO conversation_tests
            (id, name, description, endpoint, turns, context, suite_id, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            conv.id, conv.name, conv.description, conv.endpoint,
            turns_json,
            json.dumps(conv.context) if conv.context else None,
            conv.suite_id, conv.created_at
        ))
        conn.commit()
        conn.close()
        return conv.id

    def get_conversation_test(self, conv_id: str) -> Optional[ConversationTest]:
        """Get a conversation test by ID."""
        conn = self._get_conn()
        row = conn.execute(
            "SELECT * FROM conversation_tests WHERE id = ?", (conv_id,)
        ).fetchone()
        conn.close()
        if not row:
            return None
        return self._row_to_conversation_test(row)

    def list_conversation_tests(self) -> List[ConversationTest]:
        """List all conversation tests."""
        conn = self._get_conn()
        rows = conn.execute(
            "SELECT * FROM conversation_tests ORDER BY created_at DESC"
        ).fetchall()
        conn.close()
        return [self._row_to_conversation_test(row) for row in rows]

    def delete_conversation_test(self, conv_id: str) -> bool:
        """Delete a conversation test and its results."""
        conn = self._get_conn()
        conn.execute("DELETE FROM conversation_results WHERE conversation_id = ?", (conv_id,))
        conn.execute("DELETE FROM conversation_tests WHERE id = ?", (conv_id,))
        conn.commit()
        conn.close()
        return True

    def _row_to_conversation_test(self, row) -> ConversationTest:
        """Convert a database row to a ConversationTest."""
        turns_data = json.loads(row["turns"]) if row["turns"] else []
        turns = [
            ConversationTurn(
                role=t["role"],
                content=t["content"],
                expected=t.get("expected"),
                check_metrics=t.get("check_metrics"),
                expected_tool_calls=t.get("expected_tool_calls"),
            )
            for t in turns_data
        ]
        return ConversationTest(
            id=row["id"],
            name=row["name"],
            description=row["description"],
            endpoint=row["endpoint"],
            turns=turns,
            context=json.loads(row["context"]) if row["context"] else None,
            suite_id=row["suite_id"],
            created_at=row["created_at"],
        )

    # === Conversation Result Operations ===

    def save_conversation_result(self, result: ConversationResult) -> str:
        """Save a conversation result."""
        conn = self._get_conn()
        turn_results_json = json.dumps([t.to_dict() for t in result.turn_results])
        conn.execute("""
            INSERT INTO conversation_results
            (id, conversation_id, endpoint, turn_results, total_turns, passed_turns,
             avg_score, total_latency_ms, coherence_score, context_retention_score, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            result.id, result.conversation_id, result.endpoint,
            turn_results_json, result.total_turns, result.passed_turns,
            result.avg_score, result.total_latency_ms,
            result.coherence_score, result.context_retention_score,
            result.created_at
        ))
        conn.commit()
        conn.close()
        return result.id

    def get_conversation_result(self, result_id: str) -> Optional[ConversationResult]:
        """Get a conversation result by ID."""
        conn = self._get_conn()
        row = conn.execute(
            "SELECT * FROM conversation_results WHERE id = ?", (result_id,)
        ).fetchone()
        conn.close()
        if not row:
            return None
        return self._row_to_conversation_result(row)

    def list_conversation_results(self, conversation_id: Optional[str] = None, limit: int = 50) -> List[ConversationResult]:
        """List conversation results."""
        conn = self._get_conn()
        if conversation_id:
            rows = conn.execute(
                "SELECT * FROM conversation_results WHERE conversation_id = ? ORDER BY created_at DESC LIMIT ?",
                (conversation_id, limit)
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM conversation_results ORDER BY created_at DESC LIMIT ?",
                (limit,)
            ).fetchall()
        conn.close()
        return [self._row_to_conversation_result(row) for row in rows]

    def _row_to_conversation_result(self, row) -> ConversationResult:
        """Convert a database row to a ConversationResult."""
        turn_results_data = json.loads(row["turn_results"]) if row["turn_results"] else []
        turn_results = [
            ConversationTurnResult(
                turn_index=t["turn_index"],
                input=t["input"],
                output=t["output"],
                latency_ms=t["latency_ms"],
                evaluations=[
                    EvalMetric(metric=e["metric"], score=e["score"], passed=e["passed"], reason=e["reason"])
                    for e in t.get("evaluations", [])
                ],
                score=t["score"],
                passed=t["passed"],
                tool_calls=t.get("tool_calls"),
                tool_call_correct=t.get("tool_call_correct"),
                error=t.get("error"),
            )
            for t in turn_results_data
        ]
        return ConversationResult(
            id=row["id"],
            conversation_id=row["conversation_id"],
            endpoint=row["endpoint"],
            turn_results=turn_results,
            total_turns=row["total_turns"],
            passed_turns=row["passed_turns"],
            avg_score=row["avg_score"],
            total_latency_ms=row["total_latency_ms"],
            coherence_score=row["coherence_score"],
            context_retention_score=row["context_retention_score"],
            created_at=row["created_at"],
        )

    # === Baseline Operations ===

    def save_baseline(self, baseline_id: str, name: str, agent_endpoint: str,
                      suite_id: Optional[str], metrics_snapshot: dict,
                      total_tests: int, passed_tests: int, avg_score: float) -> str:
        """Save an evaluation baseline for regression detection."""
        conn = self._get_conn()
        from datetime import datetime
        conn.execute("""
            INSERT OR REPLACE INTO baselines
            (id, name, agent_endpoint, suite_id, metrics_snapshot,
             total_tests, passed_tests, avg_score, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            baseline_id, name, agent_endpoint, suite_id,
            json.dumps(metrics_snapshot), total_tests, passed_tests,
            avg_score, datetime.utcnow().isoformat()
        ))
        conn.commit()
        conn.close()
        return baseline_id

    def get_baseline(self, baseline_id: str) -> Optional[dict]:
        """Get a baseline by ID."""
        conn = self._get_conn()
        row = conn.execute("SELECT * FROM baselines WHERE id = ?", (baseline_id,)).fetchone()
        conn.close()
        if not row:
            return None
        return {
            "id": row["id"],
            "name": row["name"],
            "agent_endpoint": row["agent_endpoint"],
            "suite_id": row["suite_id"],
            "metrics_snapshot": json.loads(row["metrics_snapshot"]) if row["metrics_snapshot"] else {},
            "total_tests": row["total_tests"],
            "passed_tests": row["passed_tests"],
            "avg_score": row["avg_score"],
            "created_at": row["created_at"],
        }

    def list_baselines(self, agent_endpoint: Optional[str] = None) -> List[dict]:
        """List baselines, optionally filtered by endpoint."""
        conn = self._get_conn()
        if agent_endpoint:
            rows = conn.execute(
                "SELECT * FROM baselines WHERE agent_endpoint = ? ORDER BY created_at DESC",
                (agent_endpoint,)
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM baselines ORDER BY created_at DESC"
            ).fetchall()
        conn.close()
        return [
            {
                "id": row["id"],
                "name": row["name"],
                "agent_endpoint": row["agent_endpoint"],
                "suite_id": row["suite_id"],
                "total_tests": row["total_tests"],
                "passed_tests": row["passed_tests"],
                "avg_score": row["avg_score"],
                "created_at": row["created_at"],
            }
            for row in rows
        ]

    def delete_baseline(self, baseline_id: str) -> bool:
        """Delete a baseline."""
        conn = self._get_conn()
        conn.execute("DELETE FROM baselines WHERE id = ?", (baseline_id,))
        conn.commit()
        conn.close()
        return True
