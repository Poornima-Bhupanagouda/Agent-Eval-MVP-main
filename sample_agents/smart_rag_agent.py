"""
Smart RAG Agent - KB Folder Knowledge Base with LLM Gateway

This agent loads documents from the KB/ folder on startup and uses:
1. TF-IDF similarity to find relevant chunks
2. LLM Gateway (via OAuth2) to generate proper answers from context

Knowledge Base Location: KB/ folder (relative to project root)
Supported formats: PDF, TXT, MD, DOCX

Authentication: API Key required via X-API-Key header
Set RAG_AGENT_API_KEY in .env (auto-generated if missing)

Environment Variables (from .env):
- RAG_AGENT_API_KEY (required for all protected endpoints)
- OAUTH_CLIENT_ID, OAUTH_CLIENT_SECRET, OAUTH_TENANT_ID, OAUTH_SCOPE
- LLM_MODEL_API_KEY, LLM_MODEL_BASE_URL, LLM_MODEL_NAME

Run with: python sample_agents/smart_rag_agent.py
"""

from fastapi import FastAPI, Depends, HTTPException, Security
from fastapi.security import APIKeyHeader
from pydantic import BaseModel
from typing import Optional, List
from pathlib import Path
import re
import os
import requests
from collections import Counter
import math

app = FastAPI(title="HR Policy RAG Agent")

# === API Key Authentication ===
API_KEY_HEADER = APIKeyHeader(name="X-API-Key", auto_error=False)
RAG_AGENT_API_KEY: Optional[str] = None


def load_api_key():
    """Load API key from environment."""
    global RAG_AGENT_API_KEY
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except ImportError:
        pass
    RAG_AGENT_API_KEY = os.environ.get("RAG_AGENT_API_KEY")
    if not RAG_AGENT_API_KEY:
        print("[ERROR] RAG_AGENT_API_KEY not set in .env - agent will reject all requests")
        print("  Add RAG_AGENT_API_KEY=<your-key> to your .env file")
    else:
        print(f"[OK] API Key loaded (starts with {RAG_AGENT_API_KEY[:4]}****)")


async def verify_api_key(api_key: Optional[str] = Security(API_KEY_HEADER)):
    """Dependency that validates the API key on protected endpoints."""
    if not RAG_AGENT_API_KEY:
        raise HTTPException(status_code=503, detail="Agent API key not configured")
    if not api_key:
        raise HTTPException(status_code=401, detail="Missing API key. Provide X-API-Key header.")
    if api_key != RAG_AGENT_API_KEY:
        raise HTTPException(status_code=403, detail="Invalid API key")
    return api_key

@app.on_event("startup")
def startup_load_kb():
    global KNOWLEDGE_BASE
    load_api_key()
    KNOWLEDGE_BASE = load_knowledge_base()
    init_llm_client()
    print(f"[STARTUP] KB loaded: {len(KNOWLEDGE_BASE)} chunks")

# KB folder location (relative to project root)
KB_FOLDER = Path(__file__).parent.parent / "KB"

# Global knowledge base - loaded on startup
KNOWLEDGE_BASE: List[str] = []

# LLM client (initialized if credentials available)
LLM_CLIENT = None
LLM_MODEL_NAME = None
LLM_ACCESS_TOKEN = None
LLM_TOKEN_EXPIRY = 0


class ChatRequest(BaseModel):
    input: str
    context: Optional[List[str]] = None  # Optional external context from evaluator/UI


class ChatResponse(BaseModel):
    output: str


# === Document Parsing ===

def parse_document(file_path: Path) -> Optional[str]:
    """Parse document based on file extension."""
    ext = file_path.suffix.lower()

    try:
        if ext in [".txt", ".md"]:
            return file_path.read_text(encoding="utf-8")

        elif ext == ".pdf":
            try:
                import pdfplumber
                with pdfplumber.open(file_path) as pdf:
                    text = "\n".join(page.extract_text() or "" for page in pdf.pages)
                return text
            except ImportError:
                print(f"  [WARNING] pdfplumber not installed, skipping {file_path.name}")
                print(f"  Install with: pip install pdfplumber")
                return None

        elif ext == ".docx":
            try:
                from docx import Document
                doc = Document(file_path)
                return "\n".join(p.text for p in doc.paragraphs)
            except ImportError:
                print(f"  [WARNING] python-docx not installed, skipping {file_path.name}")
                print(f"  Install with: pip install python-docx")
                return None

        else:
            print(f"  [SKIP] Unsupported format: {file_path.name}")
            return None

    except Exception as e:
        print(f"  [ERROR] Failed to parse {file_path.name}: {e}")
        return None


