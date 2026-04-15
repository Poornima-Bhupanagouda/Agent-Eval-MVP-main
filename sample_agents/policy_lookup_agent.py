"""
Policy Lookup Agent - Searches HR knowledge base for relevant policies.

Step 1 in the HR Pipeline Chain:
  Policy Lookup → Summarizer → Compliance

Uses TF-IDF similarity to find the most relevant policy sections
from the KB/ folder. No LLM or API keys required.

Port: 8011
"""

import os
import re
import time
import math
from typing import Optional, List, Dict, Any
from pathlib import Path
from collections import Counter

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

app = FastAPI(title="Policy Lookup Agent")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# KB folder (same as smart_rag_agent)
KB_FOLDER = Path(__file__).parent.parent / "KB"

# Global knowledge base - loaded on startup
KNOWLEDGE_BASE: List[Dict[str, str]] = []


# === Knowledge Base Loading ===

def load_knowledge_base() -> List[Dict[str, str]]:
    """Load and chunk documents from the KB/ folder."""
    chunks = []
    if not KB_FOLDER.exists():
        print(f"[WARN] KB folder not found: {KB_FOLDER}")
        return chunks

    for filepath in KB_FOLDER.iterdir():
        if filepath.suffix.lower() in (".md", ".txt"):
            try:
                text = filepath.read_text(encoding="utf-8")
                file_chunks = chunk_document(text, filepath.name)
                chunks.extend(file_chunks)
                print(f"  Loaded {filepath.name}: {len(file_chunks)} chunks")
            except Exception as e:
                print(f"  [ERROR] Failed to load {filepath.name}: {e}")

    return chunks


def chunk_document(text: str, source: str, chunk_size: int = 500) -> List[Dict[str, str]]:
    """Split document into chunks by sections (## headers) or fixed size."""
    chunks = []
    # Split by markdown headers
    sections = re.split(r'\n(?=##?\s)', text)
    for section in sections:
        section = section.strip()
        if not section:
            continue
        # If section is too long, split further
        if len(section) > chunk_size:
            words = section.split()
            current = []
            current_len = 0
            for word in words:
                current.append(word)
                current_len += len(word) + 1
                if current_len >= chunk_size:
                    chunks.append({"text": " ".join(current), "source": source})
                    current = []
                    current_len = 0
            if current:
                chunks.append({"text": " ".join(current), "source": source})
        else:
            chunks.append({"text": section, "source": source})
    return chunks


# === TF-IDF Search ===

def tokenize(text: str) -> List[str]:
    """Simple tokenizer: lowercase, split on non-alphanumeric."""
    return [w for w in re.findall(r'[a-z0-9]+', text.lower()) if len(w) > 2]


def tfidf_search(query: str, top_k: int = 3) -> List[Dict[str, Any]]:
    """Find the most relevant KB chunks using TF-IDF cosine similarity."""
    if not KNOWLEDGE_BASE:
        return []

    query_tokens = tokenize(query)
    if not query_tokens:
        return []

    # Build document frequency
    doc_freq: Counter = Counter()
    doc_tokens = []
    for chunk in KNOWLEDGE_BASE:
        tokens = tokenize(chunk["text"])
        doc_tokens.append(tokens)
        unique = set(tokens)
        for t in unique:
            doc_freq[t] += 1

    n_docs = len(KNOWLEDGE_BASE)
    scores = []

    for i, tokens in enumerate(doc_tokens):
        if not tokens:
            scores.append(0.0)
            continue

        tf_doc = Counter(tokens)
        tf_query = Counter(query_tokens)

        # Cosine similarity with TF-IDF weighting
        dot_product = 0.0
        norm_doc = 0.0
        norm_query = 0.0

        all_terms = set(query_tokens) | set(tokens)
        for term in all_terms:
            idf = math.log((n_docs + 1) / (doc_freq.get(term, 0) + 1)) + 1
            w_doc = (tf_doc.get(term, 0) / len(tokens)) * idf
            w_query = (tf_query.get(term, 0) / len(query_tokens)) * idf
            dot_product += w_doc * w_query
            norm_doc += w_doc ** 2
            norm_query += w_query ** 2

        if norm_doc > 0 and norm_query > 0:
            scores.append(dot_product / (math.sqrt(norm_doc) * math.sqrt(norm_query)))
        else:
            scores.append(0.0)

    # Get top-k
    ranked = sorted(enumerate(scores), key=lambda x: x[1], reverse=True)[:top_k]
    results = []
    for idx, score in ranked:
        if score > 0:
            results.append({
                "text": KNOWLEDGE_BASE[idx]["text"],
                "source": KNOWLEDGE_BASE[idx]["source"],
                "relevance_score": round(score, 4),
            })
    return results


