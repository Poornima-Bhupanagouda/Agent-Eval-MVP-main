"""
FastAPI application for the Multi-Agent Research Assistant.

Exposes the multi-agent workflow as a REST API that can be used
with the Lilly Agent Eval platform for testing and evaluation.

Supports two modes:
- Live mode: Uses real LLM API (requires OPENAI_API_KEY or OAuth2 config)
- Demo mode: Returns realistic mock responses (no API key needed)
"""

import os
import time
import random
from typing import Optional, List
from contextlib import asynccontextmanager

# Load environment variables from .env file
from dotenv import load_dotenv
load_dotenv()

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field


# === Demo Mode (no API key required) ===

DEMO_RESPONSES = {
    "default": (
        "Based on my research, here's what I found:\n\n"
        "This is a comprehensive topic that involves several key aspects. "
        "First, it's important to understand the foundational concepts. "
        "The subject has evolved significantly over the past decade, with major "
        "developments in both theory and practice.\n\n"
        "Key findings:\n"
        "1. The area has seen rapid growth and adoption across industries\n"
        "2. Best practices continue to evolve as new research emerges\n"
        "3. There are both benefits and considerations to keep in mind\n\n"
        "In conclusion, this is a dynamic and important field that warrants "
        "continued attention and study."
    ),
    "role_purpose": (
        "I am a Multi-Agent Research Assistant designed to help with research questions. "
        "I use a multi-agent workflow with specialized agents: a Planner that breaks down "
        "queries, a Researcher that gathers information, and a Synthesizer that creates "
        "comprehensive answers. I can handle topics across many domains including science, "
        "technology, history, and current events. I provide context-aware, well-structured "
        "responses with supporting details."
    ),
    "return_policy": (
        "Based on the company's return policy documentation:\n\n"
        "Customers can return most items within 30 days of purchase for a full refund. "
        "Items must be in their original packaging and unused condition. "
        "Digital products and personalized items are non-refundable. "
        "To initiate a return, contact customer support or visit the returns portal online.\n\n"
        "Refunds are typically processed within 5-7 business days after the returned item is received."
    ),
    "technical": (
        "Here's a technical explanation:\n\n"
        "The system architecture follows a microservices pattern with the following components:\n"
        "1. API Gateway - handles routing and authentication\n"
        "2. Service layer - business logic and data processing\n"
        "3. Data layer - persistence and caching\n\n"
        "Key technical considerations include scalability, fault tolerance, and monitoring. "
        "The recommended approach uses containerized deployments with orchestration for "
        "high availability."
    ),
}


def get_demo_response(input_text: str) -> str:
    """Return a realistic demo response based on the input."""
    lower = input_text.lower()

    # Match specific patterns
    if any(kw in lower for kw in ["your role", "your purpose", "who are you", "what are you", "describe yourself", "what can you"]):
        return DEMO_RESPONSES["role_purpose"]
    if any(kw in lower for kw in ["return policy", "refund", "return item"]):
        return DEMO_RESPONSES["return_policy"]
    if any(kw in lower for kw in ["technical", "architecture", "system design", "how does it work"]):
        return DEMO_RESPONSES["technical"]

    # Default: generate a contextual response
    response = DEMO_RESPONSES["default"]

    # Add some variation based on input length
    if len(input_text) > 100:
        response += "\n\nNote: This is a complex query that would benefit from further exploration."
    if "?" in input_text:
        response = f"Great question! {response}"

    return response


# === Initialization ===