def load_knowledge_base() -> List[str]:
    """Load all documents from KB folder."""
    documents = []

    if not KB_FOLDER.exists():
        print(f"[WARNING] KB folder not found at: {KB_FOLDER}")
        print(f"[INFO] Create the folder and add documents to enable Q&A")
        return documents

    print(f"\n[INFO] Loading knowledge base from: {KB_FOLDER}")

    for file_path in sorted(KB_FOLDER.iterdir()):
        if file_path.is_file() and not file_path.name.startswith("."):
            content = parse_document(file_path)
            if content:
                documents.append(content)
                print(f"  [OK] {file_path.name} ({len(content)} chars)")

    return documents


# === Text Chunking ===

def chunk_text(text: str, chunk_size: int = 800, overlap: int = 200) -> List[str]:
    """Split text into overlapping chunks for better context retrieval."""
    text = re.sub(r'\s+', ' ', text).strip()

    chunks = []
    start = 0

    while start < len(text):
        end = start + chunk_size

        if end < len(text):
            for sep in ['. ', '! ', '? ', '\n']:
                last_sep = text.rfind(sep, start + chunk_size // 2, end + 50)
                if last_sep != -1:
                    end = last_sep + 1
                    break

        chunk = text[start:end].strip()
        if len(chunk) > 50:
            chunks.append(chunk)

        start = end - overlap

    return chunks


# === TF-IDF Functions ===

def tokenize(text: str) -> List[str]:
    """Simple tokenization - lowercase and split on non-alphanumeric."""
    return re.findall(r'\b[a-z0-9]+\b', text.lower())


def compute_tf(tokens: List[str]) -> dict:
    """Compute term frequency."""
    tf = Counter(tokens)
    total = len(tokens)
    if total == 0:
        return {}
    return {word: count / total for word, count in tf.items()}


def compute_idf(documents: List[List[str]]) -> dict:
    """Compute inverse document frequency."""
    n_docs = len(documents)
    if n_docs == 0:
        return {}

    idf = {}
    all_words = set(word for doc in documents for word in doc)

    for word in all_words:
        n_containing = sum(1 for doc in documents if word in doc)
        idf[word] = math.log(n_docs / (1 + n_containing)) + 1

    return idf


def cosine_similarity(vec1: dict, vec2: dict) -> float:
    """Compute cosine similarity between two TF-IDF vectors."""
    common_words = set(vec1.keys()) & set(vec2.keys())

    if not common_words:
        return 0.0

    dot_product = sum(vec1[w] * vec2[w] for w in common_words)
    norm1 = math.sqrt(sum(v**2 for v in vec1.values()))
    norm2 = math.sqrt(sum(v**2 for v in vec2.values()))

    if norm1 == 0 or norm2 == 0:
        return 0.0

    return dot_product / (norm1 * norm2)


def find_relevant_chunks(query: str, documents: List[str], top_k: int = 5) -> List[str]:
    """Find the most relevant chunks from documents using TF-IDF similarity."""
    if not documents:
        return []

    all_chunks = []
    for doc in documents:
        all_chunks.extend(chunk_text(doc, chunk_size=800, overlap=200))

    if not all_chunks:
        return []

    query_tokens = tokenize(query)
    chunk_tokens = [tokenize(c) for c in all_chunks]

    all_docs = chunk_tokens + [query_tokens]
    idf = compute_idf(all_docs)

    query_tf = compute_tf(query_tokens)
    query_tfidf = {w: tf * idf.get(w, 1) for w, tf in query_tf.items()}

    similarities = []
    for chunk, tokens in zip(all_chunks, chunk_tokens):
        tf = compute_tf(tokens)
        tfidf = {w: tf_val * idf.get(w, 1) for w, tf_val in tf.items()}
        sim = cosine_similarity(query_tfidf, tfidf)
        similarities.append((sim, chunk))

    similarities.sort(reverse=True, key=lambda x: x[0])

    seen = set()
    results = []
    for sim, chunk in similarities:
        if sim < 0.01:
            continue
        chunk_key = chunk[:100]
        if chunk_key not in seen:
            seen.add(chunk_key)
            results.append(chunk)
        if len(results) >= top_k:
            break

    return results


# === LLM Gateway Connection (OAuth2) ===

def get_oauth_token() -> Optional[str]:
    """Get OAuth2 token from Microsoft Azure AD."""
    global LLM_ACCESS_TOKEN, LLM_TOKEN_EXPIRY
    import time

    # Check if existing token is still valid (with 5 min buffer)
    if LLM_ACCESS_TOKEN and time.time() < LLM_TOKEN_EXPIRY - 300:
        return LLM_ACCESS_TOKEN

    client_id = os.environ.get("OAUTH_CLIENT_ID")
    client_secret = os.environ.get("OAUTH_CLIENT_SECRET")
    tenant_id = os.environ.get("OAUTH_TENANT_ID")
    scope = os.environ.get("OAUTH_SCOPE")

    if not all([client_id, client_secret, tenant_id, scope]):
        return None

    token_url = f"https://login.microsoftonline.com/{tenant_id}/oauth2/v2.0/token"
    token_payload = {
        "grant_type": "client_credentials",
        "client_id": client_id,
        "client_secret": client_secret,
        "scope": scope
    }

    try:
        response = requests.post(token_url, data=token_payload, timeout=10)
        response.raise_for_status()
        token_data = response.json()
        LLM_ACCESS_TOKEN = token_data["access_token"]
        # Token typically valid for 1 hour
        LLM_TOKEN_EXPIRY = time.time() + token_data.get("expires_in", 3600)
        return LLM_ACCESS_TOKEN
    except Exception as e:
        print(f"  [ERROR] Failed to get OAuth2 token: {e}")
        return None


def refresh_llm_client():
    """Refresh LLM client with new OAuth token."""
    global LLM_CLIENT

    gateway_key = os.environ.get("LLM_MODEL_API_KEY")
    gateway_url = os.environ.get("LLM_MODEL_BASE_URL")

    if not all([gateway_key, gateway_url]):
        return None

    access_token = get_oauth_token()
    if not access_token:
        return None

    try:
        from openai import OpenAI
        LLM_CLIENT = OpenAI(
            api_key=gateway_key,
            base_url=gateway_url,
            default_headers={
                "Authorization": f"Bearer {access_token}",
                "X-LLM-Gateway-Key": gateway_key,
            }
        )
        return LLM_CLIENT
    except Exception as e:
        print(f"[ERROR] Failed to refresh LLM client: {e}")
        return None


def init_llm_client():
    """Initialize LLM Gateway client with OAuth2 authentication."""
    global LLM_CLIENT, LLM_MODEL_NAME

    # Load environment variables
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except ImportError:
        pass  # dotenv not installed, use existing env vars

    # Get LLM Gateway settings
    gateway_key = os.environ.get("LLM_MODEL_API_KEY")
    gateway_url = os.environ.get("LLM_MODEL_BASE_URL")
    model_name = os.environ.get("LLM_MODEL_NAME")

    if not all([gateway_key, gateway_url, model_name]):
        print("[INFO] LLM Gateway credentials not set - using simple context-based answers")
        print("  Required: LLM_MODEL_API_KEY, LLM_MODEL_BASE_URL, LLM_MODEL_NAME")
        return None

    # Get OAuth2 token
    print("[INFO] Getting OAuth2 token from Microsoft...")
    access_token = get_oauth_token()
    if not access_token:
        print("[WARNING] Failed to get OAuth2 token - using simple answers")
        return None

    print("  [OK] OAuth2 token obtained")

    # Create OpenAI client with LLM Gateway
    try:
        from openai import OpenAI

        LLM_CLIENT = OpenAI(
            api_key=gateway_key,
            base_url=gateway_url,
            default_headers={
                "Authorization": f"Bearer {access_token}",
                "X-LLM-Gateway-Key": gateway_key,
            }
        )
        LLM_MODEL_NAME = model_name

        print(f"  [OK] LLM Gateway client initialized")
        print(f"  Gateway URL: {gateway_url}")
        print(f"  Model: {model_name}")
        return LLM_CLIENT

    except ImportError:
        print("[WARNING] openai package not installed - using simple answers")
        print("  Install with: pip install openai")
        return None
    except Exception as e:
        print(f"[ERROR] Failed to initialize LLM client: {e}")
        return None


def generate_llm_answer(query: str, context_chunks: List[str]) -> Optional[str]:
    """Generate answer using LLM Gateway."""
    global LLM_CLIENT

    if not LLM_MODEL_NAME:
        return None

    # Refresh client if needed (handles token expiry)
    if not LLM_CLIENT:
        refresh_llm_client()

    if not LLM_CLIENT:
        return None

    # Combine context chunks
    context = "\n\n---\n\n".join(context_chunks)

    prompt = f"""Answer the question based ONLY on the context below. Be brief and direct.

RULES:
- Maximum 2-3 sentences for simple questions
- Use bullet points only if listing 3+ items
- No introductory phrases like "Based on the context..."
- If the specific information is not in the context, provide a helpful response about related topics that ARE covered, or suggest how the user might rephrase their question.

CONTEXT:
{context}

QUESTION: {query}

ANSWER:"""

    try:
        response = LLM_CLIENT.chat.completions.create(
            model=LLM_MODEL_NAME,
            messages=[
                {"role": "system", "content": "You are a concise HR assistant. Give short, direct answers. No fluff."},
                {"role": "user", "content": prompt}
            ],
            max_tokens=2000,  # High limit for reasoning models (uses tokens for thinking + output)
            temperature=0.2
        )
        answer = response.choices[0].message.content
        if answer:
            return answer.strip()
        return None
    except Exception as e:
        print(f"[ERROR] LLM generation failed: {e}")
        # Try refreshing the client and retry once
        refresh_llm_client()
        if LLM_CLIENT:
            try:
                response = LLM_CLIENT.chat.completions.create(
                    model=LLM_MODEL_NAME,
                    messages=[
                        {"role": "system", "content": "You are a concise HR assistant. Give short, direct answers."},
                        {"role": "user", "content": prompt}
                    ],
                    max_tokens=2000,
                    temperature=0.2
                )
                return response.choices[0].message.content.strip()
            except Exception as e2:
                print(f"[ERROR] LLM retry failed: {e2}")
        return None


def generate_simple_answer(query: str, context_chunks: List[str]) -> str:
    """Generate a simple answer without LLM (fallback)."""
    if not context_chunks:
        return "I found some related information in the knowledge base, but I couldn't pinpoint an exact answer to your question. Could you try rephrasing or asking about a specific policy area?"

    best_chunk = context_chunks[0]
    best_chunk = re.sub(r'\s+', ' ', best_chunk).strip()

    if len(best_chunk) > 500:
        sentences = re.split(r'(?<=[.!?])\s+', best_chunk)
        result = ""
        for s in sentences:
            if len(result) + len(s) < 500:
                result += s + " "
            else:
                break
        best_chunk = result.strip() or sentences[0]

    return best_chunk


def generate_answer(query: str, context_chunks: List[str]) -> str:
    """Generate an answer from context - uses LLM if available, otherwise simple extraction."""
    if not context_chunks:
        return "I searched the knowledge base but couldn't find specific information on that topic. Try asking about employee benefits, PTO policies, or other HR-related topics covered in our documents."

    # Try LLM-based answer first
    if LLM_CLIENT:
        llm_answer = generate_llm_answer(query, context_chunks)
        if llm_answer:
            return llm_answer

    # Fallback to simple answer
    return generate_simple_answer(query, context_chunks)


# === API Endpoints ===

@app.get("/")
def root():
    """Health check endpoint (no auth required)."""
    return {
        "status": "healthy",
        "agent": "hr-policy-rag",
        "port": 8002,
        "auth": "api_key",
        "kb_documents": len(KNOWLEDGE_BASE),
        "kb_folder": str(KB_FOLDER),
        "llm_enabled": LLM_CLIENT is not None,
        "llm_model": LLM_MODEL_NAME
    }


@app.get("/health")
def health():
    """Dedicated health check endpoint (no auth required)."""
    return {
        "status": "healthy",
        "agent": "hr-policy-rag",
        "port": 8002,
        "kb_documents": len(KNOWLEDGE_BASE),
        "llm_enabled": LLM_CLIENT is not None,
    }


@app.post("/describe")
def describe_agent():
    """Return agent metadata for introspection (no auth required)."""
    return {
        "name": "HR Policy RAG Agent",
        "purpose": "Answer questions about company HR policies using documents from the KB folder. I find relevant information and generate helpful answers.",
        "type": "rag",
        "capabilities": ["context_aware", "document_qa", "retrieval"],
        "domain": "hr_policies",
        "kb_documents": len(KNOWLEDGE_BASE),
        "kb_folder": str(KB_FOLDER),
        "llm_enabled": LLM_CLIENT is not None,
        "llm_model": LLM_MODEL_NAME
    }


def is_discovery_prompt(text: str) -> bool:
    """Check if the input is a discovery/introspection prompt."""
    discovery_keywords = [
        "what is your role",
        "what is your purpose",
        "describe yourself",
        "what are you designed",
        "what can you do",
        "what kind of questions",
        "who are you",
        "what are you"
    ]
    text_lower = text.lower()
    return any(kw in text_lower for kw in discovery_keywords)


@app.post("/chat", dependencies=[Depends(verify_api_key)])
def chat(request: ChatRequest) -> ChatResponse:
    """
    Chat endpoint - answers questions from KB folder knowledge base.

    Uses request context when provided; otherwise falls back to KB folder.
    """
    query = request.input

    # Handle discovery prompts
    if is_discovery_prompt(query):
        llm_status = f"with {LLM_MODEL_NAME} powered answers" if LLM_CLIENT else "with context-based answers"
        return ChatResponse(
            output=f"I am an HR Policy RAG assistant {llm_status}. "
                   f"I answer questions based on {len(KNOWLEDGE_BASE)} document(s) loaded from the KB folder. "
                   f"Ask me questions about company policies, benefits, or procedures."
        )

    # Prefer evaluator-provided context (for uploaded docs), fallback to KB corpus.
    active_corpus = [c for c in (request.context or []) if isinstance(c, str) and c.strip()]
    if not active_corpus:
        active_corpus = KNOWLEDGE_BASE

    # Check if any corpus is available
    if not active_corpus:
        return ChatResponse(
            output=(
                "No context available. Upload context in Agent Eval or add documents to the KB folder "
                "and restart the agent."
            )
        )

    # Find relevant chunks from the selected corpus
    relevant_chunks = find_relevant_chunks(query, active_corpus, top_k=5)

    if not relevant_chunks:
        return ChatResponse(
            output="I searched the knowledge base but couldn't find specific information on that topic. "
                   "Try asking about employee benefits, PTO policies, health insurance, or other HR-related topics covered in our documents."
        )

    # Generate answer from relevant KB content
    answer = generate_answer(query, relevant_chunks)

    return ChatResponse(output=answer)


# === Startup ===

if __name__ == "__main__":
    import uvicorn

    # Load API key
    load_api_key()

    # Load knowledge base from KB folder
    KNOWLEDGE_BASE = load_knowledge_base()

    # Initialize LLM Gateway client
    print("\n[INFO] Initializing LLM Gateway connection...")
    init_llm_client()

    print("\n" + "=" * 60)
    print("HR Policy RAG Agent - KB Folder Knowledge Base")
    print("=" * 60)
    print(f"Auth: API Key (X-API-Key header)")
    print(f"KB Folder: {KB_FOLDER}")
    print(f"Documents loaded: {len(KNOWLEDGE_BASE)}")
    print(f"LLM enabled: {LLM_CLIENT is not None}")
    if LLM_MODEL_NAME:
        print(f"LLM Model: {LLM_MODEL_NAME}")
    print("=" * 60)
    print("\nNOTE: This agent uses uploaded request context when provided.")
    print("If no request context is passed, it falls back to KB folder documents.")
    if not LLM_CLIENT:
        print("\nTIP: Configure .env with LLM Gateway credentials for better answers")
    print("=" * 60 + "\n")

    uvicorn.run(app, host="0.0.0.0", port=8002)
