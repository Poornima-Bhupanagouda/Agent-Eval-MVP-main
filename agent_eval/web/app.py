"""
FastAPI web application for Lilly Agent Eval.

Simple, clean API with minimal routes.
"""

from fastapi import FastAPI, HTTPException, BackgroundTasks, UploadFile, File, Request
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, Response
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Tuple
import base64
import os
import asyncio
import subprocess
import sys
import logging
from pathlib import Path
import json
import csv
import io
import yaml
from datetime import datetime
from urllib.parse import urlparse

from agent_eval.core.evaluator import Evaluator, EvalResult
from agent_eval.core.executor import Executor
from agent_eval.core.storage import Storage
from agent_eval.core.models import Test, Suite, Result, Batch, EvalMetric, RegisteredAgent, ABComparison, MultiAgentBatch, AgentChain, ChainStep, ChainResult, ChainStepResult, ChainRun, ConversationTest, ConversationTurn, ConversationTurnResult, ConversationResult, Workflow, WorkflowAgent
from agent_eval.core.file_parser import FileParser, parse_file
from agent_eval.core.introspector import AgentIntrospector, AgentProfile, get_suggested_metrics
from agent_eval.core.context_generator import ContextGenerator, GeneratedContext
from agent_eval.core.report_generator import ReportGenerator, ReportData
from agent_eval.core.statistics import welch_t_test, determine_winner, calculate_summary_stats
from agent_eval.core.test_generator import TestGenerator
from agent_eval.core.scorecard import generate_scorecard
from agent_eval.core.test_templates import list_template_packs, load_template_pack, get_template_tests, suggest_templates

# Initialize app
logger = logging.getLogger(__name__)

app = FastAPI(
    title="Lilly Agent Eval",
    description="Simple, fast agent evaluation platform",
    version="3.0.0",
)

# CORS for development
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Initialize components
evaluator = Evaluator()
executor = Executor()
storage = Storage()

# Standalone agents (not part of any workflow, auto-registered if healthy)
STANDALONE_AGENTS = [
    {"name": "HR Policy RAG Agent",  "endpoint": "http://127.0.0.1:8002/chat", "port": 8002, "health_path": "/", "tags": ["demo", "rag"]},
    {"name": "Conversational Agent", "endpoint": "http://127.0.0.1:8003/chat", "port": 8003, "health_path": "/", "tags": ["demo", "conversational"]},
    {"name": "Weather Agent",        "endpoint": "http://127.0.0.1:8004/chat", "port": 8004, "health_path": "/", "tags": ["demo", "tool_using"]},
    {"name": "Wiki Agent",           "endpoint": "http://127.0.0.1:8005/chat", "port": 8005, "health_path": "/", "tags": ["demo", "tool_using"]},
    {"name": "Calculator Agent",     "endpoint": "http://127.0.0.1:8006/chat", "port": 8006, "health_path": "/", "tags": ["demo", "tool_using"]},
    {"name": "Travel Orchestrator",  "endpoint": "http://127.0.0.1:8010/chat", "port": 8010, "health_path": "/", "tags": ["demo", "orchestrator"]},
]

# Local demo agent launch map for automatic startup on demand.
DEMO_AGENT_STARTUP = {
    8002: {"module": "sample_agents.smart_rag_agent", "depends_on": []},
    8003: {"module": "sample_agents.conversational_agent", "depends_on": []},
    8004: {"module": "sample_agents.weather_agent", "depends_on": []},
    8005: {"module": "sample_agents.wiki_agent", "depends_on": []},
    8006: {"module": "sample_agents.calculator_agent", "depends_on": []},
    8010: {"module": "sample_agents.travel_orchestrator", "depends_on": [8004, 8005, 8006]},
}

_demo_agent_processes: Dict[int, subprocess.Popen] = {}
_demo_start_lock = asyncio.Lock()


async def _is_agent_port_healthy(port: int, timeout: float = 1.5) -> bool:
    """Check whether a localhost demo agent is responding on /health or /."""
    import urllib.error
    import urllib.request

    base = f"http://127.0.0.1:{port}"

    def _probe(url: str) -> bool:
        try:
            with urllib.request.urlopen(url, timeout=timeout) as resp:
                return resp.status == 200
        except (urllib.error.URLError, TimeoutError, OSError):
            return False

    for path in ("/health", "/"):
        if await asyncio.to_thread(_probe, f"{base}{path}"):
            return True

    return False


def _start_demo_agent_process(port: int) -> bool:
    """Start a demo agent process for a known port if not already running."""
    spec = DEMO_AGENT_STARTUP.get(port)
    if not spec:
        return False

    existing = _demo_agent_processes.get(port)
    if existing and existing.poll() is None:
        return True

    project_root = Path(__file__).parent.parent.parent
    cmd = [sys.executable, "-m", spec["module"]]
    popen_kwargs = {
        "cwd": str(project_root),
        "stdout": subprocess.DEVNULL,
        "stderr": subprocess.DEVNULL,
    }

    if os.name == "nt":
        popen_kwargs["creationflags"] = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    else:
        popen_kwargs["start_new_session"] = True

    try:
        _demo_agent_processes[port] = subprocess.Popen(cmd, **popen_kwargs)
        logger.info(f"Auto-started demo agent on port {port}: {spec['module']}")
        return True
    except Exception as e:
        logger.warning(f"Failed to auto-start demo agent on port {port}: {e}")
        return False


async def _wait_until_healthy(port: int, timeout_seconds: float = 18.0) -> bool:
    """Wait until the agent on the given port becomes healthy."""
    deadline = asyncio.get_running_loop().time() + timeout_seconds
    while asyncio.get_running_loop().time() < deadline:
        if await _is_agent_port_healthy(port):
            return True
        await asyncio.sleep(0.4)
    return False


async def _ensure_demo_agents_running_for_endpoint(endpoint: str) -> None:
    """Auto-start known local demo agents when requests target their endpoints."""
    try:
        parsed = urlparse(endpoint)
        host = (parsed.hostname or "").lower()
        port = parsed.port
    except Exception:
        return

    if host not in {"127.0.0.1", "localhost"} or port not in DEMO_AGENT_STARTUP:
        return

    if await _is_agent_port_healthy(port):
        return

    async with _demo_start_lock:
        if await _is_agent_port_healthy(port):
            return

        to_start = DEMO_AGENT_STARTUP[port]["depends_on"] + [port]
        for dep_port in to_start:
            if await _is_agent_port_healthy(dep_port):
                continue
            if not _start_demo_agent_process(dep_port):
                continue
            became_healthy = await _wait_until_healthy(dep_port)
            if not became_healthy:
                logger.warning(f"Demo agent on port {dep_port} did not become healthy in time")


async def _execute_with_autostart(
    endpoint: str,
    input_text: str,
    headers: Optional[Dict[str, str]] = None,
    context: Optional[List[str]] = None,
):
    """Execute a request and auto-start local demo agents when needed."""
    await _ensure_demo_agents_running_for_endpoint(endpoint)
    return await executor.execute(endpoint, input_text, headers=headers, context=context)


async def _execute_conversation_with_autostart(
    endpoint: str,
    turns: List[Dict[str, str]],
    headers: Optional[Dict[str, str]] = None,
    context: Optional[List[str]] = None,
):
    """Execute conversation and auto-start local demo agents when needed."""
    await _ensure_demo_agents_running_for_endpoint(endpoint)
    return await executor.execute_conversation(endpoint, turns, headers=headers, context=context)


@app.on_event("startup")
async def startup_register():
    """Auto-register standalone agents and load workflow YAMLs at startup."""
    import httpx

    # 1. Register standalone agents
    for agent_def in STANDALONE_AGENTS:
        try:
            existing = storage.get_agent_by_endpoint(agent_def["endpoint"])
            if existing:
                continue

            async with httpx.AsyncClient(timeout=2.0, verify=False) as client:
                health_url = f"http://127.0.0.1:{agent_def['port']}{agent_def['health_path']}"
                resp = await client.get(health_url)
                if resp.status_code != 200:
                    continue

            agent = RegisteredAgent(
                name=agent_def["name"],
                endpoint=agent_def["endpoint"],
                tags=agent_def.get("tags"),
            )

            try:
                introspector = AgentIntrospector()
                profile = await introspector.introspect(agent_def["endpoint"])
                if profile.discovered:
                    agent.agent_type = profile.agent_type
                    agent.domain = profile.domain
                    agent.capabilities = profile.capabilities
                    agent.description = profile.purpose
            except Exception:
                pass

            storage.save_agent(agent)
            logger.info(f"Auto-registered standalone: {agent_def['name']}")
        except Exception as e:
            logger.debug(f"Skipping standalone {agent_def['name']}: {e}")

    # 2. Load workflow YAML files from workflows/ directory
    await _load_workflow_yamls()


async def _load_workflow_yamls():
    """Scan workflows/ directory, parse YAMLs, register workflows + their agents."""
    import httpx
    from urllib.parse import urlparse

    workflows_dir = Path(__file__).parent.parent.parent / "workflows"
    if not workflows_dir.exists():
        logger.info("No workflows/ directory found, skipping workflow loading")
        return

    for yaml_file in sorted(workflows_dir.glob("*.yaml")):
        try:
            with open(yaml_file) as f:
                data = yaml.safe_load(f)

            if not data or "name" not in data or "orchestrator" not in data:
                logger.warning(f"Invalid workflow YAML: {yaml_file.name}")
                continue

            # Check if already registered (by name)
            existing = storage.get_workflow_by_name(data["name"])
            workflow_id = existing.id if existing else None

            orch_data = data["orchestrator"]
            orchestrator = WorkflowAgent(
                name=orch_data["name"],
                endpoint=orch_data["endpoint"],
                health_path=orch_data.get("health_path", "/health"),
                role="orchestrator",
                tags=orch_data.get("tags"),
            )

            sub_agents = []
            for sa in data.get("sub_agents", []):
                sub_agents.append(WorkflowAgent(
                    name=sa["name"],
                    endpoint=sa["endpoint"],
                    health_path=sa.get("health_path", "/health"),
                    role="sub_agent",
                    tags=sa.get("tags"),
                ))

            workflow = Workflow(
                name=data["name"],
                description=data.get("description"),
                orchestrator=orchestrator,
                sub_agents=sub_agents,
                test_suite_path=data.get("test_suite"),
                source="yaml",
                source_file=str(yaml_file.relative_to(workflows_dir.parent)),
            )
            if workflow_id:
                workflow.id = workflow_id

            storage.save_workflow(workflow)

            # Auto-register each agent in the agents table (if healthy and not already registered)
            all_agents = [orchestrator] + sub_agents
            async with httpx.AsyncClient(timeout=2.0, verify=False) as client:
                for agent_def in all_agents:
                    existing_agent = storage.get_agent_by_endpoint(agent_def.endpoint)
                    if existing_agent:
                        continue

                    try:
                        parsed = urlparse(agent_def.endpoint)
                        health_url = f"{parsed.scheme}://{parsed.netloc}{agent_def.health_path}"
                        resp = await client.get(health_url)
                        if resp.status_code != 200:
                            continue
                    except Exception:
                        continue

                    agent = RegisteredAgent(
                        name=agent_def.name,
                        endpoint=agent_def.endpoint,
                        tags=agent_def.tags,
                    )
                    try:
                        introspector = AgentIntrospector()
                        profile = await introspector.introspect(agent_def.endpoint)
                        if profile.discovered:
                            agent.agent_type = profile.agent_type
                            agent.domain = profile.domain
                            agent.capabilities = profile.capabilities
                            agent.description = profile.purpose
                    except Exception:
                        pass

                    storage.save_agent(agent)

            logger.info(f"Loaded workflow: {data['name']} from {yaml_file.name}")

        except Exception as e:
            logger.warning(f"Failed to load workflow {yaml_file.name}: {e}")


# === Request/Response Models ===

class AuthConfigRequest(BaseModel):
    """Authentication configuration for agent endpoints."""
    auth_type: str = Field(default="none", description="Auth type: none, bearer_token, api_key, basic_auth, custom_headers")
    bearer_token: Optional[str] = Field(None, description="Bearer token value")
    api_key_header: Optional[str] = Field(None, description="API key header name (e.g., X-API-Key)")
    api_key_value: Optional[str] = Field(None, description="API key value")
    basic_username: Optional[str] = Field(None, description="Basic auth username")
    basic_password: Optional[str] = Field(None, description="Basic auth password")
    custom_headers: Optional[Dict[str, str]] = Field(None, description="Custom header key-value pairs")

    def to_headers(self) -> Dict[str, str]:
        """Convert auth config to HTTP headers."""
        headers = {}

        if self.auth_type == "bearer_token" and self.bearer_token:
            headers["Authorization"] = f"Bearer {self.bearer_token}"

        elif self.auth_type == "api_key" and self.api_key_header and self.api_key_value:
            headers[self.api_key_header] = self.api_key_value

        elif self.auth_type == "basic_auth" and self.basic_username and self.basic_password:
            credentials = f"{self.basic_username}:{self.basic_password}"
            encoded = base64.b64encode(credentials.encode()).decode()
            headers["Authorization"] = f"Basic {encoded}"

        elif self.auth_type == "custom_headers" and self.custom_headers:
            headers.update(self.custom_headers)

        return headers


def _resolve_auth_headers(
    auth: Optional["AuthConfigRequest"] = None,
    auth_dict: Optional[dict] = None,
    endpoint: Optional[str] = None,
) -> Optional[Dict[str, str]]:
    """
    Resolve auth headers with automatic env-var fallback.

    Priority:
    1. Explicit auth config from the request
    2. Auto-detect: if RAG_AGENT_API_KEY is set in env, send it as X-API-Key

    This ensures the eval platform can authenticate with agents
    without requiring the user to manually configure auth every time.
    """
    # 1. Explicit auth from request
    headers = None
    if auth and auth.auth_type != "none":
        headers = auth.to_headers()
    elif auth_dict and auth_dict.get("auth_type", "none") != "none":
        headers = AuthConfigRequest(**auth_dict).to_headers()

    if headers:
        return headers

    # 2. Auto-detect from environment
    env_key = os.environ.get("RAG_AGENT_API_KEY")
    if env_key:
        return {"X-API-Key": env_key}

    return None


class QuickTestRequest(BaseModel):
    """Request for running a quick test."""
    endpoint: str = Field(..., description="Agent endpoint URL")
    input: str = Field(..., description="Input text to send")
    expected: Optional[str] = Field(None, description="Expected output")
    context: Optional[List[str]] = Field(None, description="Context for RAG")
    metrics: Optional[List[str]] = Field(None, description="Metrics to run")
    threshold: Optional[float] = Field(None, description="Pass threshold")
    auth: Optional[AuthConfigRequest] = Field(None, description="Authentication config")
    agent_type: Optional[str] = Field(None, description="Agent type for auto metric selection (rag, conversational, tool_using, orchestrator, simple)")


class TestResponse(BaseModel):
    """Response from a test run."""
    id: str
    output: str
    score: float
    passed: bool
    latency_ms: int
    evaluations: List[dict]
    expected: Optional[str] = None
    trajectory_result: Optional[dict] = None
    rubric_results: Optional[List[dict]] = None


class SuiteCreate(BaseModel):
    """Request to create a test suite."""
    name: str
    description: Optional[str] = None
    endpoint: Optional[str] = None
    tests: Optional[List[dict]] = None


class TestCreate(BaseModel):
    """Request to add a test to a suite."""
    name: Optional[str] = None
    input: str
    expected: Optional[str] = None
    context: Optional[List[str]] = None
    metrics: Optional[List[str]] = None


class BatchRequest(BaseModel):
    """Request to run batch tests."""
    endpoint: str
    tests: List[TestCreate]
    name: Optional[str] = None
    threshold: Optional[float] = None
    auth: Optional[AuthConfigRequest] = Field(None, description="Authentication config")


# === Routes ===

@app.get("/", response_class=HTMLResponse)
async def home():
    """Serve the single-page application."""
    template_path = Path(__file__).parent / "templates" / "index.html"
    if template_path.exists():
        return HTMLResponse(template_path.read_text(encoding="utf-8"))
    return HTMLResponse("<h1>Lilly Agent Eval</h1><p>Template not found</p>")


@app.get("/api/health")
async def health():
    """Health check endpoint."""
    return {"status": "healthy", "version": "3.0.0"}


# === Quick Test ===

