"""
Summarizer Agent - Condenses policy text into clear summaries.

Step 2 in the HR Pipeline Chain:
  Policy Lookup → Summarizer → Compliance

Takes raw policy text (from Policy Lookup Agent) and produces
a concise, bullet-point summary. No LLM or API keys required -
uses extractive summarization (sentence scoring).

Port: 8012
"""

import os
import re
import time
from typing import Optional, List, Dict, Any

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

app = FastAPI(title="Summarizer Agent")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# === Extractive Summarization ===

def score_sentence(sentence: str, query_words: set) -> float:
    """Score a sentence by importance signals."""
    score = 0.0
    s_lower = sentence.lower()
    words = set(re.findall(r'[a-z0-9]+', s_lower))

    # Query relevance: overlap with original query terms
    if query_words:
        overlap = len(words & query_words)
        score += overlap * 2.0

    # Contains numbers (specific facts are important)
    if re.search(r'\d+', sentence):
        score += 3.0

    # Contains key policy words
    policy_keywords = {
        'must', 'required', 'eligible', 'maximum', 'minimum', 'limit',
        'days', 'weeks', 'months', 'years', 'percent', 'rate', 'paid',
        'coverage', 'benefit', 'policy', 'employee', 'allowed', 'approved',
        'reimbursement', 'insurance', 'leave', 'salary', 'contribution',
    }
    keyword_overlap = len(words & policy_keywords)
    score += keyword_overlap * 1.5

    # Bold/emphasized text (markdown **bold**)
    if '**' in sentence:
        score += 2.0

    # Bullet points / list items
    if sentence.strip().startswith(('-', '*', '•')):
        score += 1.0

    # Penalize very short sentences
    if len(words) < 4:
        score -= 2.0

    # Penalize very long sentences
    if len(words) > 40:
        score -= 1.0

    return score


def extractive_summarize(text: str, max_sentences: int = 8) -> str:
    """Create a summary by extracting the most important sentences."""
    if not text or not text.strip():
        return "No content to summarize."

    # Extract a "query" from any source attribution line
    query_words = set()
    for line in text.split('\n'):
        if not line.startswith('[Source:'):
            words = re.findall(r'[a-z0-9]+', line.lower())
            query_words.update(w for w in words if len(w) > 3)
            if len(query_words) > 10:
                break

    # Split into sentences
    # Handle markdown bullet points as separate "sentences"
    lines = text.split('\n')
    sentences = []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        # Skip source attribution lines
        if line.startswith('[Source:') or line.startswith('---'):
            continue
        # Handle markdown headers
        if line.startswith('#'):
            line = re.sub(r'^#+\s*', '', line)
        sentences.append(line)

    if not sentences:
        return "No content to summarize."

    # Score each sentence
    scored = [(s, score_sentence(s, query_words)) for s in sentences]
    scored.sort(key=lambda x: x[1], reverse=True)

    # Take top sentences, but preserve original order
    top_sentences = scored[:max_sentences]
    top_set = {s for s, _ in top_sentences}

    # Rebuild in original order
    ordered = [s for s in sentences if s in top_set]

    # Format as bullet points
    summary_lines = []
    for s in ordered:
        # Clean up markdown formatting
        s = re.sub(r'\*\*([^*]+)\*\*', r'\1', s)  # Remove bold markers
        s = s.strip('- *•').strip()
        if s:
            summary_lines.append(f"• {s}")

    if not summary_lines:
        return "No key points could be extracted from the provided text."

    return "POLICY SUMMARY\n" + "\n".join(summary_lines)


# === Models ===

class ChatRequest(BaseModel):
    input: str = Field(..., description="Policy text to summarize")


class ChatResponse(BaseModel):
    output: str
    tool_calls: Optional[List[Dict[str, Any]]] = None
    latency_ms: Optional[int] = None
    trace: Optional[List[Dict[str, Any]]] = None


# === Endpoints ===

@app.get("/")
async def root():
    return {
        "name": "Summarizer Agent",
        "version": "1.0.0",
        "status": "healthy",
        "description": "Condenses policy text into clear bullet-point summaries",
    }


@app.get("/health")
async def health():
    return {"status": "healthy"}


@app.post("/describe")
async def describe():
    return {
        "name": "Summarizer Agent",
        "purpose": "Takes raw policy text and produces a concise bullet-point summary highlighting key facts, numbers, and requirements.",
        "type": "simple",
        "domain": "hr_policies",
        "capabilities": ["text_summarization", "extractive_summary"],
        "tools": [
            {"name": "extractive_summarize", "description": "Score sentences by importance and extract top points"},
        ],
    }


@app.post("/chat", response_model=ChatResponse)
async def chat(request: ChatRequest):
    start = time.time()

    # --- Pipeline node functions ---

    def analyze_input_node(state: dict) -> dict:
        """Node 1: Analyze input text structure."""
        state = dict(state)
        state["intermediate"] = dict(state.get("intermediate", {}))
        text = state["query"]
        state["intermediate"]["input_length"] = len(text)
        state["intermediate"]["has_sections"] = '---' in text or '##' in text
        return state

    def summarize_node(state: dict) -> dict:
        """Node 2: Run extractive summarization."""
        state = dict(state)
        state["tool_calls"] = list(state.get("tool_calls", []))
        text = state["query"]

        state["tool_calls"].append({
            "name": "extractive_summarize",
            "args": {"text_length": len(text), "max_sentences": 8},
        })

        summary = extractive_summarize(text, max_sentences=8)
        state["intermediate"] = dict(state.get("intermediate", {}))
        state["intermediate"]["summary"] = summary
        return state

    def format_node(state: dict) -> dict:
        """Node 3: Format final output."""
        state = dict(state)
        summary = state["intermediate"].get("summary", "")
        input_len = state["intermediate"].get("input_length", 0)
        summary_len = len(summary)

        compression = round((1 - summary_len / max(input_len, 1)) * 100)
        state["output"] = f"{summary}\n\n[Compressed {input_len} chars → {summary_len} chars ({compression}% reduction)]"
        return state

    # --- Run steps sequentially ---
    state = {"query": request.input, "intermediate": {}, "tool_calls": [], "output": "", "errors": []}
    state = analyze_input_node(state)
    state = summarize_node(state)
    state = format_node(state)
    latency = int((time.time() - start) * 1000)

    return ChatResponse(
        output=state.get("output", ""),
        tool_calls=state.get("tool_calls", []),
        latency_ms=latency,
    )


def main():
    import uvicorn
    port = int(os.environ.get("SUMMARIZER_PORT", 8012))
    host = os.environ.get("HOST", "127.0.0.1")
    print(f"\nSummarizer Agent starting at http://{host}:{port}")
    print(f"  API docs: http://{host}:{port}/docs\n")
    uvicorn.run(app, host=host, port=port)


if __name__ == "__main__":
    main()
