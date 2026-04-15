"""
OpenTelemetry Tracing Module for Lilly Agent Eval.

Provides:
  - OTel provider initialization (configure once at startup)
  - Span helpers for instrumenting eval pipeline steps
  - Trace context propagation for external agent HTTP calls
  - Built-in persistent trace store (saved to file, survives server restarts)

Works alongside LangSmith:
  - LangSmith enabled only  → traces go to LangSmith cloud
  - OTel enabled only       → traces stored locally + optionally sent to Jaeger/Grafana
  - Both enabled            → traces go to both simultaneously
  - Neither enabled         → only local trace list (default)

Configuration via environment variables:
  OTEL_ENABLED=true
  OTEL_SERVICE_NAME=agent-eval-platform
  OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4317   (optional — Jaeger/Grafana)
"""

import os
import json
import time
import logging
import threading
from collections import deque
from pathlib import Path
from typing import Optional, Dict, Any, List
from contextlib import contextmanager

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────
# 1. OTel availability detection
# ─────────────────────────────────────────────

_otel_available = False
_tracer = None

try:
    from opentelemetry import trace
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor, SpanExporter, SpanExportResult
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
    from opentelemetry.trace import StatusCode, Status
    from opentelemetry.trace.propagation import get_current_span
    from opentelemetry.propagate import inject as otel_inject
    _otel_available = True
except ImportError:
    pass


# ─────────────────────────────────────────────
# 2. Persistent trace store (saved to file)
# ─────────────────────────────────────────────

_MAX_STORED_TRACES = 200
_trace_store: deque = deque(maxlen=_MAX_STORED_TRACES)
_trace_lock = threading.Lock()

# File path for persistent storage
_TRACE_FILE = Path(os.getenv("OTEL_TRACE_FILE", Path.cwd() / "trace_store.json"))


def _save_traces_to_file():
    """Save current traces to a JSON file for persistence across server restarts."""
    try:
        data = list(_trace_store)
        _TRACE_FILE.write_text(json.dumps(data, default=str), encoding="utf-8")
    except Exception as e:
        logger.debug(f"Could not save traces to file: {e}")


def _load_traces_from_file():
    """Load previously saved traces from the JSON file on startup."""
    try:
        if _TRACE_FILE.exists():
            data = json.loads(_TRACE_FILE.read_text(encoding="utf-8"))
            if isinstance(data, list):
                with _trace_lock:
                    for item in data[-_MAX_STORED_TRACES:]:
                        _trace_store.append(item)
                logger.info(f"Loaded {len(_trace_store)} spans from {_TRACE_FILE}")
    except Exception as e:
        logger.debug(f"Could not load traces from file: {e}")


# Load saved traces on module import
_load_traces_from_file()


class PersistentSpanExporter(SpanExporter if _otel_available else object):
    """Custom exporter that stores finished spans and persists them to a JSON file."""

    def export(self, spans):
        for span in spans:
            span_data = {
                "trace_id": format(span.context.trace_id, "032x"),
                "span_id": format(span.context.span_id, "016x"),
                "parent_span_id": format(span.parent.span_id, "016x") if span.parent else None,
                "name": span.name,
                "start_time": span.start_time / 1e9,  # nanosec → sec
                "end_time": span.end_time / 1e9,
                "duration_ms": round((span.end_time - span.start_time) / 1e6, 1),
                "status": span.status.status_code.name if span.status else "UNSET",
                "attributes": dict(span.attributes) if span.attributes else {},
            }
            with _trace_lock:
                _trace_store.append(span_data)
        _save_traces_to_file()
        return SpanExportResult.SUCCESS

    def shutdown(self):
        _save_traces_to_file()

    def force_flush(self, timeout_millis=0):
        _save_traces_to_file()
        return True