@app.post("/api/test", response_model=TestResponse)
async def run_test(request: QuickTestRequest):
    """
    Run a quick evaluation test.

    This is the main endpoint:
    1. Calls the agent endpoint
    2. Runs selected evaluations
    3. Returns results
    """
    try:
        # Convert auth config to headers (with env fallback)
        headers = _resolve_auth_headers(auth=request.auth, endpoint=request.endpoint)

        # Execute agent call (pass context for RAG agents)
        exec_result = await _execute_with_autostart(
            request.endpoint,
            request.input,
            headers=headers,
            context=request.context,
        )

        if exec_result.error:
            raise HTTPException(status_code=400, detail=exec_result.error)

        # Run evaluations (in thread to avoid blocking event loop during DeepEval LLM calls)
        eval_results = await asyncio.to_thread(
            evaluator.evaluate,
            input_text=request.input,
            output=exec_result.output,
            expected=request.expected,
            context=request.context,
            metrics=request.metrics,
            threshold=request.threshold,
            agent_type=request.agent_type,
        )

        # Calculate overall score
        if eval_results:
            avg_score = sum(r.score for r in eval_results) / len(eval_results)
            all_passed = all(r.passed for r in eval_results)
        else:
            avg_score = 0
            all_passed = False

        # Create result object
        result = Result(
            endpoint=request.endpoint,
            input=request.input,
            output=exec_result.output,
            expected=request.expected,
            score=avg_score,
            passed=all_passed,
            latency_ms=exec_result.latency_ms,
            evaluations=[
                EvalMetric(
                    metric=r.metric,
                    score=r.score,
                    passed=r.passed,
                    reason=r.reason,
                    scored_by=getattr(r, 'scored_by', 'heuristic'),
                )
                for r in eval_results
            ],
        )

        # Save to history
        storage.save_result(result)

        return TestResponse(
            id=result.id,
            output=exec_result.output,
            score=round(avg_score, 1),
            passed=all_passed,
            latency_ms=exec_result.latency_ms,
            expected=request.expected,
            evaluations=[
                {"metric": r.metric, "score": round(r.score, 1), "passed": r.passed, "reason": r.reason, "scored_by": getattr(r, 'scored_by', 'heuristic')}
                for r in eval_results
            ],
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Unexpected error in /api/test")
        raise HTTPException(status_code=500, detail=f"Internal error: {str(e)}")


class TestConnectionRequest(BaseModel):
    """Request to test endpoint connection."""
    endpoint: str
    auth: Optional[AuthConfigRequest] = None


@app.post("/api/test-connection")
async def test_connection(request: TestConnectionRequest):
    """Test if an endpoint is reachable, optionally with auth."""
    headers = _resolve_auth_headers(auth=request.auth, endpoint=request.endpoint)
    result = await executor.test_connection(request.endpoint, headers=headers)
    return result


# === Test Suites ===

@app.get("/api/suites")
async def list_suites():
    """List all test suites."""
    suites = storage.list_suites()
    return [s.to_dict() for s in suites]


@app.post("/api/suites")
async def create_suite(request: SuiteCreate):
    """Create a new test suite."""
    suite = Suite(
        name=request.name,
        description=request.description,
        endpoint=request.endpoint,
    )
    storage.save_suite(suite)

    # Add initial tests if provided
    if request.tests:
        for t in request.tests:
            test = Test(
                suite_id=suite.id,
                name=t.get("name"),
                input=t.get("input", ""),
                expected=t.get("expected"),
                context=t.get("context"),
                metrics=t.get("metrics"),
            )
            storage.save_test(test)

    return suite.to_dict()


@app.get("/api/suites/{suite_id}")
async def get_suite(suite_id: str):
    """Get a suite with all its tests."""
    suite = storage.get_suite(suite_id)
    if not suite:
        raise HTTPException(status_code=404, detail="Suite not found")

    return {
        **suite.to_dict(),
        "tests": [t.to_dict() for t in suite.tests],
    }


@app.post("/api/suites/{suite_id}/tests")
async def add_test_to_suite(suite_id: str, request: TestCreate):
    """Add a test to a suite."""
    suite = storage.get_suite(suite_id)
    if not suite:
        raise HTTPException(status_code=404, detail="Suite not found")

    test = Test(
        suite_id=suite_id,
        name=request.name,
        input=request.input,
        expected=request.expected,
        context=request.context,
        metrics=request.metrics,
    )
    storage.save_test(test)
    return test.to_dict()


@app.delete("/api/suites/{suite_id}")
async def delete_suite(suite_id: str):
    """Delete a suite and all its tests."""
    storage.delete_suite(suite_id)
    return {"status": "deleted"}


class UpdateTestsRequest(BaseModel):
    tests: List[dict]


@app.put("/api/suites/{suite_id}/tests")
async def update_suite_tests(suite_id: str, request: UpdateTestsRequest):
    """Update all tests in a suite (replaces existing tests)."""
    suite = storage.get_suite(suite_id)
    if not suite:
        raise HTTPException(status_code=404, detail="Suite not found")

    # Delete existing tests
    for test in suite.tests:
        storage.delete_test(test.id)

    # Add new tests
    new_tests = []
    for t in request.tests:
        test = Test(
            suite_id=suite_id,
            input=t.get("input", ""),
            expected=t.get("expected"),
            context=t.get("context"),
            metrics=t.get("metrics"),
            name=t.get("name"),
        )
        storage.save_test(test)
        new_tests.append(test.to_dict())

    return {"updated": len(new_tests), "tests": new_tests}


@app.post("/api/suites/import-yaml")
async def import_yaml_suite(file: UploadFile = File(...)):
    """Import a YAML test file and create a suite with all tests."""
    if not file.filename.endswith(('.yaml', '.yml')):
        raise HTTPException(status_code=400, detail="File must be a YAML file (.yaml or .yml)")

    try:
        content = await file.read()
        data = yaml.safe_load(content.decode('utf-8'))
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid YAML: {str(e)}")

    if not isinstance(data, dict) or 'tests' not in data:
        raise HTTPException(status_code=400, detail="YAML must contain a 'tests' key with a list of test cases")

    name = data.get('name', file.filename.rsplit('.', 1)[0])
    description = data.get('description', '')
    endpoint = data.get('endpoint', '')
    threshold = data.get('threshold', 80)

    suite = Suite(name=name, description=description, endpoint=endpoint)
    storage.save_suite(suite)

    tests_created = []
    for t in data['tests']:
        test = Test(
            suite_id=suite.id,
            input=t.get('input', ''),
            expected=t.get('expected'),
            context=t.get('context'),
            metrics=t.get('metrics'),
            name=t.get('name'),
        )
        storage.save_test(test)
        tests_created.append(test.to_dict())

    return {
        "suite_id": suite.id,
        "name": name,
        "tests_created": len(tests_created),
        "endpoint": endpoint,
    }


@app.post("/api/suites/import-yaml-path")
async def import_yaml_suite_from_path(request: Request):
    """Import a YAML test file by server-side path and create a suite. Used by Demo Mode."""
    body = await request.json()
    path = body.get("path", "")
    if not path:
        raise HTTPException(status_code=400, detail="path is required")

    # Resolve relative to project root
    resolved = Path(path) if Path(path).is_absolute() else Path(__file__).parent.parent.parent / path
    if not resolved.exists():
        raise HTTPException(status_code=404, detail=f"File not found: {path}")
    if not resolved.suffix in ('.yaml', '.yml'):
        raise HTTPException(status_code=400, detail="File must be a YAML file")

    try:
        with open(resolved, 'r') as f:
            data = yaml.safe_load(f)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid YAML: {str(e)}")

    if not isinstance(data, dict) or 'tests' not in data:
        raise HTTPException(status_code=400, detail="YAML must contain a 'tests' key")

    name = data.get('name', resolved.stem)
    description = data.get('description', '')
    endpoint = data.get('endpoint', '')

    suite = Suite(name=name, description=description, endpoint=endpoint)
    storage.save_suite(suite)

    tests_created = []
    for t in data['tests']:
        test = Test(
            suite_id=suite.id,
            input=t.get('input', ''),
            expected=t.get('expected'),
            context=t.get('context'),
            metrics=t.get('metrics'),
            name=t.get('name'),
        )
        storage.save_test(test)
        tests_created.append(test.to_dict())

    return {
        "suite_id": suite.id,
        "name": name,
        "tests_created": len(tests_created),
        "endpoint": endpoint,
    }


@app.post("/api/suites/generate-from-kb")
async def generate_tests_from_kb(
    kb_dir: Optional[str] = None,
    max_per_file: int = 10,
    suite_name: Optional[str] = None,
    endpoint: Optional[str] = None,
):
    """Generate test cases from knowledge base documents."""
    generator = TestGenerator()

    # Default to KB/ directory relative to project root
    if not kb_dir:
        kb_dir = str(Path(__file__).parent.parent.parent / "KB")

    kb_path = Path(kb_dir)
    if not kb_path.exists():
        raise HTTPException(status_code=404, detail=f"KB directory not found: {kb_dir}")

    try:
        tests = generator.generate_from_directory(str(kb_path), max_tests_per_file=max_per_file)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Generation failed: {str(e)}")

    if not tests:
        raise HTTPException(status_code=400, detail="No tests could be generated from the KB documents")

    # Create a suite with the generated tests
    name = suite_name or f"Generated from KB ({len(tests)} tests)"
    suite = Suite(name=name, description=f"Auto-generated from {kb_path.name}/", endpoint=endpoint or "")
    storage.save_suite(suite)

    for t in tests:
        test = Test(
            suite_id=suite.id,
            name=t.name,
            input=t.input,
            expected=t.expected,
            context=t.context,
            metrics=t.metrics,
        )
        storage.save_test(test)

    return {
        "suite_id": suite.id,
        "name": name,
        "tests_generated": len(tests),
        "source_files": list(set(t.source_file for t in tests)),
        "tests": [
            {
                "name": t.name,
                "input": t.input,
                "expected": t.expected[:100] + "..." if len(t.expected) > 100 else t.expected,
                "difficulty": t.difficulty,
                "source": t.source_file,
            }
            for t in tests
        ],
    }


@app.post("/api/suites/generate-from-file")
async def generate_tests_from_file(
    file: UploadFile = File(...),
    max_tests: int = 10,
    endpoint: Optional[str] = None,
):
    """Generate test cases from an uploaded document."""
    generator = TestGenerator()

    content = await file.read()
    try:
        text = FileParser.parse(content, file.filename)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    tests = generator.generate_from_text(text, source_name=file.filename, max_tests=max_tests)

    if not tests:
        raise HTTPException(status_code=400, detail="No tests could be generated from this document")

    name = f"Generated from {file.filename} ({len(tests)} tests)"
    suite = Suite(name=name, description=f"Auto-generated from {file.filename}", endpoint=endpoint or "")
    storage.save_suite(suite)

    for t in tests:
        test = Test(
            suite_id=suite.id,
            name=t.name,
            input=t.input,
            expected=t.expected,
            context=t.context,
            metrics=t.metrics,
        )
        storage.save_test(test)

    return {
        "suite_id": suite.id,
        "name": name,
        "tests_generated": len(tests),
        "tests": [
            {
                "name": t.name,
                "input": t.input,
                "expected": t.expected[:100] + "..." if len(t.expected) > 100 else t.expected,
                "difficulty": t.difficulty,
            }
            for t in tests
        ],
    }


@app.post("/api/suites/{suite_id}/run")
async def run_suite(suite_id: str, endpoint: Optional[str] = None, threshold: Optional[float] = None, concurrency: int = 1):
    """Run all tests in a suite against an endpoint. Set concurrency > 1 for parallel execution."""
    try:
        import asyncio

        suite = storage.get_suite(suite_id)
        if not suite:
            raise HTTPException(status_code=404, detail="Suite not found")

        # Use provided endpoint or suite's configured endpoint
        target_endpoint = endpoint or suite.endpoint
        if not target_endpoint:
            raise HTTPException(status_code=400, detail="No endpoint specified. Provide endpoint parameter or configure suite endpoint.")

        # Look up auth headers from registered agent matching this endpoint
        headers = None
        agents = storage.list_agents(active_only=False)
        for agent in agents:
            if agent.endpoint == target_endpoint and agent.auth_type != "none" and agent.auth_config:
                auth_req = AuthConfigRequest(
                    auth_type=agent.auth_type,
                    bearer_token=agent.auth_config.get("bearer_token"),
                    api_key_header=agent.auth_config.get("api_key_header"),
                    api_key_value=agent.auth_config.get("api_key_value"),
                    basic_username=agent.auth_config.get("basic_username"),
                    basic_password=agent.auth_config.get("basic_password"),
                    custom_headers=agent.auth_config.get("custom_headers"),
                )
                headers = auth_req.to_headers()
                break

        # Fallback: auto-detect from environment
        if not headers:
            headers = _resolve_auth_headers(endpoint=target_endpoint)

        concurrency = max(1, min(concurrency, 20))
        semaphore = asyncio.Semaphore(concurrency)

        async def run_single_test(test):
            async with semaphore:
                try:
                    exec_result = await _execute_with_autostart(target_endpoint, test.input, headers=headers)

                    if exec_result.error:
                        return {
                            "test_id": test.id,
                            "name": test.name,
                            "error": exec_result.error,
                        }

                    eval_results = await asyncio.to_thread(
                        evaluator.evaluate,
                        input_text=test.input,
                        output=exec_result.output,
                        expected=test.expected,
                        context=test.context,
                        metrics=test.metrics,
                        threshold=threshold,
                    )

                    avg_score = sum(r.score for r in eval_results) / len(eval_results) if eval_results else 0
                    all_passed = all(r.passed for r in eval_results) if eval_results else False

                    result = Result(
                        test_id=test.id,
                        suite_id=suite_id,
                        endpoint=target_endpoint,
                        input=test.input,
                        output=exec_result.output,
                        expected=test.expected,
                        score=avg_score,
                        passed=all_passed,
                        latency_ms=exec_result.latency_ms,
                        evaluations=[
                            EvalMetric(metric=r.metric, score=r.score, passed=r.passed, reason=r.reason, scored_by=getattr(r, 'scored_by', 'heuristic'))
                            for r in eval_results
                        ],
                    )
                    storage.save_result(result)

                    return {
                        "test_id": test.id,
                        "name": test.name,
                        "score": round(avg_score, 1),
                        "passed": all_passed,
                        "latency_ms": exec_result.latency_ms,
                    }
                except Exception as e:
                    return {
                        "test_id": test.id,
                        "name": test.name,
                        "error": str(e),
                    }

        if concurrency > 1 and len(suite.tests) > 1:
            results = await asyncio.gather(*[run_single_test(t) for t in suite.tests])
            results = list(results)
        else:
            results = []
            for test in suite.tests:
                results.append(await run_single_test(test))

        # Summary
        passed_count = sum(1 for r in results if r.get("passed", False))
        total_count = len(results)
        avg_score = sum(r.get("score", 0) for r in results) / total_count if total_count > 0 else 0

        return {
            "suite_id": suite_id,
            "total": total_count,
            "passed": passed_count,
            "failed": total_count - passed_count,
            "avg_score": round(avg_score, 1),
            "results": results,
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Unexpected error in /api/suites/{suite_id}/run")
        raise HTTPException(status_code=500, detail=f"Internal error: {str(e)}")


# === Batch Testing ===

@app.post("/api/batch")
async def run_batch(request: BatchRequest):
    """Run a batch of tests."""
    try:
        # Convert auth config to headers (with env fallback)
        headers = _resolve_auth_headers(auth=request.auth, endpoint=request.endpoint)

        # Create batch record
        batch = Batch(
            name=request.name or f"Batch {datetime.now().strftime('%Y-%m-%d %H:%M')}",
            total_tests=len(request.tests),
        )

        results = []
        passed_count = 0
        total_score = 0

        for test_data in request.tests:
            # Execute (pass context for RAG agents)
            exec_result = await _execute_with_autostart(
                request.endpoint,
                test_data.input,
                headers=headers,
                context=test_data.context,
            )

            if exec_result.error:
                results.append({
                    "input": test_data.input[:50] + "..." if len(test_data.input) > 50 else test_data.input,
                    "error": exec_result.error,
                })
                continue

            # Evaluate
            eval_results = await asyncio.to_thread(
                evaluator.evaluate,
                input_text=test_data.input,
                output=exec_result.output,
                expected=test_data.expected,
                context=test_data.context,
                metrics=test_data.metrics,
                threshold=request.threshold,
            )

            avg_score = sum(r.score for r in eval_results) / len(eval_results) if eval_results else 0
            all_passed = all(r.passed for r in eval_results) if eval_results else False

            if all_passed:
                passed_count += 1
            total_score += avg_score

            # Save result
            result = Result(
                batch_id=batch.id,
                endpoint=request.endpoint,
                input=test_data.input,
                output=exec_result.output,
                score=avg_score,
                passed=all_passed,
                latency_ms=exec_result.latency_ms,
                evaluations=[
                    EvalMetric(metric=r.metric, score=r.score, passed=r.passed, reason=r.reason, scored_by=getattr(r, 'scored_by', 'heuristic'))
                    for r in eval_results
                ],
            )
            storage.save_result(result)

            results.append({
                "input": test_data.input[:50] + "..." if len(test_data.input) > 50 else test_data.input,
                "output": exec_result.output[:100] + "..." if len(exec_result.output) > 100 else exec_result.output,
                "score": round(avg_score, 1),
                "passed": all_passed,
                "latency_ms": exec_result.latency_ms,
            })

        # Update batch
        batch.passed_tests = passed_count
        batch.avg_score = total_score / len(request.tests) if request.tests else 0
        batch.completed_at = datetime.utcnow().isoformat()
        storage.save_batch(batch)

        return {
            "batch_id": batch.id,
            "name": batch.name,
            "total": len(request.tests),
            "passed": passed_count,
            "failed": len(request.tests) - passed_count,
            "avg_score": round(batch.avg_score, 1),
            "results": results,
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Unexpected error in /api/batch")
        raise HTTPException(status_code=500, detail=f"Internal error: {str(e)}")


# === History ===

@app.get("/api/history")
async def get_history(
    page: int = 1,
    per_page: int = 20,
    days: int = 90,
    status: Optional[str] = None,
    agent_id: Optional[str] = None,
    limit: Optional[int] = None,  # Legacy parameter
):
    """Get evaluation history with pagination and filters."""
    try:
        # Support legacy limit parameter
        if limit and not page:
            results = storage.get_history(limit)
            return [r.to_dict() for r in results]

        # Get paginated results
        results, total = storage.get_history_paginated(
            page=page,
            per_page=per_page,
            days=days,
            status=status,
            agent_id=agent_id,
        )

        return {
            "results": [r.to_dict() for r in results],
            "total": total,
            "page": page,
            "per_page": per_page,
            "pages": (total + per_page - 1) // per_page if total > 0 else 1,
        }
    except Exception as e:
        logger.exception("Unexpected error in /api/history")
        raise HTTPException(status_code=500, detail=f"Internal error: {str(e)}")


@app.get("/api/results/{result_id}")
async def get_single_result(result_id: str):
    """Get a single test result by ID."""
    result = storage.get_result(result_id)
    if not result:
        raise HTTPException(status_code=404, detail="Result not found")
    return result.to_dict()


# === Analytics ===

@app.get("/api/analytics/summary")
async def get_analytics_summary(days: int = 30, agent_id: Optional[str] = None, suite_id: Optional[str] = None):
    """Get analytics summary for dashboard."""
    return storage.get_analytics_summary(days=days, agent_id=agent_id, suite_id=suite_id)


@app.get("/api/analytics/trends")
async def get_analytics_trends(days: int = 30, agent_id: Optional[str] = None, suite_id: Optional[str] = None):
    """Get pass rate trends over time."""
    return storage.get_analytics_trends(days=days, agent_id=agent_id, suite_id=suite_id)


@app.get("/api/analytics/distribution")
async def get_score_distribution(days: int = 30, agent_id: Optional[str] = None, suite_id: Optional[str] = None):
    """Get score distribution for histogram."""
    return storage.get_score_distribution(days=days, agent_id=agent_id, suite_id=suite_id)


@app.get("/api/analytics/category-radar")
async def get_category_radar(days: int = 30):
    """Get metric category scores for radar chart visualization."""
    from agent_eval.core.scorecard import METRIC_CATEGORIES, CATEGORY_ORDER

    history = storage.get_history(limit=200)
    if not history:
        return {"categories": []}

    # Convert to dicts (get_history returns Result dataclass objects)
    history = [r.to_dict() for r in history]

    # Filter by date
    from datetime import datetime, timedelta
    cutoff = (datetime.utcnow() - timedelta(days=days)).isoformat()
    recent = [r for r in history if r.get("created_at", "") >= cutoff]
    if not recent:
        recent = history[:50]

    # Aggregate metric scores
    metric_totals = {}
    metric_counts = {}
    for r in recent:
        for ev in r.get("evaluations", []):
            m = ev.get("metric", "")
            if m:
                metric_totals[m] = metric_totals.get(m, 0) + ev.get("score", 0)
                metric_counts[m] = metric_counts.get(m, 0) + 1

    # Build category averages
    cat_scores = {}
    cat_metric_count = {}
    for m, total in metric_totals.items():
        cat = METRIC_CATEGORIES.get(m, "Other")
        avg = total / metric_counts[m] if metric_counts[m] > 0 else 0
        cat_scores[cat] = cat_scores.get(cat, 0) + avg
        cat_metric_count[cat] = cat_metric_count.get(cat, 0) + 1

    categories = []
    for cat in CATEGORY_ORDER + ["Other"]:
        if cat in cat_scores:
            categories.append({
                "category": cat,
                "score": round(cat_scores[cat] / cat_metric_count[cat], 1),
                "metric_count": cat_metric_count[cat],
            })

    return {"categories": categories}


@app.get("/api/analytics/failure-distribution")
async def get_failure_distribution(days: int = 30):
    """Get failure distribution by metric for pie/bar chart."""
    history = storage.get_history(limit=200)
    if not history:
        return {"failures": [], "total_failures": 0}

    # Convert to dicts (get_history returns Result dataclass objects)
    history = [r.to_dict() for r in history]

    from datetime import datetime, timedelta
    cutoff = (datetime.utcnow() - timedelta(days=days)).isoformat()
    recent = [r for r in history if r.get("created_at", "") >= cutoff]
    if not recent:
        recent = history[:50]

    # Count failures per metric
    fail_counts = {}
    total_counts = {}
    for r in recent:
        for ev in r.get("evaluations", []):
            m = ev.get("metric", "")
            if m:
                total_counts[m] = total_counts.get(m, 0) + 1
                if not ev.get("passed", True):
                    fail_counts[m] = fail_counts.get(m, 0) + 1

    total_failures = sum(fail_counts.values())
    failures = sorted(
        [
            {
                "metric": m,
                "count": c,
                "total": total_counts.get(m, c),
                "percentage": round(c / total_failures * 100, 1) if total_failures > 0 else 0,
            }
            for m, c in fail_counts.items()
        ],
        key=lambda x: x["count"],
        reverse=True,
    )

    return {"failures": failures, "total_failures": total_failures}


@app.get("/api/analytics/latency-percentiles")
async def get_latency_percentiles(days: int = 30):
    """Get latency percentiles (p50, p95, p99) from recent results."""
    history = storage.get_history(limit=500)
    if not history:
        return {"p50": 0, "p95": 0, "p99": 0, "min": 0, "max": 0, "avg": 0, "count": 0}

    # Convert to dicts (get_history returns Result dataclass objects)
    history = [r.to_dict() for r in history]

    from datetime import datetime, timedelta
    cutoff = (datetime.utcnow() - timedelta(days=days)).isoformat()
    recent = [r for r in history if r.get("created_at", "") >= cutoff]
    if not recent:
        recent = history[:50]

    latencies = sorted([r.get("latency_ms", 0) for r in recent if r.get("latency_ms", 0) > 0])

    if not latencies:
        return {"p50": 0, "p95": 0, "p99": 0, "min": 0, "max": 0, "avg": 0, "count": 0}

    def percentile(data, p):
        idx = int(len(data) * p / 100)
        return data[min(idx, len(data) - 1)]

    return {
        "p50": percentile(latencies, 50),
        "p95": percentile(latencies, 95),
        "p99": percentile(latencies, 99),
        "min": latencies[0],
        "max": latencies[-1],
        "avg": round(sum(latencies) / len(latencies), 1),
        "count": len(latencies),
    }


# === Report Generation ===

class ReportRequest(BaseModel):
    """Request for generating a report."""
    title: Optional[str] = "Evaluation Report"
    result_ids: Optional[List[str]] = None  # If None, use recent results
    batch_id: Optional[str] = None
    suite_id: Optional[str] = None
    limit: int = 50


@app.post("/api/reports/html")
async def generate_html_report(request: ReportRequest):
    """Generate a beautiful HTML evaluation report."""
    try:
        # Get results based on request
        if request.batch_id:
            results = storage.get_batch_results(request.batch_id)
            title = f"Batch Report - {request.batch_id[:8]}"
        elif request.suite_id:
            results = storage.get_suite_results(request.suite_id)
            suite = storage.get_suite(request.suite_id)
            title = f"Suite Report - {suite.name if suite else request.suite_id[:8]}"
        elif request.result_ids:
            results = [storage.get_result(rid) for rid in request.result_ids if storage.get_result(rid)]
            title = request.title
        else:
            results = storage.get_history(limit=request.limit)
            title = request.title

        if not results:
            raise HTTPException(status_code=404, detail="No results found. Run an evaluation first.")

        # Convert to dict format
        results_data = []
        total_latency = 0
        passed = 0
        total_score = 0

        for r in results:
            if hasattr(r, '__dict__'):
                # Handle evaluations - they might be dicts or objects
                evals = []
                for e in (r.evaluations or []):
                    if isinstance(e, dict):
                        evals.append(e)
                    else:
                        evals.append({"metric": e.metric, "score": e.score, "passed": e.passed, "reason": e.reason, "scored_by": getattr(e, 'scored_by', 'heuristic')})

                r_dict = {
                    "input": r.input,
                    "output": r.output,
                    "expected": getattr(r, 'expected', None),
                    "score": r.score,
                    "passed": r.passed,
                    "latency_ms": r.latency_ms,
                    "evaluations": evals
                }
            else:
                r_dict = r

            results_data.append(r_dict)
            total_latency += r_dict.get("latency_ms", 0) or 0
            total_score += r_dict.get("score", 0) or 0
            if r_dict.get("passed"):
                passed += 1

        total = len(results_data)
        endpoint = results[0].endpoint if hasattr(results[0], 'endpoint') else "Unknown"

        report_data = ReportData(
            title=title,
            endpoint=endpoint,
            total_tests=total,
            passed_tests=passed,
            failed_tests=total - passed,
            avg_score=round(total_score / total, 1) if total > 0 else 0,
            avg_latency_ms=round(total_latency / total, 1) if total > 0 else 0,
            results=results_data
        )

        html_content = ReportGenerator.generate_html_report(report_data)

        return Response(
            content=html_content,
            media_type="text/html",
            headers={
                "Content-Disposition": f'attachment; filename="eval_report_{datetime.now().strftime("%Y%m%d_%H%M%S")}.html"'
            }
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to generate report: {str(e)}")


@app.post("/api/reports/json")
async def generate_json_report(request: ReportRequest):
    """Generate a JSON evaluation report."""
    # Get results based on request
    if request.batch_id:
        results = storage.get_batch_results(request.batch_id)
        title = f"Batch Report - {request.batch_id[:8]}"
    elif request.suite_id:
        results = storage.get_suite_results(request.suite_id)
        suite = storage.get_suite(request.suite_id)
        title = f"Suite Report - {suite.name if suite else request.suite_id[:8]}"
    elif request.result_ids:
        results = [storage.get_result(rid) for rid in request.result_ids if storage.get_result(rid)]
    else:
        results = storage.get_history(limit=request.limit)
        title = request.title

    if not results:
        raise HTTPException(status_code=404, detail="No results found")

    # Convert to dict format
    results_data = []
    total_latency = 0
    passed = 0
    total_score = 0

    for r in results:
        if hasattr(r, '__dict__'):
            # Handle evaluations - they might be dicts or objects
            evals = []
            for e in (r.evaluations or []):
                if isinstance(e, dict):
                    evals.append(e)
                else:
                    evals.append({"metric": e.metric, "score": e.score, "passed": e.passed, "reason": e.reason, "scored_by": getattr(e, 'scored_by', 'heuristic')})

            r_dict = {
                "input": r.input,
                "output": r.output,
                "expected": getattr(r, 'expected', None),
                "score": r.score,
                "passed": r.passed,
                "latency_ms": r.latency_ms,
                "evaluations": evals
            }
        else:
            r_dict = r

        results_data.append(r_dict)
        total_latency += r_dict.get("latency_ms", 0)
        total_score += r_dict.get("score", 0)
        if r_dict.get("passed"):
            passed += 1

    total = len(results_data)
    endpoint = results[0].endpoint if hasattr(results[0], 'endpoint') else "Unknown"

    report_data = ReportData(
        title=title,
        endpoint=endpoint,
        total_tests=total,
        passed_tests=passed,
        failed_tests=total - passed,
        avg_score=round(total_score / total, 1) if total > 0 else 0,
        avg_latency_ms=round(total_latency / total, 1) if total > 0 else 0,
        results=results_data
    )

    json_content = ReportGenerator.generate_json_report(report_data)

    return Response(
        content=json_content,
        media_type="application/json",
        headers={
            "Content-Disposition": f'attachment; filename="eval_report_{datetime.now().strftime("%Y%m%d_%H%M%S")}.json"'
        }
    )


# === Metrics ===

@app.get("/api/metrics")
async def list_metrics():
    """List available evaluation metrics."""
    return Evaluator.list_metrics()


# === File Upload for RAG Context ===

@app.post("/api/upload-context")
async def upload_context_file(file: UploadFile = File(...)):
    """
    Upload a file and extract text content for RAG context.

    Supported formats: PDF, Markdown, DOCX, XLSX, CSV, TXT
    """
    # Check file extension
    filename = file.filename or "unknown"
    ext = Path(filename).suffix.lower()

    if ext not in FileParser.SUPPORTED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file format: {ext}. Supported: {list(FileParser.SUPPORTED_EXTENSIONS)}"
        )

    try:
        # Read file content
        content = await file.read()

        # Parse file
        extracted_text = parse_file(content, filename)

        return {
            "success": True,
            "filename": filename,
            "format": ext,
            "content": extracted_text,
            "char_count": len(extracted_text),
        }

    except ImportError as e:
        raise HTTPException(
            status_code=500,
            detail=f"Missing dependency for parsing {ext} files: {str(e)}"
        )
    except Exception as e:
        raise HTTPException(
            status_code=400,
            detail=f"Failed to parse file: {str(e)}"
        )


@app.get("/api/supported-formats")
async def get_supported_formats():
    """Get list of supported file formats for upload."""
    return FileParser.get_supported_formats()


# === Agent Discovery ===

class IntrospectRequest(BaseModel):
    """Request to discover agent capabilities."""
    endpoint: str = Field(..., description="Agent endpoint URL")
    auth: Optional[AuthConfigRequest] = Field(None, description="Authentication config")


class AgentProfileResponse(BaseModel):
    """Response with discovered agent profile."""
    name: str
    purpose: str
    agent_type: str
    domain: str
    capabilities: List[str]
    suggested_metrics: List[str]
    raw_response: str
    discovered: bool = True
    discovery_error: Optional[str] = None
    auth_hint: Optional[str] = None  # "api_key", "bearer", "none", or null
    auth_header: Optional[str] = None  # Header name like "X-API-Key"


@app.post("/api/agents/discover")
async def discover_agent(request: IntrospectRequest):
    """
    Query agent to discover its purpose and capabilities.

    Returns 502 only if the agent is completely unreachable.
    Returns 200 for successful or partial discovery (check 'discovered' flag).
    """
    headers = request.auth.to_headers() if request.auth else None

    introspector = AgentIntrospector()
    profile = await introspector.introspect(request.endpoint, headers=headers)

    # Only hard-fail if agent is truly unreachable
    if not profile.discovered:
        raise HTTPException(
            status_code=502,
            detail=profile.discovery_error or "Cannot connect to agent",
        )

    # Get suggested metrics based on agent type
    suggested = get_suggested_metrics(profile.agent_type)

    return AgentProfileResponse(
        name=profile.name,
        purpose=profile.purpose,
        agent_type=profile.agent_type,
        domain=profile.domain,
        capabilities=profile.capabilities,
        suggested_metrics=suggested,
        raw_response=profile.raw_response,
        discovered=profile.discovered,
        discovery_error=profile.discovery_error,
        auth_hint=profile.auth_hint,
        auth_header=profile.auth_header,
    )


# === Context Generation ===

class GenerateContextRequest(BaseModel):
    """Request to generate sample context."""
    domain: str = Field(..., description="Domain for context generation")
    purpose: Optional[str] = Field(None, description="Agent purpose for refinement")
    count: int = Field(default=5, description="Number of samples to generate")


class GenerateContextResponse(BaseModel):
    """Response with generated context samples."""
    domain: str
    samples: List[str]


@app.post("/api/context/generate", response_model=GenerateContextResponse)
async def generate_context(request: GenerateContextRequest):
    """
    Generate sample context based on agent domain.

    Uses domain-specific templates with realistic values.
    """
    generator = ContextGenerator()
    context = generator.generate(
        domain=request.domain,
        purpose=request.purpose,
        count=request.count,
    )

    return GenerateContextResponse(
        domain=context.domain,
        samples=context.samples,
    )


@app.get("/api/context/domains")
async def list_context_domains():
    """List available domains for context generation."""
    generator = ContextGenerator()
    return {
        "domains": generator.get_available_domains()
    }


# === Agent Registry ===

class RegisterAgentRequest(BaseModel):
    """Request to register a new agent."""
    name: str = Field(..., description="Agent display name")
    endpoint: str = Field(..., description="Agent endpoint URL")
    description: Optional[str] = Field(None, description="Agent description")
    agent_type: Optional[str] = Field("simple", description="Agent type: simple, rag, conversational, tool_using")
    domain: Optional[str] = Field("general", description="Agent domain")
    auth: Optional[AuthConfigRequest] = Field(None, description="Authentication config")
    version: Optional[str] = Field(None, description="Agent version (e.g., v1.0.0)")
    tags: Optional[List[str]] = Field(None, description="Tags for categorization")
    auto_discover: bool = Field(default=False, description="Use introspection to fill in details")


class RegisteredAgentResponse(BaseModel):
    """Response with registered agent details."""
    id: str
    name: str
    endpoint: str
    description: Optional[str]
    agent_type: str
    domain: str
    capabilities: Optional[List[str]]
    auth_type: str
    version: Optional[str]
    tags: Optional[List[str]]
    is_active: bool
    last_tested_at: Optional[str]
    created_at: str
    updated_at: str


@app.post("/api/agents", response_model=RegisteredAgentResponse)
async def register_agent(request: RegisterAgentRequest):
    """
    Register a new agent in the registry.

    Optionally uses introspection to discover agent type and capabilities.
    """
    # Build auth config dict for storage
    auth_config = None
    auth_type = "none"
    if request.auth:
        auth_type = request.auth.auth_type
        auth_config = {
            "bearer_token": request.auth.bearer_token,
            "api_key_header": request.auth.api_key_header,
            "api_key_value": request.auth.api_key_value,
            "basic_username": request.auth.basic_username,
            "basic_password": request.auth.basic_password,
            "custom_headers": request.auth.custom_headers,
        }

    # Create agent
    agent = RegisteredAgent(
        name=request.name,
        endpoint=request.endpoint,
        description=request.description,
        agent_type=request.agent_type or "simple",
        domain=request.domain or "general",
        auth_type=auth_type,
        auth_config=auth_config,
        version=request.version,
        tags=request.tags,
    )

    # Auto-discover capabilities if requested
    if request.auto_discover:
        try:
            headers = request.auth.to_headers() if request.auth else None
            introspector = AgentIntrospector()
            profile = await introspector.introspect(request.endpoint, headers=headers)
            agent.agent_type = profile.agent_type
            agent.domain = profile.domain
            agent.capabilities = profile.capabilities
            if not request.description:
                agent.description = profile.purpose
        except Exception as e:
            # Continue without introspection data
            pass

    # Save to database
    storage.save_agent(agent)

    return RegisteredAgentResponse(**agent.to_dict())


@app.get("/api/agents", response_model=List[RegisteredAgentResponse])
async def list_agents(active_only: bool = True, tag: Optional[str] = None):
    """List all registered agents, optionally filtered."""
    try:
        agents = storage.list_agents(active_only=active_only, tag=tag)
        return [RegisteredAgentResponse(**a.to_dict()) for a in agents]
    except Exception as e:
        logger.exception("Unexpected error in GET /api/agents")
        raise HTTPException(status_code=500, detail=f"Internal error: {str(e)}")


@app.get("/api/agents/{agent_id}", response_model=RegisteredAgentResponse)
async def get_agent(agent_id: str):
    """Get details for a specific registered agent."""
    agent = storage.get_agent(agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")
    return RegisteredAgentResponse(**agent.to_dict())


@app.put("/api/agents/{agent_id}", response_model=RegisteredAgentResponse)
async def update_agent(agent_id: str, request: RegisterAgentRequest):
    """Update an agent's configuration."""
    existing = storage.get_agent(agent_id)
    if not existing:
        raise HTTPException(status_code=404, detail="Agent not found")

    # Build auth config
    auth_config = None
    auth_type = "none"
    if request.auth:
        auth_type = request.auth.auth_type
        auth_config = {
            "bearer_token": request.auth.bearer_token,
            "api_key_header": request.auth.api_key_header,
            "api_key_value": request.auth.api_key_value,
            "basic_username": request.auth.basic_username,
            "basic_password": request.auth.basic_password,
            "custom_headers": request.auth.custom_headers,
        }

    # Update agent
    existing.name = request.name
    existing.endpoint = request.endpoint
    existing.description = request.description
    existing.agent_type = request.agent_type or existing.agent_type
    existing.domain = request.domain or existing.domain
    existing.auth_type = auth_type
    existing.auth_config = auth_config
    existing.version = request.version
    existing.tags = request.tags
    existing.updated_at = datetime.utcnow().isoformat()

    storage.save_agent(existing)
    return RegisteredAgentResponse(**existing.to_dict())


@app.delete("/api/agents/{agent_id}")
async def delete_agent(agent_id: str):
    """Remove an agent from the registry."""
    agent = storage.get_agent(agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")
    storage.delete_agent(agent_id)
    return {"success": True, "message": f"Agent {agent_id} deleted"}


@app.post("/api/agents/{agent_id}/test")
async def quick_test_registered_agent(agent_id: str, input: str):
    """Quick connectivity and response test for a registered agent."""
    agent = storage.get_agent(agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")

    # Build headers from auth config
    headers = {}
    if agent.auth_config:
        auth_req = AuthConfigRequest(
            auth_type=agent.auth_type,
            bearer_token=agent.auth_config.get("bearer_token"),
            api_key_header=agent.auth_config.get("api_key_header"),
            api_key_value=agent.auth_config.get("api_key_value"),
            basic_username=agent.auth_config.get("basic_username"),
            basic_password=agent.auth_config.get("basic_password"),
            custom_headers=agent.auth_config.get("custom_headers"),
        )
        headers = auth_req.to_headers()

    # Execute test
    response = await _execute_with_autostart(
        endpoint=agent.endpoint,
        input_text=input,
        headers=headers,
    )

    # Update last tested timestamp
    storage.update_agent_last_tested(agent_id)

    if response.error:
        return {
            "agent_id": agent_id,
            "agent_name": agent.name,
            "input": input,
            "output": response.output,
            "latency_ms": response.latency_ms,
            "success": False,
            "error": response.error,
            "status_code": response.status_code,
        }

    if not (response.output or "").strip():
        return {
            "agent_id": agent_id,
            "agent_name": agent.name,
            "input": input,
            "output": response.output,
            "latency_ms": response.latency_ms,
            "success": False,
            "error": "Agent returned an empty response body or an unrecognized response format.",
            "status_code": response.status_code,
        }

    return {
        "agent_id": agent_id,
        "agent_name": agent.name,
        "input": input,
        "output": response.output,
        "latency_ms": response.latency_ms,
        "success": True,
        "status_code": response.status_code,
    }


@app.post("/api/agents/{agent_id}/toggle")
async def toggle_agent_active(agent_id: str, is_active: bool):
    """Toggle agent active status."""
    agent = storage.get_agent(agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")

    agent.is_active = is_active
    agent.updated_at = datetime.utcnow().isoformat()
    storage.save_agent(agent)

    return {"success": True, "agent_id": agent_id, "is_active": is_active}


# === Workflow Management ===

class WorkflowAgentRequest(BaseModel):
    name: str = Field(..., description="Agent name")
    endpoint: str = Field(..., description="Agent chat endpoint URL")
    health_path: str = Field(default="/health", description="Health check path")
    tags: Optional[List[str]] = Field(None, description="Agent tags")

class WorkflowCreateRequest(BaseModel):
    name: str = Field(..., description="Workflow name")
    description: Optional[str] = Field(None, description="Workflow description")
    orchestrator: WorkflowAgentRequest = Field(..., description="Orchestrator agent")
    sub_agents: List[WorkflowAgentRequest] = Field(..., description="Sub-agents")
    test_suite_path: Optional[str] = Field(None, description="Path to test suite YAML")


@app.get("/api/workflows")
async def list_workflows():
    """List all registered workflows."""
    workflows = storage.list_workflows()
    return [w.to_dict() for w in workflows]


@app.post("/api/workflows")
async def create_workflow(req: WorkflowCreateRequest):
    """Create a workflow from the UI."""
    orchestrator = WorkflowAgent(
        name=req.orchestrator.name,
        endpoint=req.orchestrator.endpoint,
        health_path=req.orchestrator.health_path,
        role="orchestrator",
        tags=req.orchestrator.tags,
    )
    sub_agents = [
        WorkflowAgent(
            name=sa.name, endpoint=sa.endpoint,
            health_path=sa.health_path, role="sub_agent", tags=sa.tags,
        )
        for sa in req.sub_agents
    ]
    workflow = Workflow(
        name=req.name,
        description=req.description,
        orchestrator=orchestrator,
        sub_agents=sub_agents,
        test_suite_path=req.test_suite_path,
        source="ui",
    )
    storage.save_workflow(workflow)
    return workflow.to_dict()


@app.get("/api/workflows/{workflow_id}")
async def get_workflow(workflow_id: str):
    """Get a single workflow by ID."""
    workflow = storage.get_workflow(workflow_id)
    if not workflow:
        raise HTTPException(status_code=404, detail="Workflow not found")
    return workflow.to_dict()


@app.get("/api/workflows/{workflow_id}/status")
async def get_workflow_status(workflow_id: str):
    """Get workflow with live health status of all agents."""
    import httpx
    import time as _time
    from urllib.parse import urlparse

    workflow = storage.get_workflow(workflow_id)
    if not workflow:
        raise HTTPException(status_code=404, detail="Workflow not found")

    async def check_health(agent_def: WorkflowAgent) -> dict:
        status = "offline"
        latency_ms = 0
        try:
            parsed = urlparse(agent_def.endpoint)
            base = f"{parsed.scheme}://{parsed.netloc}"
            # Try configured health_path first, then common fallbacks
            health_paths = [agent_def.health_path]
            if agent_def.health_path not in ("/", "/health"):
                health_paths += ["/health", "/"]
            elif agent_def.health_path == "/health":
                health_paths.append("/")
            async with httpx.AsyncClient(timeout=3.0, verify=False) as client:
                for path in health_paths:
                    try:
                        start = _time.time()
                        resp = await client.get(f"{base}{path}")
                        latency_ms = int((_time.time() - start) * 1000)
                        if resp.status_code == 200:
                            status = "healthy"
                            break
                    except Exception:
                        continue
        except Exception:
            pass
        registered = storage.get_agent_by_endpoint(agent_def.endpoint)
        return {
            **agent_def.to_dict(),
            "status": status,
            "latency_ms": latency_ms,
            "registered": registered is not None,
            "agent_id": registered.id if registered else None,
            "agent_type": registered.agent_type if registered else None,
            "capabilities": registered.capabilities if registered else [],
            "description": registered.description if registered else None,
        }

    all_agents = [workflow.orchestrator] + workflow.sub_agents
    agent_statuses = []
    for a in all_agents:
        agent_statuses.append(await check_health(a))

    healthy_count = sum(1 for a in agent_statuses if a["status"] == "healthy")
    return {
        **workflow.to_dict(),
        "agents": agent_statuses,
        "healthy_count": healthy_count,
        "total_count": len(agent_statuses),
    }


@app.delete("/api/workflows/{workflow_id}")
async def delete_workflow(workflow_id: str):
    """Delete a workflow."""
    workflow = storage.get_workflow(workflow_id)
    if not workflow:
        raise HTTPException(status_code=404, detail="Workflow not found")
    storage.delete_workflow(workflow_id)
    return {"success": True}


@app.post("/api/workflows/{workflow_id}/evaluate")
async def evaluate_workflow(workflow_id: str):
    """Run the associated test suite against the workflow's orchestrator."""
    workflow = storage.get_workflow(workflow_id)
    if not workflow:
        raise HTTPException(status_code=404, detail="Workflow not found")

    if not workflow.test_suite_path:
        raise HTTPException(status_code=400, detail="No test suite associated with this workflow")

    tests_path = Path(__file__).parent.parent.parent / workflow.test_suite_path
    if not tests_path.exists():
        raise HTTPException(status_code=404, detail=f"Test suite file not found: {workflow.test_suite_path}")

    endpoint = workflow.orchestrator.endpoint
    return await _run_evaluation(tests_path, endpoint, workflow.name)


@app.post("/api/workflows/{workflow_id}/evaluate-inline")
async def evaluate_workflow_inline(workflow_id: str, req: Request):
    """
    Evaluate a workflow using tests provided inline (JSON body).
    Body: { "tests": [{input, expected?, name?, metrics?}], "threshold": 70 }
    This avoids requiring a test suite file on disk.
    """
    try:
        body = await req.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON body")

    workflow = storage.get_workflow(workflow_id)
    if not workflow:
        raise HTTPException(status_code=404, detail="Workflow not found")

    tests = body.get("tests")
    if not tests or not isinstance(tests, list) or len(tests) == 0:
        raise HTTPException(status_code=400, detail="'tests' must be a non-empty list")

    endpoint = workflow.orchestrator.endpoint
    agent_name = workflow.name

    # Reuse _run_evaluation logic but with in-memory tests dict
    batch = Batch(
        name=f"Workflow: {agent_name} {datetime.now().strftime('%H:%M')}",
        total_tests=len(tests),
    )

    results = []
    passed_count = 0
    total_score = 0
    all_eval_results = []
    trajectory_stats = {"tests_with_trajectory": 0, "trajectory_passed": 0}

    for test_data in tests:
        test_input = test_data.get("input", "")
        if not test_input:
            continue
        expected = test_data.get("expected") or None
        metrics = test_data.get("metrics", ["answer_relevancy"])
        rubrics = test_data.get("rubrics")
        trajectory_spec = test_data.get("trajectory")
        expected_tool_calls = test_data.get("expected_tool_calls")
        if not trajectory_spec and expected_tool_calls:
            trajectory_spec = {"match_type": "ANY_ORDER", "expected_calls": expected_tool_calls, "check_args": False}

        has_trajectory = trajectory_spec is not None
        if has_trajectory:
            trajectory_stats["tests_with_trajectory"] += 1

        try:
            exec_result = await _execute_with_autostart(endpoint, test_input)

            if exec_result.error:
                results.append({
                    "name": test_data.get("name", ""),
                    "input": test_input,
                    "output": "",
                    "error": exec_result.error,
                    "score": 0,
                    "passed": False,
                    "latency_ms": exec_result.latency_ms,
                    "evaluations": [],
                })
                continue

            eval_results = await asyncio.to_thread(
                evaluator.evaluate,
                input_text=test_input,
                output=exec_result.output,
                expected=expected,
                metrics=metrics,
                tool_calls=exec_result.tool_calls,
                expected_tool_calls=expected_tool_calls,
                trajectory_spec=trajectory_spec,
                rubrics=rubrics,
            )

            avg_score = sum(r.score for r in eval_results) / len(eval_results) if eval_results else 0
            all_passed = all(r.passed for r in eval_results) if eval_results else False

            if all_passed:
                passed_count += 1
            total_score += avg_score

            evals_list = [{"metric": r.metric, "score": r.score, "passed": r.passed, "reason": r.reason, "scored_by": getattr(r, 'scored_by', 'heuristic')} for r in eval_results]
            all_eval_results.append({"passed": all_passed, "latency_ms": exec_result.latency_ms, "evaluations": evals_list})

            trajectory_result = None
            rubric_results = None
            for r in eval_results:
                if r.metric == "trajectory_score" and r.details:
                    trajectory_result = r.details
                    if r.details.get("matched"):
                        trajectory_stats["trajectory_passed"] += 1
                elif r.metric == "rubric_score" and r.details:
                    rubric_results = r.details.get("rubric_results")

            result_entry = Result(
                batch_id=batch.id,
                endpoint=endpoint,
                input=test_input,
                output=exec_result.output,
                expected=expected,
                score=avg_score,
                passed=all_passed,
                latency_ms=exec_result.latency_ms,
                evaluations=[EvalMetric(metric=r.metric, score=r.score, passed=r.passed, reason=r.reason, scored_by=getattr(r, 'scored_by', 'heuristic')) for r in eval_results],
                trajectory_result=trajectory_result,
                rubric_results=rubric_results,
            )
            storage.save_result(result_entry)

            result_dict = {
                "name": test_data.get("name", ""),
                "input": test_input,
                "output": exec_result.output[:300] if exec_result.output else "",
                "score": round(avg_score, 1),
                "passed": all_passed,
                "latency_ms": exec_result.latency_ms,
                "evaluations": evals_list,
            }
            results.append(result_dict)
        except Exception as e:
            results.append({
                "name": test_data.get("name", ""),
                "input": test_input,
                "output": "",
                "error": str(e),
                "score": 0,
                "passed": False,
                "latency_ms": 0,
                "evaluations": [],
            })

    batch.passed_tests = passed_count
    batch.avg_score = total_score / len(tests) if tests else 0
    batch.completed_at = datetime.utcnow().isoformat()
    storage.save_batch(batch)

    scorecard = None
    if all_eval_results:
        try:
            scorecard = generate_scorecard(all_eval_results, endpoint=endpoint, agent_name=agent_name)
        except Exception:
            pass

    response_data = {
        "batch_id": batch.id,
        "total": len(tests),
        "passed": passed_count,
        "failed": len(tests) - passed_count,
        "pass_rate": round(passed_count / len(tests) * 100, 1) if tests else 0,
        "avg_score": round(batch.avg_score, 1),
        "results": results,
        "scorecard": scorecard,
    }
    if trajectory_stats["tests_with_trajectory"] > 0:
        t = trajectory_stats
        response_data["trajectory_summary"] = {
            "tests_with_trajectory": t["tests_with_trajectory"],
            "trajectory_passed": t["trajectory_passed"],
            "trajectory_accuracy": round(t["trajectory_passed"] / t["tests_with_trajectory"] * 100, 1),
        }
    return response_data



@app.post("/api/workflows/{workflow_id}/quick-test")
async def workflow_quick_test(workflow_id: str, req: Request):
    """Send a single query to the workflow's orchestrator and run a quick evaluation."""
    try:
        body = await req.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON body")

    workflow = storage.get_workflow(workflow_id)
    if not workflow:
        raise HTTPException(status_code=404, detail="Workflow not found")

    input_text = body.get("input", "")
    expected_text = body.get("expected") or None
    if not input_text:
        raise HTTPException(status_code=400, detail="Input is required")

    try:
        exec_result = await _execute_with_autostart(workflow.orchestrator.endpoint, input_text)
        if exec_result.error:
            return {"output": None, "latency_ms": exec_result.latency_ms, "error": exec_result.error, "tool_calls": []}

        # ── Auto-derive expected_tool_calls from workflow sub-agents ──
        # Map endpoint → agent_id from actual tool_calls so we can build expected list
        endpoint_to_agent = {}
        for tc in (exec_result.tool_calls or []):
            agent_id = tc.get("args", {}).get("agent", "")
            endpoint = tc.get("args", {}).get("endpoint", "")
            if agent_id and endpoint:
                endpoint_to_agent[endpoint] = agent_id

        # Build expected_tool_calls from all sub-agents in the workflow definition
        expected_tool_calls = []
        for sa in workflow.sub_agents:
            # Try to resolve agent_id from endpoint, or derive from agent name
            agent_id = endpoint_to_agent.get(sa.endpoint) or sa.name.lower().replace(" ", "_")
            expected_tool_calls.append({"tool": "route_to_agent", "args": {"agent": agent_id}})

        # Build trajectory spec (ANY_ORDER — orchestrator can call agents in any order)
        trajectory_spec = {
            "match_type": "ANY_ORDER",
            "expected_calls": expected_tool_calls,
            "check_args": False,
        }

        # ── Run comprehensive evaluation with tool metrics ──
        eval_metrics_list = [
            "answer_relevancy",   # Does the response answer the query?
            "task_completion",    # Did the agent complete the task?
            "tool_correctness",   # Did it call the right tools?
            "trajectory_score",   # Does the tool call sequence match expectations?
        ]
        if expected_text:
            eval_metrics_list.append("similarity")

        eval_results = await asyncio.to_thread(
            evaluator.evaluate,
            input_text=input_text,
            output=exec_result.output,
            expected=expected_text,
            metrics=eval_metrics_list,
            tool_calls=exec_result.tool_calls or [],
            expected_tool_calls=expected_tool_calls,
            trajectory_spec=trajectory_spec,
        )

        # ── Tool routing analysis ──
        actual_agents = [tc.get("args", {}).get("agent", tc.get("name", "")) for tc in (exec_result.tool_calls or [])]
        expected_agents = [etc["args"]["agent"] for etc in expected_tool_calls]
        called_set = set(actual_agents)
        expected_set = set(expected_agents)
        missing_agents = sorted(expected_set - called_set)
        extra_agents = sorted(called_set - expected_set)
        routing_correct = (called_set == expected_set)

        tool_routing_info = {
            "agents_called": actual_agents,
            "agents_expected": expected_agents,
            "count": len(exec_result.tool_calls or []),
            "expected_count": len(expected_tool_calls),
            "routing_correct": routing_correct,
            "missing_agents": missing_agents,
            "extra_agents": extra_agents,
        }

        avg_score = round(sum(r.score for r in eval_results) / len(eval_results), 1) if eval_results else 0
        passed = avg_score >= 70.0

        # Save to history
        result = Result(
            endpoint=workflow.orchestrator.endpoint,
            input=input_text,
            output=exec_result.output,
            score=avg_score,
            passed=passed,
            latency_ms=exec_result.latency_ms,
            evaluations=[EvalMetric(metric=r.metric, score=r.score, passed=r.passed, reason=r.reason, scored_by=getattr(r, 'scored_by', 'heuristic')) for r in eval_results],
        )
        storage.save_result(result)

        return {
            "output": exec_result.output,
            "latency_ms": exec_result.latency_ms,
            "score": avg_score,
            "passed": passed,
            "error": None,
            "tool_calls": exec_result.tool_calls or [],
            "tool_routing": tool_routing_info,
            "evaluations": [{"metric": r.metric, "score": r.score, "passed": r.passed, "reason": r.reason, "scored_by": getattr(r, 'scored_by', 'heuristic')} for r in eval_results],
        }
    except Exception as e:
        logger.exception("Error in workflow quick test")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/workflows/reload")
async def reload_workflows():
    """Re-scan workflows/ directory and sync to DB."""
    await _load_workflow_yamls()
    workflows = storage.list_workflows()
    return {"reloaded": len(workflows), "workflows": [w.to_dict() for w in workflows]}


async def _run_evaluation(tests_path: Path, endpoint: str, agent_name: str = "Orchestrator"):
    """Shared evaluation logic for both workflow and fleet endpoints."""
    with open(tests_path) as f:
        suite_data = yaml.safe_load(f)

    # Use the endpoint passed in, but allow test file to override if no explicit endpoint
    tests = suite_data.get("tests", [])

    batch = Batch(
        name=f"Workflow: {agent_name} {datetime.now().strftime('%H:%M')}",
        total_tests=len(tests),
    )

    results = []
    passed_count = 0
    total_score = 0
    all_eval_results = []
    trajectory_stats = {"tests_with_trajectory": 0, "trajectory_passed": 0}

    for test_data in tests:
        test_input = test_data.get("input", "")
        expected = test_data.get("expected") or None
        metrics = test_data.get("metrics", ["answer_relevancy"])
        rubrics = test_data.get("rubrics")

        # Build trajectory spec: explicit trajectory block or fallback from expected_tool_calls
        trajectory_spec = test_data.get("trajectory")
        expected_tool_calls = test_data.get("expected_tool_calls")
        if not trajectory_spec and expected_tool_calls:
            trajectory_spec = {"match_type": "ANY_ORDER", "expected_calls": expected_tool_calls, "check_args": False}

        has_trajectory = trajectory_spec is not None
        if has_trajectory:
            trajectory_stats["tests_with_trajectory"] += 1

        try:
            exec_result = await _execute_with_autostart(endpoint, test_input)

            if exec_result.error:
                results.append({
                    "name": test_data.get("name", ""),
                    "input": test_input,
                    "output": "",
                    "error": exec_result.error,
                    "score": 0,
                    "passed": False,
                    "latency_ms": exec_result.latency_ms,
                    "evaluations": [],
                    "tool_calls": [],
                })
                continue

            eval_results = await asyncio.to_thread(
                evaluator.evaluate,
                input_text=test_input,
                output=exec_result.output,
                expected=expected,
                metrics=metrics,
                tool_calls=exec_result.tool_calls,
                expected_tool_calls=expected_tool_calls,
                trajectory_spec=trajectory_spec,
                rubrics=rubrics,
            )

            avg_score = sum(r.score for r in eval_results) / len(eval_results) if eval_results else 0
            all_passed = all(r.passed for r in eval_results) if eval_results else False

            if all_passed:
                passed_count += 1
            total_score += avg_score

            evals_list = [{"metric": r.metric, "score": r.score, "passed": r.passed, "reason": r.reason, "scored_by": getattr(r, 'scored_by', 'heuristic')} for r in eval_results]
            all_eval_results.append({"passed": all_passed, "latency_ms": exec_result.latency_ms, "evaluations": evals_list})

            # Extract trajectory and rubric results from eval details
            trajectory_result = None
            rubric_results = None
            for r in eval_results:
                if r.metric == "trajectory_score" and r.details:
                    trajectory_result = r.details
                    if r.details.get("matched"):
                        trajectory_stats["trajectory_passed"] += 1
                elif r.metric == "rubric_score" and r.details:
                    rubric_results = r.details.get("rubric_results")

            result_entry = Result(
                batch_id=batch.id,
                endpoint=endpoint,
                input=test_input,
                output=exec_result.output,
                expected=expected,
                score=avg_score,
                passed=all_passed,
                latency_ms=exec_result.latency_ms,
                evaluations=[EvalMetric(metric=r.metric, score=r.score, passed=r.passed, reason=r.reason, scored_by=getattr(r, 'scored_by', 'heuristic')) for r in eval_results],
                trajectory_result=trajectory_result,
                rubric_results=rubric_results,
            )
            storage.save_result(result_entry)

            result_dict = {
                "name": test_data.get("name", ""),
                "input": test_input,
                "output": exec_result.output[:300] if exec_result.output else "",
                "score": round(avg_score, 1),
                "passed": all_passed,
                "latency_ms": exec_result.latency_ms,
                "evaluations": evals_list,
                "tool_calls": exec_result.tool_calls or [],
            }
            if trajectory_result:
                result_dict["trajectory_result"] = trajectory_result
            if rubric_results:
                result_dict["rubric_results"] = rubric_results

            results.append(result_dict)
        except Exception as e:
            results.append({
                "name": test_data.get("name", ""),
                "input": test_input,
                "output": "",
                "error": str(e),
                "score": 0,
                "passed": False,
                "latency_ms": 0,
                "evaluations": [],
                "tool_calls": [],
            })

    batch.passed_tests = passed_count
    batch.avg_score = total_score / len(tests) if tests else 0
    batch.completed_at = datetime.utcnow().isoformat()
    storage.save_batch(batch)

    scorecard = None
    if all_eval_results:
        try:
            scorecard = generate_scorecard(all_eval_results, endpoint=endpoint, agent_name=agent_name)
        except Exception:
            pass

    response = {
        "batch_id": batch.id,
        "total": len(tests),
        "passed": passed_count,
        "failed": len(tests) - passed_count,
        "pass_rate": round(passed_count / len(tests) * 100, 1) if tests else 0,
        "avg_score": round(batch.avg_score, 1),
        "results": results,
        "scorecard": scorecard,
    }

    if trajectory_stats["tests_with_trajectory"] > 0:
        t = trajectory_stats
        response["trajectory_summary"] = {
            "tests_with_trajectory": t["tests_with_trajectory"],
            "trajectory_passed": t["trajectory_passed"],
            "trajectory_accuracy": round(t["trajectory_passed"] / t["tests_with_trajectory"] * 100, 1),
        }

    return response


# === Trajectory Analysis ===

@app.post("/api/trajectory/analyze")
async def analyze_trajectory(req: dict):
    """Standalone trajectory comparison for interactive analysis."""
    actual_calls = req.get("actual_calls", [])
    expected_calls = req.get("expected_calls", [])
    match_type = req.get("match_type", "IN_ORDER")
    check_args = req.get("check_args", True)

    if not expected_calls:
        raise HTTPException(status_code=400, detail="expected_calls is required")

    trajectory_spec = {
        "match_type": match_type,
        "expected_calls": expected_calls,
        "check_args": check_args,
    }

    result = evaluator._heuristic_trajectory_score(
        tool_calls=actual_calls,
        expected_tool_calls=expected_calls,
        threshold=50.0,
        trajectory_spec=trajectory_spec,
    )

    return {
        "score": result.score,
        "matched": result.details.get("matched", False) if result.details else False,
        "match_type": match_type,
        "details": result.reason,
        "per_call_match": result.details.get("per_call_match", []) if result.details else [],
        "expected_calls": result.details.get("expected_calls", []) if result.details else [],
        "actual_calls": result.details.get("actual_calls", []) if result.details else [],
    }


# === Fleet Management (backward compatibility) ===

@app.get("/api/fleet/status")
async def fleet_status():
    """Get live health status of all agents across all workflows (backward compatible)."""
    import httpx
    import time as _time
    from urllib.parse import urlparse

    # Collect all unique agents from all workflows + standalone
    all_agent_defs = []
    seen_endpoints = set()

    # Add standalone agents
    for sa in STANDALONE_AGENTS:
        if sa["endpoint"] not in seen_endpoints:
            all_agent_defs.append(sa)
            seen_endpoints.add(sa["endpoint"])

    # Add agents from all workflows
    workflows = storage.list_workflows()
    for wf in workflows:
        for agent_def in [wf.orchestrator] + wf.sub_agents:
            if agent_def.endpoint not in seen_endpoints:
                parsed = urlparse(agent_def.endpoint)
                port = parsed.port or 80
                all_agent_defs.append({
                    "name": agent_def.name,
                    "endpoint": agent_def.endpoint,
                    "port": port,
                    "health_path": agent_def.health_path,
                    "tags": agent_def.tags or [],
                })
                seen_endpoints.add(agent_def.endpoint)

    fleet = []
    async with httpx.AsyncClient(timeout=3.0, verify=False) as client:
        for agent_def in all_agent_defs:
            status = "offline"
            latency_ms = 0

            try:
                parsed = urlparse(agent_def["endpoint"])
                base = f"{parsed.scheme}://{parsed.netloc}"
                hp = agent_def['health_path']
                # Try configured health_path first, then common fallbacks
                health_paths = [hp]
                if hp not in ("/", "/health"):
                    health_paths += ["/health", "/"]
                elif hp == "/health":
                    health_paths.append("/")
                for path in health_paths:
                    try:
                        start = _time.time()
                        resp = await client.get(f"{base}{path}")
                        latency_ms = int((_time.time() - start) * 1000)
                        if resp.status_code == 200:
                            status = "healthy"
                            break
                    except Exception:
                        continue
            except Exception:
                pass

            registered = storage.get_agent_by_endpoint(agent_def["endpoint"])

            fleet.append({
                "name": agent_def["name"],
                "endpoint": agent_def["endpoint"],
                "port": agent_def.get("port", 0),
                "status": status,
                "latency_ms": latency_ms,
                "tags": agent_def.get("tags", []),
                "registered": registered is not None,
                "agent_id": registered.id if registered else None,
                "agent_type": registered.agent_type if registered else None,
                "domain": registered.domain if registered else None,
                "capabilities": registered.capabilities if registered else [],
                "description": registered.description if registered else None,
            })

    healthy_count = sum(1 for f in fleet if f["status"] == "healthy")
    return {
        "total": len(fleet),
        "healthy": healthy_count,
        "offline": len(fleet) - healthy_count,
        "agents": fleet,
    }


@app.post("/api/fleet/warmup")
async def fleet_warmup(include_orchestrator: bool = True):
    """Proactively start demo fleet agents and return resulting health status."""
    requested = []
    results = []

    for agent_def in STANDALONE_AGENTS:
        port = agent_def.get("port")
        if not include_orchestrator and port == 8010:
            continue

        requested.append(agent_def)
        was_healthy = await _is_agent_port_healthy(port)
        if not was_healthy:
            await _ensure_demo_agents_running_for_endpoint(agent_def["endpoint"])
        is_healthy = await _is_agent_port_healthy(port)

        results.append({
            "name": agent_def["name"],
            "endpoint": agent_def["endpoint"],
            "port": port,
            "was_healthy": was_healthy,
            "status": "healthy" if is_healthy else "offline",
        })

    healthy = sum(1 for r in results if r["status"] == "healthy")
    return {
        "requested": len(requested),
        "healthy": healthy,
        "offline": len(results) - healthy,
        "include_orchestrator": include_orchestrator,
        "agents": results,
    }


@app.post("/api/fleet/evaluate-orchestrator")
async def evaluate_orchestrator():
    """Run orchestrator demo tests (backward compatible â€” delegates to workflow evaluation)."""
    # Try to find "Travel Demo" workflow first
    workflow = storage.get_workflow_by_name("Travel Demo")
    if workflow and workflow.test_suite_path:
        tests_path = Path(__file__).parent.parent.parent / workflow.test_suite_path
        if tests_path.exists():
            return await _run_evaluation(tests_path, workflow.orchestrator.endpoint, "Travel Orchestrator")

    # Fallback: use hardcoded path
    tests_path = Path(__file__).parent.parent.parent / "tests" / "orchestrator_demo_tests.yaml"
    if not tests_path.exists():
        raise HTTPException(status_code=404, detail="orchestrator_demo_tests.yaml not found")

    return await _run_evaluation(tests_path, "http://localhost:8010/chat", "Travel Orchestrator")


# === A/B Testing ===

class ABTestRequest(BaseModel):
    """Request to create an A/B comparison."""
    name: str = Field(..., description="Name for this comparison")
    agent_a_id: str = Field(..., description="Agent A (control) ID")
    agent_b_id: str = Field(..., description="Agent B (treatment) ID")
    suite_id: Optional[str] = Field(None, description="Test suite to use")
    test_inputs: Optional[List[dict]] = Field(None, description="Ad-hoc test inputs if no suite")
    threshold: float = Field(default=70.0, description="Pass threshold")


class ABTestResponse(BaseModel):
    """Response with A/B comparison results."""
    id: str
    name: str
    status: str
    agent_a: dict
    agent_b: dict
    winner: Optional[str]
    statistics: Optional[dict]
    per_test_results: Optional[List[dict]]


async def _run_tests_for_agent(
    agent: RegisteredAgent,
    test_inputs: List[dict],
    threshold: float = 70.0,
) -> Tuple[List[dict], dict]:
    """Run tests against an agent and return results + summary."""
    results = []

    # Build headers from auth config
    headers = {}
    if agent.auth_config:
        auth_req = AuthConfigRequest(
            auth_type=agent.auth_type,
            bearer_token=agent.auth_config.get("bearer_token"),
            api_key_header=agent.auth_config.get("api_key_header"),
            api_key_value=agent.auth_config.get("api_key_value"),
            basic_username=agent.auth_config.get("basic_username"),
            basic_password=agent.auth_config.get("basic_password"),
            custom_headers=agent.auth_config.get("custom_headers"),
        )
        headers = auth_req.to_headers()

    total_score = 0
    total_latency = 0
    passed_count = 0

    for test in test_inputs:
        input_text = test.get("input", "")
        expected = test.get("expected")
        context = test.get("context")

        # Execute
        response = await _execute_with_autostart(
            endpoint=agent.endpoint,
            input_text=input_text,
            context=context,
            headers=headers,
        )

        # Evaluate
        eval_results = await asyncio.to_thread(
            evaluator.evaluate,
            input_text=input_text,
            output=response.output,
            expected=expected,
            context=context,
            threshold=threshold,
        )

        # Calculate score
        if eval_results:
            score = sum(e.score for e in eval_results) / len(eval_results)
            passed = all(e.passed for e in eval_results)
        else:
            score = 0
            passed = False

        results.append({
            "input": input_text,
            "output": response.output,
            "expected": expected,
            "score": round(score, 1),
            "passed": passed,
            "latency_ms": response.latency_ms,
        })

        total_score += score
        total_latency += response.latency_ms
        if passed:
            passed_count += 1

    n = len(results)
    summary = {
        "total": n,
        "passed": passed_count,
        "failed": n - passed_count,
        "pass_rate": round(passed_count / n * 100, 1) if n > 0 else 0,
        "avg_score": round(total_score / n, 1) if n > 0 else 0,
        "avg_latency_ms": round(total_latency / n) if n > 0 else 0,
    }

    return results, summary


@app.post("/api/ab-tests", response_model=ABTestResponse)
async def create_ab_test(request: ABTestRequest):
    """
    Create and run an A/B comparison between two agents.

    Runs the same tests against both agents and performs statistical analysis.
    """
    # Validate agents exist
    agent_a = storage.get_agent(request.agent_a_id)
    agent_b = storage.get_agent(request.agent_b_id)

    if not agent_a:
        raise HTTPException(status_code=404, detail=f"Agent A not found: {request.agent_a_id}")
    if not agent_b:
        raise HTTPException(status_code=404, detail=f"Agent B not found: {request.agent_b_id}")

    # Get test inputs
    test_inputs = []
    if request.suite_id:
        suite = storage.get_suite(request.suite_id)
        if not suite:
            raise HTTPException(status_code=404, detail=f"Suite not found: {request.suite_id}")
        test_inputs = [{"input": t.input, "expected": t.expected, "context": t.context} for t in suite.tests]
    elif request.test_inputs:
        test_inputs = request.test_inputs
    else:
        raise HTTPException(status_code=400, detail="Either suite_id or test_inputs required")

    if len(test_inputs) < 2:
        raise HTTPException(status_code=400, detail="Need at least 2 test cases for A/B comparison")

    # Create comparison record
    comparison = ABComparison(
        name=request.name,
        agent_a_id=request.agent_a_id,
        agent_b_id=request.agent_b_id,
        suite_id=request.suite_id,
        status="running",
    )
    storage.save_ab_comparison(comparison)

    try:
        # Run tests for both agents
        results_a, summary_a = await _run_tests_for_agent(agent_a, test_inputs, request.threshold)
        results_b, summary_b = await _run_tests_for_agent(agent_b, test_inputs, request.threshold)

        # Extract scores for statistical analysis
        scores_a = [r["score"] for r in results_a]
        scores_b = [r["score"] for r in results_b]

        # Determine winner with statistics
        winner, stats = determine_winner(scores_a, scores_b)

        # Update comparison
        comparison.status = "completed"
        comparison.agent_a_results = summary_a
        comparison.agent_b_results = summary_b
        comparison.winner = winner
        comparison.p_value = stats.p_value
        comparison.effect_size = stats.effect_size
        comparison.completed_at = datetime.utcnow().isoformat()
        storage.save_ab_comparison(comparison)

        # Update last tested timestamps
        storage.update_agent_last_tested(agent_a.id)
        storage.update_agent_last_tested(agent_b.id)

        # Build per-test comparison
        per_test_results = []
        for i, (ra, rb) in enumerate(zip(results_a, results_b)):
            per_test_results.append({
                "input": ra["input"],
                "agent_a_output": ra["output"],
                "agent_a_score": ra["score"],
                "agent_b_output": rb["output"],
                "agent_b_score": rb["score"],
                "score_diff": round(rb["score"] - ra["score"], 1),
                "test_winner": "B" if rb["score"] > ra["score"] else ("A" if ra["score"] > rb["score"] else "tie"),
            })

        return ABTestResponse(
            id=comparison.id,
            name=comparison.name,
            status="completed",
            agent_a={
                "id": agent_a.id,
                "name": agent_a.name,
                **summary_a,
            },
            agent_b={
                "id": agent_b.id,
                "name": agent_b.name,
                **summary_b,
            },
            winner=winner,
            statistics=stats.to_dict(),
            per_test_results=per_test_results,
        )

    except Exception as e:
        comparison.status = "failed"
        storage.save_ab_comparison(comparison)
        raise HTTPException(status_code=500, detail=f"A/B test failed: {str(e)}")


@app.get("/api/ab-tests")
async def list_ab_tests(limit: int = 20):
    """List recent A/B comparisons."""
    comparisons = storage.list_ab_comparisons(limit=limit)

    results = []
    for c in comparisons:
        agent_a = storage.get_agent(c.agent_a_id)
        agent_b = storage.get_agent(c.agent_b_id)

        results.append({
            "id": c.id,
            "name": c.name,
            "status": c.status,
            "agent_a_name": agent_a.name if agent_a else "Unknown",
            "agent_b_name": agent_b.name if agent_b else "Unknown",
            "winner": c.winner,
            "p_value": c.p_value,
            "created_at": c.created_at,
            "completed_at": c.completed_at,
        })

    return results


@app.get("/api/ab-tests/{comparison_id}")
async def get_ab_test(comparison_id: str):
    """Get detailed results for an A/B comparison."""
    comparison = storage.get_ab_comparison(comparison_id)
    if not comparison:
        raise HTTPException(status_code=404, detail="Comparison not found")

    agent_a = storage.get_agent(comparison.agent_a_id)
    agent_b = storage.get_agent(comparison.agent_b_id)

    return {
        "id": comparison.id,
        "name": comparison.name,
        "status": comparison.status,
        "agent_a": {
            "id": comparison.agent_a_id,
            "name": agent_a.name if agent_a else "Unknown",
            "results": comparison.agent_a_results,
        },
        "agent_b": {
            "id": comparison.agent_b_id,
            "name": agent_b.name if agent_b else "Unknown",
            "results": comparison.agent_b_results,
        },
        "winner": comparison.winner,
        "p_value": comparison.p_value,
        "effect_size": comparison.effect_size,
        "created_at": comparison.created_at,
        "completed_at": comparison.completed_at,
    }


# === Chain Testing Models ===

class ChainStepRequest(BaseModel):
    """A single step in a chain."""
    agent_id: str = Field(..., description="Agent ID for this step")
    input_mapping: str = Field(default="previous_output", description="How to map input: direct, previous_output, template")
    input_template: Optional[str] = Field(None, description="Template for input transformation (use {input} and {previous_output})")
    expected_routing: Optional[str] = Field(None, description="Expected agent to route to (for verification)")


class ChainCreateRequest(BaseModel):
    """Request to create an agent chain."""
    name: str = Field(..., description="Chain name")
    description: Optional[str] = Field(None, description="Chain description")
    steps: List[ChainStepRequest] = Field(..., description="Chain steps (agents in order)")
    fail_fast: bool = Field(default=False, description="Stop on first failure")


class ChainRunRequest(BaseModel):
    """Request to run a chain."""
    input: str = Field(..., description="Input to send to first agent")
    name: Optional[str] = Field(None, description="Name for this run")
    expected: Optional[str] = Field(None, description="Expected final output for evaluation")
    threshold: Optional[float] = Field(70.0, description="Pass threshold (0-100)")
    context: Optional[List[str]] = Field(None, description="Context for RAG chains")


class ChainResponse(BaseModel):
    """Chain response."""
    id: str
    name: str
    description: Optional[str]
    step_count: int
    steps: List[dict]
    fail_fast: bool
    created_at: str


class ChainRunResponse(BaseModel):
    """Chain run response."""
    id: str
    chain_id: str
    name: str
    status: str
    total_tests: int
    passed_tests: int
    pass_rate: float
    avg_latency_ms: float
    routing_accuracy: Optional[float]
    created_at: str
    completed_at: Optional[str]


# === Chain Testing Endpoints ===

@app.post("/api/chains", response_model=ChainResponse)
async def create_chain(request: ChainCreateRequest):
    """Create a new agent chain."""
    # Validate all agents exist
    for i, step in enumerate(request.steps):
        agent = storage.get_agent(step.agent_id)
        if not agent:
            raise HTTPException(status_code=400, detail=f"Agent {step.agent_id} not found in step {i+1}")

    # Create chain steps
    steps = [
        ChainStep(
            agent_id=s.agent_id,
            order=i,
            input_mapping=s.input_mapping,
            input_template=s.input_template,
            expected_routing=s.expected_routing,
        )
        for i, s in enumerate(request.steps)
    ]

    chain = AgentChain(
        name=request.name,
        description=request.description,
        steps=steps,
        fail_fast=request.fail_fast,
    )

    storage.save_chain(chain)

    return ChainResponse(
        id=chain.id,
        name=chain.name,
        description=chain.description,
        step_count=len(chain.steps),
        steps=[s.to_dict() for s in chain.steps],
        fail_fast=chain.fail_fast,
        created_at=chain.created_at,
    )


@app.get("/api/chains", response_model=List[ChainResponse])
async def list_chains():
    """List all agent chains."""
    chains = storage.list_chains()
    return [
        ChainResponse(
            id=c.id,
            name=c.name,
            description=c.description,
            step_count=len(c.steps),
            steps=[s.to_dict() for s in c.steps],
            fail_fast=c.fail_fast,
            created_at=c.created_at,
        )
        for c in chains
    ]


@app.get("/api/chains/{chain_id}", response_model=ChainResponse)
async def get_chain(chain_id: str):
    """Get chain details."""
    chain = storage.get_chain(chain_id)
    if not chain:
        raise HTTPException(status_code=404, detail="Chain not found")

    # Enrich steps with agent names
    enriched_steps = []
    for step in chain.steps:
        agent = storage.get_agent(step.agent_id)
        step_dict = step.to_dict()
        step_dict["agent_name"] = agent.name if agent else "Unknown"
        enriched_steps.append(step_dict)

    return ChainResponse(
        id=chain.id,
        name=chain.name,
        description=chain.description,
        step_count=len(chain.steps),
        steps=enriched_steps,
        fail_fast=chain.fail_fast,
        created_at=chain.created_at,
    )


@app.delete("/api/chains/{chain_id}")
async def delete_chain(chain_id: str):
    """Delete a chain."""
    chain = storage.get_chain(chain_id)
    if not chain:
        raise HTTPException(status_code=404, detail="Chain not found")

    storage.delete_chain(chain_id)
    return {"message": "Chain deleted", "id": chain_id}


@app.post("/api/chains/{chain_id}/run")
async def run_chain(chain_id: str, request: ChainRunRequest):
    """Run a single test through the chain."""
    chain = storage.get_chain(chain_id)
    if not chain:
        raise HTTPException(status_code=404, detail="Chain not found")

    # Execute chain
    step_results = []
    current_input = request.input
    total_latency = 0
    success = True
    final_output = ""

    for step in chain.steps:
        agent = storage.get_agent(step.agent_id)
        if not agent:
            step_results.append(ChainStepResult(
                agent_id=step.agent_id,
                agent_name="Unknown",
                input=current_input,
                output="",
                latency_ms=0,
                success=False,
                error=f"Agent {step.agent_id} not found",
            ))
            if chain.fail_fast:
                success = False
                break
            continue

        # Prepare input based on mapping
        if step.input_mapping == "template" and step.input_template:
            step_input = step.input_template.replace("{input}", request.input).replace("{previous_output}", current_input)
        elif step.input_mapping == "direct":
            step_input = request.input
        else:  # previous_output (default)
            step_input = current_input

        # Execute step
        try:
            # Get auth headers
            auth_headers = {}
            if agent.auth_type != "none" and agent.auth_config:
                auth_config = AuthConfigRequest(**agent.auth_config)
                auth_headers = auth_config.to_headers()

            result = await _execute_with_autostart(agent.endpoint, step_input, headers=auth_headers)

            # Per-step evaluation
            step_evals = []
            step_tool_calls = result.tool_calls
            step_score = None

            if step.expected_output or step.metrics or step.expected_tool_calls:
                eval_metrics = step.metrics or ["answer_relevancy"]
                if step.expected_tool_calls and "tool_correctness" not in eval_metrics:
                    eval_metrics.append("tool_correctness")
                eval_results = await asyncio.to_thread(
                    evaluator.evaluate,
                    input_text=step_input,
                    output=result.output,
                    expected=step.expected_output,
                    context=step.context,
                    metrics=eval_metrics,
                    tool_calls=step_tool_calls,
                    expected_tool_calls=step.expected_tool_calls,
                )
                step_evals = [{"metric": e.metric, "score": e.score, "passed": e.passed, "reason": e.reason, "scored_by": getattr(e, 'scored_by', 'heuristic')} for e in eval_results]
                if step_evals:
                    step_score = sum(e["score"] for e in step_evals) / len(step_evals)

            step_results.append(ChainStepResult(
                agent_id=step.agent_id,
                agent_name=agent.name,
                input=step_input,
                output=result.output,
                latency_ms=result.latency_ms,
                success=True,
                evaluations=step_evals if step_evals else None,
                tool_calls=step_tool_calls,
                score=step_score,
            ))

            current_input = result.output
            final_output = result.output
            total_latency += result.latency_ms

            # Update agent last tested
            storage.update_agent_last_tested(agent.id)

        except Exception as e:
            step_results.append(ChainStepResult(
                agent_id=step.agent_id,
                agent_name=agent.name,
                input=step_input,
                output="",
                latency_ms=0,
                success=False,
                error=str(e),
            ))
            success = False
            if chain.fail_fast:
                break

    # Routing verification
    routing_correct = None
    routing_checks = 0
    routing_passed = 0
    for i, step in enumerate(chain.steps):
        if step.expected_routing and i < len(step_results) and step_results[i].success:
            routing_checks += 1
            if step.expected_routing.lower() in step_results[i].output.lower():
                routing_passed += 1
    if routing_checks > 0:
        routing_correct = routing_passed == routing_checks

    # Create chain result
    chain_result = ChainResult(
        chain_id=chain_id,
        test_input=request.input,
        final_output=final_output,
        step_results=step_results,
        total_latency_ms=total_latency,
        success=success,
        routing_correct=routing_correct,
    )

    # Generate scorecard from step evaluations
    scorecard = None
    scored_steps = [s for s in step_results if s.evaluations]
    if scored_steps:
        scorecard_results = []
        for sr in scored_steps:
            scorecard_results.append({
                "passed": all(e["passed"] for e in sr.evaluations),
                "latency_ms": sr.latency_ms,
                "evaluations": sr.evaluations,
            })
        scorecard = generate_scorecard(scorecard_results, endpoint=chain.name, agent_name=chain.name)

    # Save as a chain run
    run_name = request.name or f"Run {datetime.utcnow().strftime('%Y-%m-%d %H:%M')}"
    routing_accuracy = (routing_passed / routing_checks * 100) if routing_checks > 0 else None
    chain_run = ChainRun(
        chain_id=chain_id,
        name=run_name,
        status="completed",
        total_tests=1,
        passed_tests=1 if success else 0,
        avg_latency_ms=total_latency,
        routing_accuracy=routing_accuracy,
        results=[chain_result],
        completed_at=datetime.utcnow().isoformat(),
    )
    storage.save_chain_run(chain_run)

    response = {
        "run_id": chain_run.id,
        "chain_id": chain_id,
        "success": success,
        "test_input": request.input,
        "final_output": final_output,
        "total_latency_ms": total_latency,
        "step_results": [s.to_dict() for s in step_results],
    }
    if routing_accuracy is not None:
        response["routing_accuracy"] = routing_accuracy
    if scorecard:
        response["scorecard"] = scorecard
    return response


@app.post("/api/chains/{chain_id}/run-suite/{suite_id}")
async def run_chain_with_suite(chain_id: str, suite_id: str):
    """Run all tests from a suite through the chain."""
    chain = storage.get_chain(chain_id)
    if not chain:
        raise HTTPException(status_code=404, detail="Chain not found")

    suite = storage.get_suite(suite_id)
    if not suite:
        raise HTTPException(status_code=404, detail="Suite not found")

    if not suite.tests:
        raise HTTPException(status_code=400, detail="Suite has no tests")

    # Run each test through the chain
    all_results = []
    total_latency = 0
    passed_count = 0

    for test in suite.tests:
        step_results = []
        current_input = test.input
        test_latency = 0
        test_success = True
        final_output = ""

        for step in chain.steps:
            agent = storage.get_agent(step.agent_id)
            if not agent:
                step_results.append(ChainStepResult(
                    agent_id=step.agent_id,
                    agent_name="Unknown",
                    input=current_input,
                    output="",
                    latency_ms=0,
                    success=False,
                    error=f"Agent {step.agent_id} not found",
                ))
                if chain.fail_fast:
                    test_success = False
                    break
                continue

            # Prepare input
            if step.input_mapping == "template" and step.input_template:
                step_input = step.input_template.replace("{input}", test.input).replace("{previous_output}", current_input)
            elif step.input_mapping == "direct":
                step_input = test.input
            else:
                step_input = current_input

            try:
                auth_headers = {}
                if agent.auth_type != "none" and agent.auth_config:
                    auth_config = AuthConfigRequest(**agent.auth_config)
                    auth_headers = auth_config.to_headers()

                result = await _execute_with_autostart(agent.endpoint, step_input, headers=auth_headers)

                # Per-step evaluation
                step_evals = []
                step_tool_calls = result.tool_calls
                step_score = None

                if step.expected_output or step.metrics or step.expected_tool_calls:
                    eval_metrics = step.metrics or ["answer_relevancy"]
                    if step.expected_tool_calls and "tool_correctness" not in eval_metrics:
                        eval_metrics.append("tool_correctness")
                    eval_results = await asyncio.to_thread(
                        evaluator.evaluate,
                        input_text=step_input,
                        output=result.output,
                        expected=step.expected_output,
                        context=step.context,
                        metrics=eval_metrics,
                        tool_calls=step_tool_calls,
                        expected_tool_calls=step.expected_tool_calls,
                    )
                    step_evals = [{"metric": e.metric, "score": e.score, "passed": e.passed, "reason": e.reason, "scored_by": getattr(e, 'scored_by', 'heuristic')} for e in eval_results]
                    if step_evals:
                        step_score = sum(e["score"] for e in step_evals) / len(step_evals)

                step_results.append(ChainStepResult(
                    agent_id=step.agent_id,
                    agent_name=agent.name,
                    input=step_input,
                    output=result.output,
                    latency_ms=result.latency_ms,
                    success=True,
                    evaluations=step_evals if step_evals else None,
                    tool_calls=step_tool_calls,
                    score=step_score,
                ))

                current_input = result.output
                final_output = result.output
                test_latency += result.latency_ms

            except Exception as e:
                step_results.append(ChainStepResult(
                    agent_id=step.agent_id,
                    agent_name=agent.name,
                    input=step_input,
                    output="",
                    latency_ms=0,
                    success=False,
                    error=str(e),
                ))
                test_success = False
                if chain.fail_fast:
                    break

        chain_result = ChainResult(
            chain_id=chain_id,
            test_input=test.input,
            final_output=final_output,
            step_results=step_results,
            total_latency_ms=test_latency,
            success=test_success,
        )
        all_results.append(chain_result)
        total_latency += test_latency
        if test_success:
            passed_count += 1

    # Save chain run
    run_name = f"{chain.name} x {suite.name}"
    avg_latency = total_latency / len(suite.tests) if suite.tests else 0

    chain_run = ChainRun(
        chain_id=chain_id,
        name=run_name,
        suite_id=suite_id,
        status="completed",
        total_tests=len(suite.tests),
        passed_tests=passed_count,
        avg_latency_ms=avg_latency,
        results=all_results,
        completed_at=datetime.utcnow().isoformat(),
    )
    storage.save_chain_run(chain_run)

    return {
        "run_id": chain_run.id,
        "chain_id": chain_id,
        "suite_id": suite_id,
        "status": "completed",
        "total_tests": len(suite.tests),
        "passed_tests": passed_count,
        "pass_rate": round(passed_count / len(suite.tests) * 100, 1) if suite.tests else 0,
        "avg_latency_ms": round(avg_latency, 1),
        "results": [r.to_dict() for r in all_results],
    }


@app.get("/api/chains/{chain_id}/runs", response_model=List[ChainRunResponse])
async def list_chain_runs(chain_id: str):
    """List runs for a specific chain."""
    chain = storage.get_chain(chain_id)
    if not chain:
        raise HTTPException(status_code=404, detail="Chain not found")

    runs = storage.list_chain_runs(chain_id=chain_id)
    return [
        ChainRunResponse(
            id=r.id,
            chain_id=r.chain_id,
            name=r.name,
            status=r.status,
            total_tests=r.total_tests,
            passed_tests=r.passed_tests,
            pass_rate=round(r.passed_tests / r.total_tests * 100, 1) if r.total_tests > 0 else 0,
            avg_latency_ms=r.avg_latency_ms,
            routing_accuracy=r.routing_accuracy,
            created_at=r.created_at,
            completed_at=r.completed_at,
        )
        for r in runs
    ]


@app.get("/api/chain-runs")
async def list_all_chain_runs():
    """List all chain runs."""
    runs = storage.list_chain_runs()
    result = []
    for r in runs:
        chain = storage.get_chain(r.chain_id)
        result.append({
            "id": r.id,
            "chain_id": r.chain_id,
            "chain_name": chain.name if chain else "Unknown",
            "name": r.name,
            "status": r.status,
            "total_tests": r.total_tests,
            "passed_tests": r.passed_tests,
            "pass_rate": round(r.passed_tests / r.total_tests * 100, 1) if r.total_tests > 0 else 0,
            "avg_latency_ms": r.avg_latency_ms,
            "created_at": r.created_at,
            "completed_at": r.completed_at,
        })
    return result


@app.get("/api/chain-runs/{run_id}")
async def get_chain_run(run_id: str):
    """Get detailed chain run results."""
    run = storage.get_chain_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Chain run not found")

    chain = storage.get_chain(run.chain_id)

    return {
        "id": run.id,
        "chain_id": run.chain_id,
        "chain_name": chain.name if chain else "Unknown",
        "name": run.name,
        "suite_id": run.suite_id,
        "status": run.status,
        "total_tests": run.total_tests,
        "passed_tests": run.passed_tests,
        "pass_rate": round(run.passed_tests / run.total_tests * 100, 1) if run.total_tests > 0 else 0,
        "avg_latency_ms": run.avg_latency_ms,
        "routing_accuracy": run.routing_accuracy,
        "results": [r.to_dict() for r in run.results],
        "created_at": run.created_at,
        "completed_at": run.completed_at,
    }


# === Multi-Turn Conversation Testing ===

class ConversationTurnRequest(BaseModel):
    """A single turn in a conversation test."""
    role: str = Field(..., description="'user' or 'expected_assistant'")
    content: str = Field(..., description="Turn content")
    expected: Optional[str] = Field(None, description="Expected response for user turns")
    check_metrics: Optional[List[str]] = Field(None, description="Metrics to check this turn")
    expected_tool_calls: Optional[List[dict]] = Field(None, description="Expected tool calls")

class ConversationCreateRequest(BaseModel):
    """Request to create a conversation test."""
    name: str = Field(..., description="Conversation test name")
    turns: List[ConversationTurnRequest] = Field(..., description="Conversation turns")
    description: Optional[str] = None
    endpoint: Optional[str] = None
    context: Optional[List[str]] = None


@app.post("/api/conversations")
async def create_conversation(request: ConversationCreateRequest):
    """Create a multi-turn conversation test."""
    if not request.turns or len(request.turns) < 1:
        raise HTTPException(status_code=400, detail="At least 1 turn required")

    user_turns = [t for t in request.turns if t.role == "user"]
    if not user_turns:
        raise HTTPException(status_code=400, detail="At least 1 user turn required")

    turns = [
        ConversationTurn(
            role=t.role,
            content=t.content,
            expected=t.expected,
            check_metrics=t.check_metrics,
            expected_tool_calls=t.expected_tool_calls,
        )
        for t in request.turns
    ]

    conv = ConversationTest(
        name=request.name,
        turns=turns,
        description=request.description,
        endpoint=request.endpoint,
        context=request.context,
    )
    storage.save_conversation_test(conv)

    return conv.to_dict()


@app.get("/api/conversations")
async def list_conversations():
    """List all conversation tests."""
    convs = storage.list_conversation_tests()
    return [c.to_dict() for c in convs]


@app.get("/api/conversations/{conv_id}")
async def get_conversation(conv_id: str):
    """Get conversation test details."""
    conv = storage.get_conversation_test(conv_id)
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation test not found")
    return conv.to_dict()


@app.delete("/api/conversations/{conv_id}")
async def delete_conversation(conv_id: str):
    """Delete a conversation test."""
    conv = storage.get_conversation_test(conv_id)
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation test not found")
    storage.delete_conversation_test(conv_id)
    return {"deleted": True, "id": conv_id}


@app.post("/api/conversations/{conv_id}/run")
async def run_conversation(conv_id: str, endpoint: Optional[str] = None, threshold: Optional[float] = None):
    """Run a multi-turn conversation test against an agent endpoint."""
    conv = storage.get_conversation_test(conv_id)
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation test not found")

    target_endpoint = endpoint or conv.endpoint
    if not target_endpoint:
        raise HTTPException(status_code=400, detail="No endpoint specified")

    eval_threshold = threshold or 70.0

    # Look up auth headers from registered agents
    headers = None
    agents = storage.list_agents(active_only=False)
    for agent in agents:
        if agent.endpoint == target_endpoint and agent.auth_type != "none" and agent.auth_config:
            auth_req = AuthConfigRequest(
                auth_type=agent.auth_type,
                bearer_token=agent.auth_config.get("bearer_token"),
                api_key_header=agent.auth_config.get("api_key_header"),
                api_key_value=agent.auth_config.get("api_key_value"),
                basic_username=agent.auth_config.get("basic_username"),
                basic_password=agent.auth_config.get("basic_password"),
                custom_headers=agent.auth_config.get("custom_headers"),
            )
            headers = auth_req.to_headers()
            break

    # Build turns list for executor
    turn_dicts = [{"role": t.role, "content": t.content} for t in conv.turns]

    # Execute conversation
    exec_results = await _execute_conversation_with_autostart(
        target_endpoint, turn_dicts, headers=headers, context=conv.context
    )

    # ── PHASE 1: Build conversation history (fast, no LLM) ──────────────
    # Collect all turn data first so we can evaluate everything in parallel.
    eval_jobs = []          # list of dicts with all info needed for eval
    conversation_history = []
    user_turn_idx = 0
    error_results = []      # (index, ConversationTurnResult) for failed turns

    for turn in conv.turns:
        if turn.role != "user":
            conversation_history.append({"role": "assistant", "content": turn.content})
            continue

        if user_turn_idx >= len(exec_results):
            break

        exec_result = exec_results[user_turn_idx]
        turn_index = user_turn_idx
        user_turn_idx += 1

        conversation_history.append({"role": "user", "content": turn.content})

        if exec_result.error:
            error_results.append((turn_index, ConversationTurnResult(
                turn_index=turn_index,
                input=turn.content,
                output="",
                latency_ms=exec_result.latency_ms,
                evaluations=[],
                score=0.0,
                passed=False,
                error=exec_result.error,
            )))
            continue

        conversation_history.append({"role": "assistant", "content": exec_result.output})

        # Select metrics — lean default set for conversation tests
        turn_metrics = turn.check_metrics
        if not turn_metrics:
            turn_metrics = ["answer_relevancy", "toxicity", "task_completion"]
            if turn.expected:
                turn_metrics.append("similarity")
            if len(conversation_history) > 2:
                turn_metrics.extend(["coherence", "context_retention"])

        eval_jobs.append({
            "turn_index": turn_index,
            "turn": turn,
            "exec_result": exec_result,
            "metrics": turn_metrics,
            "history_snapshot": list(conversation_history[:-1]) if len(conversation_history) > 2 else None,
        })

    # ── PHASE 2: Evaluate ALL turns in PARALLEL (single batch) ──────────
    # Submit every turn's evaluation concurrently. The evaluator already
    # parallelizes DeepEval metrics within each call, so this gives us
    # full concurrency: all turns × all metrics at once.
    async def _eval_turn(job):
        return await asyncio.to_thread(
            evaluator.evaluate,
            input_text=job["turn"].content,
            output=job["exec_result"].output,
            expected=job["turn"].expected,
            metrics=job["metrics"],
            threshold=eval_threshold,
            tool_calls=job["exec_result"].tool_calls,
            expected_tool_calls=job["turn"].expected_tool_calls,
            conversation_history=job["history_snapshot"],
        )

    # Also evaluate coherence + retention in the same parallel batch
    coherence_job = None
    retention_job = None
    if len(conversation_history) > 2 and eval_jobs:
        last_job = eval_jobs[-1]
        coherence_job = asyncio.to_thread(
            evaluator.evaluate,
            input_text=last_job["turn"].content,
            output=last_job["exec_result"].output,
            metrics=["coherence"],
            conversation_history=conversation_history,
        )
        retention_job = asyncio.to_thread(
            evaluator.evaluate,
            input_text=last_job["turn"].content,
            output=last_job["exec_result"].output,
            metrics=["context_retention"],
            conversation_history=conversation_history,
        )

    # Gather ALL evaluations at once
    all_tasks = [_eval_turn(job) for job in eval_jobs]
    if coherence_job:
        all_tasks.append(coherence_job)
    if retention_job:
        all_tasks.append(retention_job)

    all_eval_results = await asyncio.gather(*all_tasks, return_exceptions=True)

    # ── PHASE 3: Assemble results ──────────────────────────────────────
    turn_results = []
    for i, job in enumerate(eval_jobs):
        evals_or_error = all_eval_results[i]
        if isinstance(evals_or_error, Exception):
            logger.error(f"Eval error for turn {job['turn_index']}: {evals_or_error}")
            evals = []
        else:
            evals = evals_or_error

        eval_metrics = [
            EvalMetric(metric=e.metric, score=e.score, passed=e.passed, reason=e.reason, scored_by=getattr(e, 'scored_by', 'heuristic'))
            for e in evals
        ]
        avg_score = sum(e.score for e in evals) / len(evals) if evals else 0
        turn_passed = avg_score >= eval_threshold

        turn_results.append(ConversationTurnResult(
            turn_index=job["turn_index"],
            input=job["turn"].content,
            output=job["exec_result"].output,
            latency_ms=job["exec_result"].latency_ms,
            evaluations=eval_metrics,
            score=round(avg_score, 1),
            passed=turn_passed,
            tool_calls=job["exec_result"].tool_calls,
        ))

    # Insert error results at correct positions
    for idx, err_result in error_results:
        turn_results.insert(idx, err_result)

    # Extract coherence/retention from the tail of all_eval_results
    coherence_eval = []
    retention_eval = []
    extra_offset = len(eval_jobs)
    if coherence_job:
        r = all_eval_results[extra_offset]
        coherence_eval = r if not isinstance(r, Exception) else []
        extra_offset += 1
    if retention_job:
        r = all_eval_results[extra_offset]
        retention_eval = r if not isinstance(r, Exception) else []

    # Calculate overall conversation metrics
    total_turns = len(turn_results)
    passed_turns = sum(1 for t in turn_results if t.passed)
    avg_score = sum(t.score for t in turn_results) / total_turns if total_turns > 0 else 0
    total_latency = sum(t.latency_ms for t in turn_results)

    coherence_score = coherence_eval[0].score if coherence_eval else 0
    retention_score = retention_eval[0].score if retention_eval else 0

    result = ConversationResult(
        conversation_id=conv_id,
        endpoint=target_endpoint,
        turn_results=turn_results,
        total_turns=total_turns,
        passed_turns=passed_turns,
        avg_score=round(avg_score, 1),
        total_latency_ms=total_latency,
        coherence_score=round(coherence_score, 1),
        context_retention_score=round(retention_score, 1),
    )

    storage.save_conversation_result(result)

    return result.to_dict()


@app.get("/api/conversation-results")
async def list_conversation_results(conversation_id: Optional[str] = None, limit: int = 50):
    """List conversation test results."""
    results = storage.list_conversation_results(conversation_id=conversation_id, limit=limit)
    return [r.to_dict() for r in results]


@app.get("/api/conversation-results/{result_id}")
async def get_conversation_result(result_id: str):
    """Get detailed conversation result."""
    result = storage.get_conversation_result(result_id)
    if not result:
        raise HTTPException(status_code=404, detail="Conversation result not found")
    return result.to_dict()


# === Agent Scorecard ===

@app.get("/api/scorecard/latest")
async def get_latest_scorecard(endpoint: str = "", threshold: float = 70.0):
    """Generate a scorecard from the most recent results for an endpoint."""
    results = storage.get_history(limit=100)
    if endpoint:
        results = [r for r in results if r.endpoint == endpoint]

    if not results:
        raise HTTPException(status_code=404, detail="No results found")

    result_dicts = [r.to_dict() for r in results]
    ep = endpoint or (result_dicts[0].get("endpoint", "") if result_dicts else "")

    agent_name = ""
    agents = storage.list_agents(active_only=False)
    for agent in agents:
        if agent.endpoint == ep:
            agent_name = agent.name
            break

    scorecard = generate_scorecard(
        results=result_dicts,
        endpoint=ep,
        agent_name=agent_name,
        threshold=threshold,
    )
    return scorecard.to_dict()


@app.post("/api/scorecard/from-results")
async def generate_scorecard_from_results(
    result_ids: List[str] = [],
    endpoint: str = "",
    agent_name: str = "",
    threshold: float = 70.0,
):
    """Generate a scorecard from specific result IDs."""
    results = []
    for rid in result_ids:
        r = storage.get_result(rid)
        if r:
            results.append(r.to_dict())

    if not results:
        raise HTTPException(status_code=404, detail="No results found")

    scorecard = generate_scorecard(
        results=results,
        endpoint=endpoint or results[0].get("endpoint", ""),
        agent_name=agent_name,
        threshold=threshold,
    )
    return scorecard.to_dict()


@app.get("/api/scorecard/{batch_id}")
async def get_scorecard(batch_id: str, threshold: float = 70.0):
    """Generate a scorecard from a batch run's results."""
    batch = storage.get_batch(batch_id)
    if not batch:
        raise HTTPException(status_code=404, detail="Batch not found")

    results = storage.get_batch_results(batch_id)
    if not results:
        raise HTTPException(status_code=404, detail="No results found for this batch")

    result_dicts = [r.to_dict() for r in results]
    endpoint = result_dicts[0].get("endpoint", "") if result_dicts else ""

    # Try to find agent name
    agent_name = ""
    agents = storage.list_agents(active_only=False)
    for agent in agents:
        if agent.endpoint == endpoint:
            agent_name = agent.name
            break
    if not agent_name:
        agent_name = batch.name

    scorecard = generate_scorecard(
        results=result_dicts,
        endpoint=endpoint,
        agent_name=agent_name,
        threshold=threshold,
    )
    return scorecard.to_dict()


# === Evaluation Wizard ===

class WizardRequest(BaseModel):
    """One-click evaluation wizard request."""
    endpoint: str = Field(..., description="Agent endpoint URL")
    scope: str = Field("standard", description="quick, standard, comprehensive, or custom")
    template_packs: Optional[List[str]] = Field(None, description="Custom template pack IDs (for scope=custom)")
    threshold: float = Field(70.0, description="Pass/fail threshold")
    auth: Optional[dict] = Field(None, description="Auth configuration")


@app.post("/api/wizard/run")
async def run_evaluation_wizard(request: WizardRequest):
    """
    One-click evaluation wizard.

    1. Auto-discovers agent capabilities
    2. Selects appropriate test templates based on scope
    3. Runs all tests as a batch
    4. Returns scorecard with categorized results
    """
    try:
        # Step 1: Discover agent
        introspector = AgentIntrospector()
        # Build auth headers from request if provided (for introspection too)
        introspect_headers = None
        if request.auth and request.auth.get("auth_type", "none") != "none":
            introspect_headers = AuthConfigRequest(**request.auth).to_headers()
        try:
            profile = await introspector.introspect(request.endpoint, headers=introspect_headers)
        except Exception:
            profile = AgentProfile(
                endpoint=request.endpoint,
                name="Unknown Agent",
                purpose="Agent at " + request.endpoint,
                agent_type="simple",
                domain="general",
                capabilities=[],
                raw_response="",
            )

        # Step 2: Select templates based on scope
        if request.scope == "custom" and request.template_packs:
            selected_packs = request.template_packs
        else:
            # Get suggestions based on agent type
            suggested = suggest_templates(profile.agent_type)

            if request.scope == "quick":
                selected_packs = [suggested[0]] if suggested else ["general_agent"]
            elif request.scope == "standard":
                selected_packs = suggested[:2] if len(suggested) >= 2 else suggested
            else:  # comprehensive
                selected_packs = suggested

        # Step 3: Gather tests from all selected packs
        all_tests = []
        for pack_id in selected_packs:
            tests = get_template_tests(pack_id)
            for t in tests:
                all_tests.append(t)

        if not all_tests:
            raise HTTPException(status_code=400, detail="No tests available for selected scope")

        # Limit tests based on scope
        if request.scope == "quick":
            all_tests = all_tests[:5]
        elif request.scope == "standard":
            all_tests = all_tests[:20]
        # comprehensive = all tests

        # Step 4: Build auth headers (with auto-detect fallback)
        headers = _resolve_auth_headers(auth_dict=request.auth, endpoint=request.endpoint)

        # Step 5: Run batch
        batch = Batch(name=f"Wizard: {request.scope} eval")
        storage.save_batch(batch)

        results = []
        for test_data in all_tests:
            test_input = test_data.get("input", "")
            test_expected = test_data.get("expected")
            test_context = test_data.get("context")
            test_metrics = test_data.get("metrics")

            # Execute
            exec_result = await _execute_with_autostart(
                request.endpoint, test_input, headers=headers, context=test_context
            )

            # Evaluate
            evals = await asyncio.to_thread(
                evaluator.evaluate,
                input_text=test_input,
                output=exec_result.output,
                expected=test_expected,
                context=test_context,
                metrics=test_metrics,
                threshold=request.threshold,
                tool_calls=exec_result.tool_calls,
                expected_tool_calls=test_data.get("expected_tool_calls"),
            )

            eval_metrics = [
                EvalMetric(metric=e.metric, score=e.score, passed=e.passed, reason=e.reason, scored_by=getattr(e, 'scored_by', 'heuristic'))
                for e in evals
            ]
            avg_score = sum(e.score for e in evals) / len(evals) if evals else 0
            all_passed = all(e.passed for e in evals) if evals else False

            result = Result(
                endpoint=request.endpoint,
                input=test_input,
                output=exec_result.output,
                score=avg_score,
                passed=all_passed,
                latency_ms=exec_result.latency_ms,
                evaluations=eval_metrics,
                batch_id=batch.id,
                expected=test_expected,
            )
            storage.save_result(result)
            results.append(result)

        # Update batch
        batch.total_tests = len(results)
        batch.passed_tests = sum(1 for r in results if r.passed)
        batch.avg_score = sum(r.score for r in results) / len(results) if results else 0
        batch.completed_at = datetime.utcnow().isoformat()
        storage.save_batch(batch)

        # Step 6: Generate scorecard
        result_dicts = [r.to_dict() for r in results]
        scorecard = generate_scorecard(
            results=result_dicts,
            endpoint=request.endpoint,
            agent_name=profile.purpose or f"{profile.agent_type} agent",
            threshold=request.threshold,
        )

        return {
            "batch_id": batch.id,
            "agent_profile": {
                "agent_type": profile.agent_type,
                "name": profile.name,
                "capabilities": profile.capabilities,
                "domain": profile.domain,
                "purpose": profile.purpose,
            },
            "scope": request.scope,
            "template_packs_used": selected_packs,
            "scorecard": scorecard.to_dict(),
        }

    except HTTPException:
        raise
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Wizard error: {str(e)}")


# === Test Templates ===

@app.get("/api/templates")
async def get_templates():
    """List all available test template packs."""
    return list_template_packs()


@app.get("/api/templates/suggest/{agent_type}")
async def suggest_template_packs(agent_type: str):
    """Suggest template packs based on agent type."""
    suggestions = suggest_templates(agent_type)
    packs = list_template_packs()
    return [p for p in packs if p["id"] in suggestions]


@app.get("/api/templates/{pack_id}")
async def get_template_pack(pack_id: str):
    """Get a specific template pack with its test cases."""
    data = load_template_pack(pack_id)
    if not data:
        raise HTTPException(status_code=404, detail=f"Template pack '{pack_id}' not found")
    return data


@app.get("/api/templates/{pack_id}/tests")
async def get_template_pack_tests(pack_id: str):
    """Get just the test cases from a template pack."""
    tests = get_template_tests(pack_id)
    if not tests:
        raise HTTPException(status_code=404, detail=f"Template pack '{pack_id}' not found or empty")
    return tests


@app.post("/api/templates/{pack_id}/create-suite")
async def create_suite_from_template(pack_id: str, name: Optional[str] = None, endpoint: Optional[str] = None):
    """Create a test suite from a template pack."""
    data = load_template_pack(pack_id)
    if not data:
        raise HTTPException(status_code=404, detail=f"Template pack '{pack_id}' not found")

    suite_name = name or data.get("name", f"Suite from {pack_id}")
    description = data.get("description", "")

    suite = Suite(name=suite_name, description=description, endpoint=endpoint)
    storage.save_suite(suite)

    # Add tests from template
    for test_data in data.get("tests", []):
        test = Test(
            input=test_data.get("input", ""),
            suite_id=suite.id,
            name=test_data.get("name"),
            expected=test_data.get("expected"),
            context=test_data.get("context"),
            metrics=test_data.get("metrics"),
            expected_tool_calls=test_data.get("expected_tool_calls"),
        )
        storage.save_test(test)

    return {
        "suite_id": suite.id,
        "name": suite_name,
        "test_count": len(data.get("tests", [])),
    }


# === Baselines & Regression Detection ===

class SaveBaselineRequest(BaseModel):
    """Request to save a baseline from a batch."""
    name: str = Field(..., description="Name for this baseline")
    batch_id: Optional[str] = Field(None, description="Batch ID to snapshot")
    result_ids: Optional[List[str]] = Field(None, description="Specific result IDs")
    agent_endpoint: Optional[str] = None
    suite_id: Optional[str] = None


@app.get("/api/baselines")
async def list_baselines(endpoint: Optional[str] = None):
    """List all saved baselines, optionally filtered by endpoint."""
    return storage.list_baselines(agent_endpoint=endpoint)


@app.post("/api/baselines")
async def save_baseline(request: SaveBaselineRequest):
    """Save an evaluation run as a baseline for regression detection."""
    import uuid

    # Collect results
    results = []
    if request.batch_id:
        results = storage.get_batch_results(request.batch_id)
    elif request.result_ids:
        for rid in request.result_ids:
            r = storage.get_result(rid)
            if r:
                results.append(r)

    if not results:
        raise HTTPException(status_code=400, detail="No results found for baseline")

    # Build metrics snapshot: avg score per metric
    metric_totals = {}
    metric_counts = {}
    for r in results:
        r_dict = r.to_dict() if hasattr(r, 'to_dict') else r
        for ev in r_dict.get("evaluations", []):
            m = ev.get("metric", "")
            if m:
                metric_totals[m] = metric_totals.get(m, 0) + ev.get("score", 0)
                metric_counts[m] = metric_counts.get(m, 0) + 1

    metrics_snapshot = {
        m: round(metric_totals[m] / metric_counts[m], 1)
        for m in metric_totals
    }

    total_tests = len(results)
    passed_tests = sum(
        1 for r in results
        if (r.passed if hasattr(r, 'passed') else r.get("passed", False))
    )
    avg_score = round(
        sum(
            r.score if hasattr(r, 'score') else r.get("score", 0)
            for r in results
        ) / total_tests, 1
    ) if total_tests > 0 else 0

    endpoint = request.agent_endpoint
    if not endpoint and results:
        r0 = results[0]
        endpoint = r0.endpoint if hasattr(r0, 'endpoint') else r0.get("endpoint", "")

    baseline_id = str(uuid.uuid4())[:8]
    storage.save_baseline(
        baseline_id=baseline_id,
        name=request.name,
        agent_endpoint=endpoint or "",
        suite_id=request.suite_id,
        metrics_snapshot=metrics_snapshot,
        total_tests=total_tests,
        passed_tests=passed_tests,
        avg_score=avg_score,
    )

    return {
        "id": baseline_id,
        "name": request.name,
        "metrics_count": len(metrics_snapshot),
        "total_tests": total_tests,
        "passed_tests": passed_tests,
        "avg_score": avg_score,
    }


@app.get("/api/baselines/{baseline_id}")
async def get_baseline(baseline_id: str):
    """Get a specific baseline."""
    baseline = storage.get_baseline(baseline_id)
    if not baseline:
        raise HTTPException(status_code=404, detail="Baseline not found")
    return baseline


@app.delete("/api/baselines/{baseline_id}")
async def delete_baseline(baseline_id: str):
    """Delete a baseline."""
    storage.delete_baseline(baseline_id)
    return {"deleted": True}


@app.get("/api/baselines/{baseline_id}/compare/{batch_id}")
async def compare_to_baseline(baseline_id: str, batch_id: str, threshold: float = 5.0):
    """
    Compare a batch run against a baseline.

    Returns per-metric deltas with regression flags.
    threshold: percentage drop that counts as a regression (default 5%)
    """
    baseline = storage.get_baseline(baseline_id)
    if not baseline:
        raise HTTPException(status_code=404, detail="Baseline not found")

    # Get batch results
    results = storage.get_batch_results(batch_id)
    if not results:
        raise HTTPException(status_code=404, detail="Batch results not found")

    # Build current metrics snapshot
    metric_totals = {}
    metric_counts = {}
    for r in results:
        r_dict = r.to_dict() if hasattr(r, 'to_dict') else r
        for ev in r_dict.get("evaluations", []):
            m = ev.get("metric", "")
            if m:
                metric_totals[m] = metric_totals.get(m, 0) + ev.get("score", 0)
                metric_counts[m] = metric_counts.get(m, 0) + 1

    current_metrics = {
        m: round(metric_totals[m] / metric_counts[m], 1)
        for m in metric_totals
    }

    total_tests = len(results)
    passed_tests = sum(
        1 for r in results
        if (r.passed if hasattr(r, 'passed') else r.get("passed", False))
    )
    current_avg = round(
        sum(
            r.score if hasattr(r, 'score') else r.get("score", 0)
            for r in results
        ) / total_tests, 1
    ) if total_tests > 0 else 0

    baseline_metrics = baseline.get("metrics_snapshot", {})

    # Compute deltas
    all_metric_names = sorted(set(list(baseline_metrics.keys()) + list(current_metrics.keys())))
    deltas = []
    regressions = []
    improvements = []

    for m in all_metric_names:
        b_score = baseline_metrics.get(m)
        c_score = current_metrics.get(m)

        delta_entry = {"metric": m}

        if b_score is not None and c_score is not None:
            delta = round(c_score - b_score, 1)
            delta_entry["baseline_score"] = b_score
            delta_entry["current_score"] = c_score
            delta_entry["delta"] = delta
            if delta < -threshold:
                delta_entry["status"] = "regressed"
                regressions.append(m)
            elif delta > threshold:
                delta_entry["status"] = "improved"
                improvements.append(m)
            else:
                delta_entry["status"] = "unchanged"
        elif b_score is not None:
            delta_entry["baseline_score"] = b_score
            delta_entry["current_score"] = None
            delta_entry["delta"] = None
            delta_entry["status"] = "removed"
        else:
            delta_entry["baseline_score"] = None
            delta_entry["current_score"] = c_score
            delta_entry["delta"] = None
            delta_entry["status"] = "new"

        deltas.append(delta_entry)

    overall_delta = round(current_avg - baseline.get("avg_score", 0), 1)

    return {
        "baseline": {
            "id": baseline["id"],
            "name": baseline["name"],
            "avg_score": baseline.get("avg_score", 0),
            "total_tests": baseline.get("total_tests", 0),
            "passed_tests": baseline.get("passed_tests", 0),
            "created_at": baseline.get("created_at", ""),
        },
        "current": {
            "batch_id": batch_id,
            "avg_score": current_avg,
            "total_tests": total_tests,
            "passed_tests": passed_tests,
        },
        "overall_delta": overall_delta,
        "overall_status": "regressed" if overall_delta < -threshold else ("improved" if overall_delta > threshold else "unchanged"),
        "metric_deltas": deltas,
        "regressions": regressions,
        "improvements": improvements,
        "regression_count": len(regressions),
        "improvement_count": len(improvements),
    }


# === Test Variant Generation ===

class VariantRequest(BaseModel):
    """Request for generating test variants."""
    input: str = Field(..., description="Base test input to generate variants from")
    count: int = Field(5, ge=1, le=20, description="Number of variants to generate")
    types: Optional[List[str]] = Field(None, description="Variant types: rephrase, formal, informal, adversarial, typo, caps")
    expected: Optional[str] = None
    metrics: Optional[List[str]] = None


@app.post("/api/tests/generate-variants")
async def generate_test_variants(request: VariantRequest):
    """Generate test variants from a base input."""
    from agent_eval.core.test_variants import generate_variants

    variants = generate_variants(
        input_text=request.input,
        count=request.count,
        types=request.types,
        expected=request.expected,
        metrics=request.metrics,
    )

    return {
        "original_input": request.input,
        "count": len(variants),
        "variants": variants,
    }


# === Consistency Testing ===

class ConsistencyRequest(BaseModel):
    """Request for consistency/flakiness testing."""
    endpoint: str = Field(..., description="Agent endpoint URL")
    input: str = Field(..., description="Test input to repeat")
    expected: Optional[str] = None
    context: Optional[List[str]] = None
    metrics: Optional[List[str]] = None
    threshold: float = 70.0
    runs: int = Field(3, ge=2, le=10, description="Number of runs (2-10)")
    auth: Optional[dict] = None


@app.post("/api/test-consistency")
async def run_consistency_test(request: ConsistencyRequest):
    """
    Run the same test N times and measure output consistency.

    Returns variance analysis, flakiness detection, and per-run details.
    """
    headers = _resolve_auth_headers(auth_dict=request.auth, endpoint=request.endpoint)

    runs = []
    outputs = []
    scores = []
    pass_results = []

    for i in range(request.runs):
        try:
            exec_result = await _execute_with_autostart(
                request.endpoint, request.input, headers=headers, context=request.context
            )

            evals = await asyncio.to_thread(
                evaluator.evaluate,
                input_text=request.input,
                output=exec_result.output,
                expected=request.expected,
                context=request.context,
                metrics=request.metrics,
                threshold=request.threshold,
            )

            avg_score = sum(e.score for e in evals) / len(evals) if evals else 0
            all_passed = all(e.passed for e in evals) if evals else False

            runs.append({
                "run": i + 1,
                "output": exec_result.output,
                "score": round(avg_score, 1),
                "passed": all_passed,
                "latency_ms": exec_result.latency_ms,
                "evaluations": [
                    {"metric": e.metric, "score": e.score, "passed": e.passed}
                    for e in evals
                ],
            })
            outputs.append(exec_result.output)
            scores.append(avg_score)
            pass_results.append(all_passed)

        except Exception as e:
            runs.append({
                "run": i + 1,
                "output": "",
                "score": 0,
                "passed": False,
                "latency_ms": 0,
                "error": str(e),
            })
            outputs.append("")
            scores.append(0)
            pass_results.append(False)

    # Compute consistency metrics
    score_mean = sum(scores) / len(scores) if scores else 0
    score_variance = sum((s - score_mean) ** 2 for s in scores) / len(scores) if scores else 0
    score_std = score_variance ** 0.5

    # Output similarity: pairwise comparison using simple word overlap
    def word_overlap(a, b):
        wa = set(a.lower().split())
        wb = set(b.lower().split())
        if not wa and not wb:
            return 1.0
        if not wa or not wb:
            return 0.0
        return len(wa & wb) / len(wa | wb)

    overlaps = []
    for i in range(len(outputs)):
        for j in range(i + 1, len(outputs)):
            overlaps.append(word_overlap(outputs[i], outputs[j]))

    avg_overlap = sum(overlaps) / len(overlaps) if overlaps else 1.0
    consistency_score = round(avg_overlap * 100, 1)

    # Flakiness: if pass/fail is inconsistent
    pass_count = sum(1 for p in pass_results if p)
    fail_count = len(pass_results) - pass_count
    is_flaky = 0 < pass_count < len(pass_results)

    latencies = [r["latency_ms"] for r in runs if r.get("latency_ms", 0) > 0]
    latency_mean = round(sum(latencies) / len(latencies), 1) if latencies else 0
    latency_max = max(latencies) if latencies else 0
    latency_min = min(latencies) if latencies else 0

    return {
        "input": request.input,
        "endpoint": request.endpoint,
        "total_runs": request.runs,
        "consistency_score": consistency_score,
        "is_flaky": is_flaky,
        "score_mean": round(score_mean, 1),
        "score_std": round(score_std, 1),
        "pass_count": pass_count,
        "fail_count": fail_count,
        "latency_mean": latency_mean,
        "latency_min": latency_min,
        "latency_max": latency_max,
        "runs": runs,
    }


# === Multi-Agent Batch Comparison ===

class MultiAgentCompareRequest(BaseModel):
    """Request to compare multiple agents."""
    name: str = Field(..., description="Name for this comparison")
    agent_ids: List[str] = Field(..., description="List of agent IDs to compare")
    suite_id: Optional[str] = Field(None, description="Test suite to use")


@app.post("/api/compare")
async def run_multi_agent_comparison(request: MultiAgentCompareRequest):
    """Run the same tests against multiple agents and compare results."""
    if len(request.agent_ids) < 2:
        raise HTTPException(status_code=400, detail="Need at least 2 agents for comparison")

    # Validate agents exist
    agents = []
    for agent_id in request.agent_ids:
        agent = storage.get_agent(agent_id)
        if not agent:
            raise HTTPException(status_code=404, detail=f"Agent {agent_id} not found")
        agents.append(agent)

    # Get test suite
    suite = None
    tests = []
    if request.suite_id:
        suite = storage.get_suite(request.suite_id)
        if not suite:
            raise HTTPException(status_code=404, detail="Suite not found")
        tests = suite.tests
    else:
        raise HTTPException(status_code=400, detail="Suite ID is required for comparison")

    if len(tests) < 1:
        raise HTTPException(status_code=400, detail="Suite has no tests")

    # Create batch record
    batch = MultiAgentBatch(
        name=request.name,
        agent_ids=request.agent_ids,
        suite_id=request.suite_id,
        status="running",
    )
    storage.save_multi_batch(batch)

    # Run tests for each agent
    agent_results = {}
    all_scores = {}  # For finding best agent

    for agent in agents:
        scores = []
        passed = 0
        total_latency = 0
        test_details = []

        # Get auth headers
        headers = {}
        if agent.auth_type != "none" and agent.auth_config:
            auth_config = AuthConfigRequest(**agent.auth_config)
            headers = auth_config.to_headers()

        for test in tests:
            try:
                result = await _execute_with_autostart(
                    agent.endpoint,
                    test.input,
                    headers=headers,
                    context=test.context,
                )

                # Evaluate
                eval_results = await asyncio.to_thread(
                    evaluator.evaluate,
                    input_text=test.input,
                    output=result.output,
                    expected=test.expected,
                    context=test.context,
                    metrics=test.metrics,
                )

                # Calculate score from evaluation results
                if eval_results:
                    test_score = sum(r.score for r in eval_results) / len(eval_results)
                    test_passed = all(r.passed for r in eval_results)
                else:
                    test_score = 0
                    test_passed = False

                scores.append(test_score)
                if test_passed:
                    passed += 1
                total_latency += result.latency_ms

                test_details.append({
                    "test_id": test.id,
                    "input": test.input,
                    "output": result.output,
                    "score": test_score,
                    "passed": test_passed,
                    "latency_ms": result.latency_ms,
                })

            except Exception as e:
                scores.append(0)
                test_details.append({
                    "test_id": test.id,
                    "input": test.input,
                    "output": "",
                    "score": 0,
                    "passed": False,
                    "error": str(e),
                })

        # Calculate agent summary
        avg_score = sum(scores) / len(scores) if scores else 0
        avg_latency = total_latency / len(tests) if tests else 0

        agent_results[agent.id] = {
            "agent_id": agent.id,
            "agent_name": agent.name,
            "total": len(tests),
            "passed": passed,
            "failed": len(tests) - passed,
            "pass_rate": round(passed / len(tests) * 100, 1) if tests else 0,
            "avg_score": round(avg_score, 1),
            "avg_latency_ms": round(avg_latency, 1),
            "test_details": test_details,
        }
        all_scores[agent.id] = avg_score

        # Update agent last tested
        storage.update_agent_last_tested(agent.id)

    # Determine best agent
    best_agent_id = max(all_scores, key=all_scores.get) if all_scores else None

    # Update batch
    batch.status = "completed"
    batch.agent_results = {k: {kk: vv for kk, vv in v.items() if kk != "test_details"} for k, v in agent_results.items()}
    batch.best_agent_id = best_agent_id
    batch.completed_at = datetime.utcnow().isoformat()
    storage.save_multi_batch(batch)

    # Build comparison matrix
    matrix = []
    for test in tests:
        row = {"test_id": test.id, "input": test.input[:50] + "..." if len(test.input) > 50 else test.input}
        for agent_id, results in agent_results.items():
            test_detail = next((t for t in results["test_details"] if t["test_id"] == test.id), None)
            if test_detail:
                row[agent_id] = {
                    "score": test_detail["score"],
                    "passed": test_detail["passed"],
                    "latency_ms": test_detail.get("latency_ms", 0),
                }
        matrix.append(row)

    return {
        "id": batch.id,
        "name": batch.name,
        "status": "completed",
        "agent_count": len(agents),
        "test_count": len(tests),
        "best_agent": {
            "id": best_agent_id,
            "name": next((a.name for a in agents if a.id == best_agent_id), "Unknown"),
            "avg_score": agent_results[best_agent_id]["avg_score"] if best_agent_id else 0,
        },
        "agent_results": [
            {
                "id": agent_id,
                "name": agent_results[agent_id]["agent_name"],
                "total": agent_results[agent_id]["total"],
                "passed": agent_results[agent_id]["passed"],
                "pass_rate": agent_results[agent_id]["pass_rate"],
                "avg_score": agent_results[agent_id]["avg_score"],
                "avg_latency_ms": agent_results[agent_id]["avg_latency_ms"],
                "is_best": agent_id == best_agent_id,
            }
            for agent_id in request.agent_ids
        ],
        "matrix": matrix,
        "created_at": batch.created_at,
        "completed_at": batch.completed_at,
    }


@app.get("/api/compare")
async def list_comparisons():
    """List all multi-agent comparisons."""
    batches = storage.list_multi_batches()
    result = []
    for batch in batches:
        best_agent = storage.get_agent(batch.best_agent_id) if batch.best_agent_id else None
        result.append({
            "id": batch.id,
            "name": batch.name,
            "agent_count": len(batch.agent_ids),
            "status": batch.status,
            "best_agent_name": best_agent.name if best_agent else None,
            "created_at": batch.created_at,
            "completed_at": batch.completed_at,
        })
    return result


@app.get("/api/compare/{comparison_id}")
async def get_comparison(comparison_id: str):
    """Get detailed comparison results."""
    batch = storage.get_multi_batch(comparison_id)
    if not batch:
        raise HTTPException(status_code=404, detail="Comparison not found")

    # Get agent details
    agents = []
    for agent_id in batch.agent_ids:
        agent = storage.get_agent(agent_id)
        if agent:
            agent_result = batch.agent_results.get(agent_id, {})
            agents.append({
                "id": agent.id,
                "name": agent.name,
                "total": agent_result.get("total", 0),
                "passed": agent_result.get("passed", 0),
                "pass_rate": agent_result.get("pass_rate", 0),
                "avg_score": agent_result.get("avg_score", 0),
                "avg_latency_ms": agent_result.get("avg_latency_ms", 0),
                "is_best": agent.id == batch.best_agent_id,
            })

    best_agent = storage.get_agent(batch.best_agent_id) if batch.best_agent_id else None

    return {
        "id": batch.id,
        "name": batch.name,
        "status": batch.status,
        "agent_count": len(batch.agent_ids),
        "best_agent": {
            "id": batch.best_agent_id,
            "name": best_agent.name if best_agent else "Unknown",
        } if batch.best_agent_id else None,
        "agents": agents,
        "created_at": batch.created_at,
        "completed_at": batch.completed_at,
    }


# Run with: uvicorn agent_eval.web.app:app --reload