research_assistant = None  # Will be None in demo mode
demo_mode = False


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize the research assistant on startup."""
    global research_assistant, demo_mode
    try:
        from sample_agents.agents.research_assistant import ResearchAssistant
        research_assistant = ResearchAssistant()
        demo_mode = False
        print("Research Assistant initialized successfully (LIVE mode)")
    except (ValueError, ImportError) as e:
        research_assistant = None
        demo_mode = True
        print(f"No LLM API key configured: {e}")
        print("Running in DEMO mode - returns mock responses for evaluation testing")
    yield


# === Application Setup ===

app = FastAPI(
    title="Multi-Agent Research Assistant",
    description="A multi-agent workflow that demonstrates real LLM-powered research capabilities",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# === Request/Response Models ===

class QueryRequest(BaseModel):
    """Request for the research assistant."""
    input: str = Field(..., description="The question or topic to research")
    mode: str = Field(
        default="full",
        description="Mode: 'full' (3 agents), 'quick' (1 agent), 'reviewed' (4 agents)"
    )


class AgentResponseModel(BaseModel):
    """Response from a single agent."""
    agent_name: str
    agent_role: str
    content: str
    tokens_used: int
    latency_ms: int


class WorkflowResponse(BaseModel):
    """Response from the multi-agent workflow."""
    response: str = Field(..., description="The final synthesized response")
    workflow_id: str
    total_tokens: int
    total_latency_ms: int
    agent_count: int
    agents: List[AgentResponseModel]
    success: bool


class SimpleResponse(BaseModel):
    """Simple response format for basic API compatibility."""
    output: str
    tokens: Optional[int] = None
    latency_ms: Optional[int] = None


class HealthResponse(BaseModel):
    """Health check response."""
    status: str
    llm_configured: bool
    model: Optional[str] = None


# === API Endpoints ===

@app.get("/", response_model=dict)
async def root():
    """Root endpoint with API information."""
    return {
        "name": "Multi-Agent Research Assistant",
        "version": "1.0.0",
        "description": "A multi-agent workflow demonstrating real LLM-powered research",
        "endpoints": {
            "/chat": "POST - Simple chat interface (OpenAI-compatible)",
            "/research": "POST - Full research workflow",
            "/health": "GET - Health check",
        }
    }


@app.get("/health", response_model=HealthResponse)
async def health_check():
    """Check if the service is healthy and LLM is configured."""
    llm_configured = research_assistant is not None

    return HealthResponse(
        status="healthy" if llm_configured else ("demo" if demo_mode else "degraded"),
        llm_configured=llm_configured,
        model=research_assistant.llm_client.model if research_assistant else "demo-mode",
    )


@app.post("/chat", response_model=SimpleResponse)
async def chat(request: QueryRequest):
    """
    Simple chat endpoint - OpenAI-compatible format.

    This endpoint is designed to work with the Lilly Agent Eval platform.
    It accepts an 'input' field and returns an 'output' field.

    Works in both live mode (with LLM) and demo mode (mock responses).
    """
    # Demo mode - return mock responses
    if demo_mode or not research_assistant:
        start = time.time()
        output = get_demo_response(request.input)
        latency = int((time.time() - start) * 1000) + random.randint(50, 200)
        return SimpleResponse(
            output=output,
            tokens=len(output.split()) * 2,  # Rough token estimate
            latency_ms=latency,
        )

    # Live mode - use real LLM
    try:
        from sample_agents.core.llm_client import LLMError
        # Use mode to determine workflow
        if request.mode == "quick":
            result = await research_assistant.quick_answer(request.input)
        elif request.mode == "reviewed":
            result = await research_assistant.research_with_review(request.input)
        else:
            result = await research_assistant.research(request.input)

        if not result.success:
            raise HTTPException(status_code=500, detail=result.error)

        return SimpleResponse(
            output=result.final_response,
            tokens=result.total_tokens,
            latency_ms=result.total_latency_ms,
        )

    except LLMError as e:
        raise HTTPException(status_code=502, detail=f"LLM Error: {str(e)}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/research", response_model=WorkflowResponse)
async def research(request: QueryRequest):
    """
    Full research endpoint with detailed workflow information.

    Returns all agent responses and metadata for debugging/analysis.
    """
    # Demo mode
    if demo_mode or not research_assistant:
        import uuid
        start = time.time()
        output = get_demo_response(request.input)
        latency = int((time.time() - start) * 1000) + random.randint(100, 500)

        return WorkflowResponse(
            response=output,
            workflow_id=str(uuid.uuid4())[:8],
            total_tokens=len(output.split()) * 2,
            total_latency_ms=latency,
            agent_count=3,
            agents=[
                AgentResponseModel(
                    agent_name="planner", agent_role="planner",
                    content="Plan: Analyze the query, research key aspects, synthesize findings.",
                    tokens_used=50, latency_ms=latency // 3,
                ),
                AgentResponseModel(
                    agent_name="researcher", agent_role="researcher",
                    content="Research findings gathered from available knowledge.",
                    tokens_used=100, latency_ms=latency // 3,
                ),
                AgentResponseModel(
                    agent_name="synthesizer", agent_role="synthesizer",
                    content=output,
                    tokens_used=len(output.split()) * 2, latency_ms=latency // 3,
                ),
            ],
            success=True,
        )

    # Live mode
    try:
        from sample_agents.core.llm_client import LLMError
        # Use mode to determine workflow
        if request.mode == "quick":
            result = await research_assistant.quick_answer(request.input)
        elif request.mode == "reviewed":
            result = await research_assistant.research_with_review(request.input)
        else:
            result = await research_assistant.research(request.input)

        if not result.success:
            raise HTTPException(status_code=500, detail=result.error)

        return WorkflowResponse(
            response=result.final_response,
            workflow_id=result.workflow_id,
            total_tokens=result.total_tokens,
            total_latency_ms=result.total_latency_ms,
            agent_count=len(result.agent_responses),
            agents=[
                AgentResponseModel(
                    agent_name=r.agent_name,
                    agent_role=r.agent_role,
                    content=r.content,
                    tokens_used=r.tokens_used,
                    latency_ms=r.latency_ms,
                )
                for r in result.agent_responses
            ],
            success=True,
        )

    except LLMError as e:
        raise HTTPException(status_code=502, detail=f"LLM Error: {str(e)}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# === Describe endpoint for introspection ===

@app.post("/describe")
async def describe():
    """Describe this agent's capabilities for auto-discovery."""
    return {
        "name": "Multi-Agent Research Assistant",
        "purpose": (
            "A multi-agent research assistant that uses specialized agents (Planner, "
            "Researcher, Synthesizer) to provide comprehensive answers to research questions. "
            "Supports topics across science, technology, history, policy, and general knowledge."
        ),
        "type": "conversational",
        "domain": "general",
        "capabilities": [
            "multi_turn",
            "research",
            "question_answering",
            "summarization",
        ],
        "mode": "demo" if demo_mode else "live",
    }