# === Startup ===

@app.on_event("startup")
def startup():
    global KNOWLEDGE_BASE
    KNOWLEDGE_BASE = load_knowledge_base()
    print(f"[STARTUP] Policy Lookup Agent ready: {len(KNOWLEDGE_BASE)} KB chunks loaded")


# === Models ===

class ChatRequest(BaseModel):
    input: str = Field(..., description="Policy question or topic to search for")


class ChatResponse(BaseModel):
    output: str
    tool_calls: Optional[List[Dict[str, Any]]] = None
    latency_ms: Optional[int] = None
    trace: Optional[List[Dict[str, Any]]] = None
    context: Optional[List[str]] = None


# === Endpoints ===

@app.get("/")
async def root():
    return {
        "name": "Policy Lookup Agent",
        "version": "1.0.0",
        "status": "healthy",
        "description": "Searches HR knowledge base for relevant policy sections",
    }


@app.get("/health")
async def health():
    return {"status": "healthy"}


@app.post("/describe")
async def describe():
    return {
        "name": "Policy Lookup Agent",
        "purpose": "Searches the HR knowledge base (KB/ folder) to find relevant policy sections using TF-IDF similarity search.",
        "type": "rag",
        "domain": "hr_policies",
        "capabilities": ["document_search", "policy_lookup", "question_answering"],
        "tools": [
            {"name": "tfidf_search", "description": "Search KB for relevant policy chunks using TF-IDF similarity"},
        ],
    }


@app.post("/chat", response_model=ChatResponse)
async def chat(request: ChatRequest):
    start = time.time()

    # --- Pipeline node functions ---

    def parse_query_node(state: dict) -> dict:
        """Node 1: Parse and prepare the query."""
        state = dict(state)
        state["intermediate"] = dict(state.get("intermediate", {}))
        state["intermediate"]["original_query"] = state["query"]
        return state

    def search_kb_node(state: dict) -> dict:
        """Node 2: Search knowledge base for relevant policies."""
        state = dict(state)
        state["tool_calls"] = list(state.get("tool_calls", []))
        query = state["query"]
        state["tool_calls"].append({"name": "tfidf_search", "args": {"query": query, "top_k": 3}})

        results = tfidf_search(query, top_k=3)
        state["intermediate"] = dict(state.get("intermediate", {}))
        state["intermediate"]["search_results"] = results
        return state

    def format_output_node(state: dict) -> dict:
        """Node 3: Format search results into readable output."""
        state = dict(state)
        results = state["intermediate"].get("search_results", [])

        if not results:
            state["output"] = "No relevant policies found for your query. Please try rephrasing your question."
            state["metadata"] = dict(state.get("metadata", {}))
            state["metadata"]["context"] = []
            return state

        # Build output with source attribution
        sections = []
        context_list = []
        for i, r in enumerate(results, 1):
            sections.append(f"[Source: {r['source']} | Relevance: {r['relevance_score']}]\n{r['text']}")
            context_list.append(r["text"])

        state["output"] = "\n\n---\n\n".join(sections)
        state["metadata"] = dict(state.get("metadata", {}))
        state["metadata"]["context"] = context_list
        return state

    # --- Run steps sequentially ---
    state = {"query": request.input, "intermediate": {}, "tool_calls": [], "output": "", "errors": [], "metadata": {}}
    state = parse_query_node(state)
    state = search_kb_node(state)
    state = format_output_node(state)
    latency = int((time.time() - start) * 1000)

    return ChatResponse(
        output=state.get("output", ""),
        tool_calls=state.get("tool_calls", []),
        latency_ms=latency,
        context=state.get("metadata", {}).get("context"),
    )


def main():
    import uvicorn
    port = int(os.environ.get("POLICY_LOOKUP_PORT", 8011))
    host = os.environ.get("HOST", "127.0.0.1")
    print(f"\nPolicy Lookup Agent starting at http://{host}:{port}")
    print(f"  API docs: http://{host}:{port}/docs")
    print(f"  KB folder: {KB_FOLDER}\n")
    uvicorn.run(app, host=host, port=port)


if __name__ == "__main__":
    main()