def get_stored_traces(limit: int = 50) -> List[Dict]:
    """Get recent traces from the in-memory store, grouped by trace_id."""
    with _trace_lock:
        all_spans = list(_trace_store)

    # Group spans by trace_id
    traces_map: Dict[str, Dict] = {}
    for span in all_spans:
        tid = span["trace_id"]
        if tid not in traces_map:
            traces_map[tid] = {
                "trace_id": tid,
                "start_time": span["start_time"],
                "spans": [],
                "total_duration_ms": 0,
            }
        traces_map[tid]["spans"].append(span)

    # Add descriptions and calculate total duration, sort spans within each trace
    traces = []
    for t in traces_map.values():
        t["spans"].sort(key=lambda s: s["start_time"])
        for s in t["spans"]:
            s["description"] = get_span_description(s["name"])
        if t["spans"]:
            t["start_time"] = t["spans"][0]["start_time"]
            t["total_duration_ms"] = round(
                sum(s["duration_ms"] for s in t["spans"]), 1
            )
            # Use the root span name or first span name as the trace label
            root_spans = [s for s in t["spans"] if s["parent_span_id"] is None]
            t["name"] = root_spans[0]["name"] if root_spans else t["spans"][0]["name"]
            t["span_count"] = len(t["spans"])
        traces.append(t)

    # Sort by most recent first
    traces.sort(key=lambda t: t["start_time"], reverse=True)
    return traces[:limit]


def clear_stored_traces():
    """Clear all stored traces from memory and file."""
    with _trace_lock:
        _trace_store.clear()
    _save_traces_to_file()


def is_otel_enabled() -> bool:
    """Check if OpenTelemetry tracing is available.

    OTel is enabled by default when the packages are installed.
    Set OTEL_ENABLED=false to explicitly disable.
    """
    if not _otel_available:
        return False
    enabled = os.getenv("OTEL_ENABLED", "true").lower()
    return enabled != "false"


def init_otel_tracing() -> bool:
    """
    Initialize the OpenTelemetry tracing provider.

    Always adds the built-in PersistentSpanExporter (traces saved to file).
    Optionally adds OTLP exporter if Jaeger/Grafana endpoint is configured.

    Call once at application startup (e.g., in app.py or cli.py).
    Safe to call multiple times — only initializes once.

    Returns:
        True if OTel was initialized, False otherwise.
    """
    global _tracer

    if not is_otel_enabled():
        logger.debug("OpenTelemetry tracing is not enabled (set OTEL_ENABLED=true)")
        return False

    if _tracer is not None:
        return True  # already initialized

    try:
        service_name = os.getenv("OTEL_SERVICE_NAME", "agent-eval-platform")
        endpoint = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "").strip()

        resource = Resource.create({"service.name": service_name})
        provider = TracerProvider(resource=resource)

        # Always add persistent exporter (traces saved to file, survive restarts)
        persistent_exporter = PersistentSpanExporter()
        provider.add_span_processor(BatchSpanProcessor(persistent_exporter))
        logger.info(f"OpenTelemetry: persistent trace store enabled (file: {_TRACE_FILE})")

        # Optionally add OTLP exporter (Jaeger/Grafana/Datadog) — only if explicitly configured
        if endpoint:
            try:
                otlp_exporter = OTLPSpanExporter(endpoint=endpoint, insecure=True)
                provider.add_span_processor(BatchSpanProcessor(otlp_exporter))
                logger.info(f"OpenTelemetry: OTLP exporter → {endpoint}")
            except Exception as e:
                logger.debug(f"OTLP exporter not configured: {e}")

        trace.set_tracer_provider(provider)
        _tracer = trace.get_tracer("agent-eval", "3.0.0")

        logger.info(f"OpenTelemetry initialized: service={service_name}")
        return True
    except Exception as e:
        logger.warning(f"Failed to initialize OpenTelemetry: {e}")
        return False


def get_tracer():
    """Get the OTel tracer instance, or None if not initialized."""
    global _tracer
    if _tracer is None and is_otel_enabled():
        init_otel_tracing()
    return _tracer


# ─────────────────────────────────────────────
# 2. Span helpers for eval pipeline
# ─────────────────────────────────────────────

@contextmanager
def otel_span(name: str, attributes: Optional[Dict[str, Any]] = None):
    """
    Context manager that creates an OTel span.

    Usage:
        with otel_span("http-call-agent", {"endpoint": url}) as span:
            response = await client.post(url, ...)
            span.set_attribute("http.status_code", response.status_code)

    If OTel is not enabled, yields a no-op object so callers don't need guards.
    """
    tracer = get_tracer()
    if tracer is None:
        yield _NoOpSpan()
        return

    with tracer.start_as_current_span(name) as span:
        if attributes:
            for key, value in attributes.items():
                if value is not None:
                    span.set_attribute(str(key), _safe_attr(value))
        try:
            yield span
        except Exception as e:
            span.set_status(Status(StatusCode.ERROR, str(e)))
            span.record_exception(e)
            raise