# === Alternative input formats for compatibility ===

class MessageRequest(BaseModel):
    """Alternative request format with 'message' field."""
    message: str


class QueryFieldRequest(BaseModel):
    """Alternative request format with 'query' field."""
    query: str


@app.post("/v1/chat", response_model=SimpleResponse)
async def chat_v1_message(request: MessageRequest):
    """Alternative endpoint accepting 'message' field."""
    return await chat(QueryRequest(input=request.message))


@app.post("/query", response_model=SimpleResponse)
async def query_endpoint(request: QueryFieldRequest):
    """Alternative endpoint accepting 'query' field."""
    return await chat(QueryRequest(input=request.query))


# === Run server ===

def main():
    """Run the server."""
    import uvicorn

    port = int(os.environ.get("PORT", 8001))
    host = os.environ.get("HOST", "127.0.0.1")

    print(f"\n🤖 Multi-Agent Research Assistant")
    print(f"   Starting server at http://{host}:{port}")
    print(f"   API docs at http://{host}:{port}/docs")
    print(f"\n   Endpoints:")
    print(f"   POST /chat    - Simple chat (for eval platform)")
    print(f"   POST /research - Full workflow with details")
    print(f"   GET  /health  - Health check\n")

    uvicorn.run(app, host=host, port=port)


if __name__ == "__main__":
    main()
