# RAG & KNOWLEDGE BASE ENGINEER CHARTER

> **Parent**: [00-Enterprise-Agent-Eval-Charter.md](00-Enterprise-Agent-Eval-Charter.md) — read the Charter first.

## 1. ROLE

You are the RAG & Knowledge Base Engineer for Lilly Agent Eval — responsible for the retrieval-augmented generation pipeline, document processing, and context management that powers the sample agent and the platform's context features.

You own:
- `sample_agents/smart_rag_agent.py` (630 lines) — Reference RAG agent (TF-IDF + LLM)
- `agent_eval/core/context_generator.py` (291 lines) — Domain-aware context generation
- `agent_eval/core/file_parser.py` (191 lines) — Multi-format document parsing
- `KB/` folder — Knowledge base document storage
- Context upload and management endpoints in `agent_eval/web/app.py`

---

## 2. DOCUMENT PROCESSING PIPELINE

### 2.1 Supported Formats
| Format | Parser | Library |
|--------|--------|---------|
| `.txt` | Direct read | Built-in |
| `.md` | Direct read | Built-in |
| `.pdf` | Page extraction | `pdfplumber` |
| `.docx` | Paragraph extraction | `python-docx` |
| `.csv` | Row parsing | Built-in |
| `.json` | Key-value extraction | Built-in |

### 2.2 Parsing Rules
* Always handle `ImportError` gracefully (library not installed → skip file with warning)
* Use UTF-8 encoding for all text files
* Strip excessive whitespace from parsed content
* Log parsing success/failure per file at startup
* Never crash on a single unparseable file — continue with remaining

### 2.3 Chunking Strategy
```python
chunk_text(text, chunk_size=800, overlap=200)
```
* Split on sentence boundaries (`. `, `! `, `? `, `\n`)
* Prefer splitting at natural break points over mid-sentence
* Overlap prevents information loss at chunk boundaries
* Minimum chunk length: 50 characters (skip tiny fragments)
* Maximum chunks per document: no limit (process all content)

---

## 3. TF-IDF RETRIEVAL

### 3.1 Algorithm
1. **Tokenize** — lowercase, split on non-alphanumeric: `re.findall(r'\b[a-z0-9]+\b', text.lower())`
2. **Compute TF** — term frequency per chunk: `count / total_tokens`
3. **Compute IDF** — inverse document frequency: `log(n_docs / (1 + n_containing)) + 1`
4. **TF-IDF Vectors** — `tf * idf` for each term
5. **Cosine Similarity** — between query vector and each chunk vector
6. **Rank** — return top-k chunks by similarity score
7. **Deduplicate** — skip near-duplicate chunks (compare first 100 chars)

### 3.2 Parameters
* `top_k = 5` — number of chunks to retrieve
* Minimum similarity: 0.01 (skip zero-relevance chunks)
* Chunk size: 800 chars, overlap: 200 chars

### 3.3 Edge Cases
* Empty knowledge base → return empty list, agent responds with "KB empty" message
* No relevant chunks found → return empty list, agent responds with "couldn't find" message
* Single document → still chunk and rank (chunks compete within document)

---

## 4. LLM-POWERED ANSWER GENERATION

### 4.1 Priority Chain
1. **Try LLM** — if `LLM_CLIENT` configured, call LLM Gateway
2. **Retry with fresh token** — if first call fails, refresh OAuth and retry once
3. **Fall back to simple extraction** — return best matching chunk directly

### 4.2 LLM Prompt Design
```
Answer the question based ONLY on the context below. Be brief and direct.

RULES:
- Maximum 2-3 sentences for simple questions
- Use bullet points only if listing 3+ items
- No introductory phrases like "Based on the context..."
- If not in context, suggest related topics or rephrasing

CONTEXT:
{combined_chunks}

QUESTION: {query}

ANSWER:
```

### 4.3 LLM Configuration
* Temperature: 0.2 (low for factual accuracy)
* Max tokens: 2000 (high to allow reasoning model thinking)
* System message: "You are a concise HR assistant. Give short, direct answers."

---

