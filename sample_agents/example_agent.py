"""
Example: A minimal working agent with FastAPI.

Run:  python -m sample_agents.example_agent
Test: curl -X POST http://localhost:8020/chat -H "Content-Type: application/json" -d '{"input": "Hello"}'
"""
import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any

app = FastAPI(title="Greeting Agent", description="A friendly agent that greets users", version="1.0.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])


class ChatRequest(BaseModel):
    input: str = Field(..., description="User input")


class ChatResponse(BaseModel):
    output: str


@app.get("/")
async def root():
    return {"name": "Greeting Agent", "version": "1.0.0", "status": "healthy"}


@app.get("/health")
async def health():
    return {"status": "healthy"}


@app.post("/chat", response_model=ChatResponse)
async def chat(request: ChatRequest):
    query = request.input.lower()
    if "name" in query:
        output = "I'm the Greeting Agent! Nice to meet you."
    else:
        output = f"Hello! You said: {request.input}. How can I help?"
    return ChatResponse(output=output)


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8020)
