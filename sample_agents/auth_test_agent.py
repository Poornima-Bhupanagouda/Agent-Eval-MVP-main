"""
Sample agent with authentication for testing Lilly Agent Eval auth features.

Run with: python sample_agents/auth_test_agent.py

Test endpoints:
- /chat/no-auth     - No authentication required
- /chat/bearer      - Requires Bearer token: test-bearer-token-67890
- /chat/api-key     - Requires header X-API-Key: test-api-key-12345
- /chat/basic       - Requires Basic auth: testuser / testpass
- /chat/custom      - Requires header X-Custom-Auth: custom-secret
"""

from fastapi import FastAPI, HTTPException, Header, Depends
from fastapi.security import HTTPBasic, HTTPBasicCredentials, HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel
from typing import Optional
import secrets

app = FastAPI(title="Auth Test Agent")
security_basic = HTTPBasic(auto_error=False)
security_bearer = HTTPBearer(auto_error=False)

# Test credentials
TEST_API_KEY = "test-api-key-12345"
TEST_BEARER_TOKEN = "test-bearer-token-67890"
TEST_USERNAME = "testuser"
TEST_PASSWORD = "testpass"
TEST_CUSTOM_SECRET = "custom-secret"


class ChatRequest(BaseModel):
    input: str


class ChatResponse(BaseModel):
    output: str
    auth_method: str


@app.get("/")
def root():
    """Health check endpoint."""
    return {"status": "healthy", "agent": "auth-test", "port": 8002}


@app.post("/chat/no-auth")
def chat_no_auth(request: ChatRequest):
    """Endpoint with no authentication required."""
    return ChatResponse(
        output=f"[No Auth] You said: {request.input}",
        auth_method="none"
    )


@app.post("/chat/bearer")
def chat_bearer(
    request: ChatRequest,
    credentials: HTTPAuthorizationCredentials = Depends(security_bearer)
):
    """Endpoint requiring Bearer token authentication."""
    if not credentials:
        raise HTTPException(
            status_code=401,
            detail="Missing bearer token. Use: Authorization: Bearer test-bearer-token-67890"
        )

    if credentials.credentials != TEST_BEARER_TOKEN:
        raise HTTPException(
            status_code=401,
            detail=f"Invalid bearer token. Expected: {TEST_BEARER_TOKEN}"
        )

    return ChatResponse(
        output=f"[Bearer Auth] You said: {request.input}",
        auth_method="bearer_token"
    )


@app.post("/chat/api-key")
def chat_api_key(
    request: ChatRequest,
    x_api_key: Optional[str] = Header(None, alias="X-API-Key")
):
    """Endpoint requiring API key header authentication."""
    if not x_api_key:
        raise HTTPException(
            status_code=401,
            detail="Missing API key. Use header: X-API-Key: test-api-key-12345"
        )

    if x_api_key != TEST_API_KEY:
        raise HTTPException(
            status_code=401,
            detail=f"Invalid API key. Expected: {TEST_API_KEY}"
        )

    return ChatResponse(
        output=f"[API Key Auth] You said: {request.input}",
        auth_method="api_key"
    )


@app.post("/chat/basic")
def chat_basic(
    request: ChatRequest,
    credentials: HTTPBasicCredentials = Depends(security_basic)
):
    """Endpoint requiring Basic authentication."""
    if not credentials:
        raise HTTPException(
            status_code=401,
            detail="Missing basic auth credentials. Use: testuser / testpass"
        )

    correct_username = secrets.compare_digest(credentials.username, TEST_USERNAME)
    correct_password = secrets.compare_digest(credentials.password, TEST_PASSWORD)

    if not (correct_username and correct_password):
        raise HTTPException(
            status_code=401,
            detail=f"Invalid credentials. Use username: {TEST_USERNAME}, password: {TEST_PASSWORD}"
        )

    return ChatResponse(
        output=f"[Basic Auth] You said: {request.input}",
        auth_method="basic_auth"
    )


@app.post("/chat/custom")
def chat_custom_header(
    request: ChatRequest,
    x_custom_auth: Optional[str] = Header(None, alias="X-Custom-Auth")
):
    """Endpoint requiring custom header authentication."""
    if not x_custom_auth:
        raise HTTPException(
            status_code=401,
            detail="Missing custom header. Use: X-Custom-Auth: custom-secret"
        )

    if x_custom_auth != TEST_CUSTOM_SECRET:
        raise HTTPException(
            status_code=401,
            detail=f"Invalid custom header value. Expected: {TEST_CUSTOM_SECRET}"
        )

    return ChatResponse(
        output=f"[Custom Header Auth] You said: {request.input}",
        auth_method="custom_headers"
    )


if __name__ == "__main__":
    import uvicorn
    print("\n" + "="*60)
    print("Auth Test Agent - Test Credentials")
    print("="*60)
    print(f"Bearer Token:  {TEST_BEARER_TOKEN}")
    print(f"API Key:       X-API-Key: {TEST_API_KEY}")
    print(f"Basic Auth:    {TEST_USERNAME} / {TEST_PASSWORD}")
    print(f"Custom Header: X-Custom-Auth: {TEST_CUSTOM_SECRET}")
    print("="*60 + "\n")

    uvicorn.run(app, host="0.0.0.0", port=8002)