def inject_trace_headers(headers: dict) -> dict:
    """
    Inject OTel trace context into HTTP headers.

    This adds the 'traceparent' header so external agents that also
    use OTel will link their spans to the same trace.

    Args:
        headers: Existing HTTP headers dict (modified in-place and returned).

    Returns:
        The headers dict with traceparent injected (if OTel is enabled).
    """
    if is_otel_enabled() and _otel_available:
        try:
            otel_inject(headers)
        except Exception:
            pass
    return headers


def record_span_event(span, name: str, attributes: Optional[Dict[str, Any]] = None):
    """Add an event to a span (e.g., metric score, error detail)."""
    if span is not None and hasattr(span, "add_event"):
        safe_attrs = {}
        if attributes:
            for k, v in attributes.items():
                safe_attrs[str(k)] = _safe_attr(v)
        span.add_event(name, attributes=safe_attrs)


def _safe_attr(value: Any) -> Any:
    """Convert a value to an OTel-safe attribute type (str, int, float, bool)."""
    if isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


class _NoOpSpan:
    """No-op span for when OTel is not enabled. All methods are safe to call."""
    def set_attribute(self, key, value):
        pass

    def set_status(self, status):
        pass

    def add_event(self, name, **kwargs):
        pass

    def record_exception(self, exception):
        pass

    def get_span_context(self):
        return None


# ─────────────────────────────────────────────
# Human-readable span descriptions
# ─────────────────────────────────────────────

SPAN_DESCRIPTIONS = {
    "evaluate_test": "Full evaluation run — agent call + all metric scoring",
    "execute_agent_call": "HTTP request sent to the agent endpoint",
    "metric.answer_relevancy": "Checks if the answer addresses the question asked (LLM judge)",
    "metric.faithfulness": "Checks if the answer is grounded in the provided context (LLM judge)",
    "metric.contextual_relevancy": "Checks if the retrieved context is relevant to the question (LLM judge)",
    "metric.hallucination": "Checks if the answer contains made-up information (LLM judge)",
    "metric.toxicity": "Checks for harmful, offensive, or toxic language",
    "metric.bias": "Checks for biased or discriminatory language",
    "metric.correctness": "Compares the answer to the expected output",
    "metric.task_completion": "Checks if the agent completed its assigned task",
    "metric.tool_correctness": "Checks if the agent called the correct tools",
    "metric.tool_order": "Checks if tools were called in the correct sequence",
    "metric.context_retention": "Checks if the agent remembers prior conversation turns",
    "metric.agent_reasoning": "Checks if the agent's reasoning chain is logical",
    "metric.failure_recovery": "Checks if the agent recovers gracefully from errors",
    "metric.latency_sla": "Checks if the agent responded within the time limit",
    "metric.groundedness": "Checks if claims are supported by retrieved documents (LLM judge)",
    "metric.context_precision": "Checks if relevant context is ranked higher than irrelevant",
}


def get_span_description(span_name: str) -> str:
    """Get a human-readable 1-line description for a span name."""
    if span_name in SPAN_DESCRIPTIONS:
        return SPAN_DESCRIPTIONS[span_name]
    if span_name.startswith("metric."):
        metric = span_name[7:]
        return f"Evaluating {metric.replace('_', ' ')} metric"
    return ""


def get_spans_for_trace(trace_id: str) -> List[Dict]:
    """Get all spans for a specific trace_id from the in-memory store, with descriptions."""
    with _trace_lock:
        spans = [dict(s) for s in _trace_store if s["trace_id"] == trace_id]
    for s in spans:
        s["description"] = get_span_description(s["name"])
    spans.sort(key=lambda s: s["start_time"])
    return spans


def flush_spans():
    """Force flush all pending spans so they appear in the in-memory store."""
    if _otel_available:
        try:
            provider = trace.get_tracer_provider()
            if hasattr(provider, 'force_flush'):
                provider.force_flush(timeout_millis=5000)
        except Exception:
            pass