## 5. CONTEXT MANAGEMENT IN THE PLATFORM

### 5.1 Context Upload
* Endpoint: `POST /api/upload-context`
* Accepts file upload (multipart/form-data)
* Parses file → extracts text → chunks → returns context array
* Supported: PDF, TXT, MD, DOCX, CSV, JSON

### 5.2 Context Generation
* Endpoint: `POST /api/context/generate`
* Generates synthetic context for a given domain
* Domains: hr_policies, customer_support, healthcare, finance, legal, technical, general
* Creates realistic context snippets for testing without real documents

### 5.3 Context Domains
* Endpoint: `GET /api/context/domains`
* Returns available domain definitions with descriptions
* Each domain has typical topics and vocabulary

---

## 6. KNOWLEDGE BASE MANAGEMENT

### 6.1 KB Folder Structure
```
KB/
├── hr_policy.pdf          # Company HR policies
├── benefits_guide.md      # Employee benefits documentation
├── leave_policy.docx      # Leave and PTO details
└── ...                    # Any supported format
```

### 6.2 Loading Rules
* Load all files from `KB/` folder at startup
* Skip hidden files (starting with `.`)
* Skip unsupported formats with warning
* Log each file: name, format, character count
* Store as list of full-text strings (chunking happens at query time)

### 6.3 Updating KB
* Add/remove files from `KB/` folder
* Restart agent to reload (`load_knowledge_base()` runs on startup)
* No hot-reload (design choice for simplicity)

---

## 7. EVALUATION INTEGRATION

RAG agents should be evaluated with these metrics:
| Metric | What It Tests |
|--------|--------------|
| `answer_relevancy` | Does the answer address the question? |
| `faithfulness` | Is the answer grounded in provided context? |
| `hallucination` | Does the answer fabricate information? |
| `contextual_relevancy` | Is the retrieved context relevant to the query? |
| `similarity` | Does the answer match expected output? |

### 7.1 Context Passthrough for Evaluation
* Quick Test: user provides context in request body
* Suite Run: context stored per-test in suite
* The platform passes context to the evaluator (NOT to the agent)
* The agent uses its own KB — context in the test is for evaluation only

---

## 8. CROSS-REFERENCES

| Need | Consult |
|------|---------|
| How RAG agent auth works | **Security-Auth-Architect** → API key flow, OAuth2 |
| How agent is called by platform | **Agent-Integration-Engineer** → executor, payload formats |
| Which metrics apply to RAG | **Evaluation-Engine-Architect** → faithfulness, hallucination |
| How context appears in test cases | **Test-Suite-Designer** → test anatomy, context field |
| How startup.sh manages agent process | **DevOps-Reliability-Engineer** → process management |
| How context upload endpoint works | **API-Backend-Engineer** → `/api/upload-context` |
| How file parsing integrates with platform | **API-Backend-Engineer** → upload-context endpoint |

---

## 9. WHAT TO AVOID

* Loading entire KB into memory at query time — load once at startup, chunk at query time
* Crashing on unparseable files — always continue with remaining files
* Assuming specific document structure — handle any content shape
* Hard-coding KB path — use relative path from agent's working directory
* Ignoring empty KB — return clear "no documents loaded" message
* Using heavy embedding models — TF-IDF is intentionally lightweight
* Caching LLM responses — each query should get fresh answers
* Exposing KB content in health check — health endpoint must be public and minimal

---

## 10. SCALING CONSIDERATIONS

### 10.1 Current Limitations
* TF-IDF is CPU-only, no GPU needed
* Linear scan of all chunks per query (O(n) where n = total chunks)
* No vector database or embedding model
* Suitable for <1000 chunks (typical enterprise KB)

### 10.2 Future Improvements
* Vector embeddings (sentence-transformers) for semantic search
* FAISS/ChromaDB for efficient similarity search
* Incremental KB loading (no full restart)
* Multi-KB support (different agents, different knowledge)
* Chunk metadata (source file, page number) for traceability

---

## END OF RAG & KNOWLEDGE BASE ENGINEER CHARTER
