"""
LLM Client for making real API calls.

Supports:
- OpenAI API
- Azure OpenAI
- LLM Gateway with OAuth2 authentication
- Any OpenAI-compatible API
"""

import os
import time
import asyncio
from typing import List, Dict, Any, Optional
from dataclasses import dataclass
import httpx


@dataclass
class LLMResponse:
    """Response from LLM API."""
    content: str
    tokens_used: int
    latency_ms: int
    model: str
    raw_response: Optional[Dict[str, Any]] = None


class LLMClient:
    """
    Unified LLM client supporting multiple providers including OAuth2-based LLM Gateway.

    Configuration via environment variables:

    For LLM Gateway with OAuth2:
    - LLM_MODEL_BASE_URL: LLM Gateway base URL
    - LLM_MODEL_API_KEY: LLM Gateway API key
    - LLM_MODEL_NAME: Model name to use
    - OAUTH_CLIENT_ID: OAuth2 client ID
    - OAUTH_CLIENT_SECRET: OAuth2 client secret
    - OAUTH_TENANT_ID: Azure AD tenant ID
    - OAUTH_SCOPE: OAuth2 scope

    For direct OpenAI:
    - OPENAI_API_KEY: OpenAI API key
    - OPENAI_MODEL: Model to use (default: gpt-4o-mini)

    For Azure OpenAI:
    - AZURE_OPENAI_ENDPOINT: Azure OpenAI endpoint
    - AZURE_OPENAI_KEY: Azure OpenAI key
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        api_base: Optional[str] = None,
        model: Optional[str] = None,
        timeout: float = 60.0,
    ):
        """Initialize the LLM client with automatic provider detection."""
        self.timeout = timeout
        self._oauth_token: Optional[str] = None
        self._oauth_token_expiry: float = 0

        # Check for LLM Gateway with OAuth2 (priority)
        self.oauth_client_id = os.environ.get("OAUTH_CLIENT_ID")
        self.oauth_client_secret = os.environ.get("OAUTH_CLIENT_SECRET")
        self.oauth_tenant_id = os.environ.get("OAUTH_TENANT_ID")
        self.oauth_scope = os.environ.get("OAUTH_SCOPE")

        # LLM Gateway config
        self.llm_gateway_key = os.environ.get("LLM_MODEL_API_KEY")
        self.llm_gateway_url = os.environ.get("LLM_MODEL_BASE_URL")
        self.llm_model_name = os.environ.get("LLM_MODEL_NAME")

        # Determine which auth method to use
        self.use_oauth = all([
            self.oauth_client_id,
            self.oauth_client_secret,
            self.oauth_tenant_id,
            self.oauth_scope,
            self.llm_gateway_key,
            self.llm_gateway_url,
        ])

        if self.use_oauth:
            # Use LLM Gateway with OAuth2
            self.api_base = api_base or self.llm_gateway_url
            self.api_key = api_key or self.llm_gateway_key
            self.model = model or self.llm_model_name or "gpt-4o-mini"
        else:
            # Fallback to standard OpenAI/Azure config
            self.api_key = (
                api_key
                or os.environ.get("OPENAI_API_KEY")
                or os.environ.get("AZURE_OPENAI_KEY")
                or os.environ.get("LLM_MODEL_API_KEY")
            )

            self.api_base = (
                api_base
                or os.environ.get("LLM_MODEL_BASE_URL")
                or os.environ.get("LLM_GATEWAY_URL")
                or os.environ.get("OPENAI_API_BASE")
                or os.environ.get("AZURE_OPENAI_ENDPOINT")
                or "https://api.openai.com/v1"
            )

            self.model = (
                model
                or os.environ.get("LLM_MODEL_NAME")
                or os.environ.get("OPENAI_MODEL")
                or "gpt-4o-mini"
            )

        # Normalize API base URL
        if self.api_base:
            self.api_base = self.api_base.rstrip("/")
            # Don't auto-append /v1 for LLM Gateway - it may have its own path structure
            if not self.use_oauth and "openai.com" not in self.api_base:
                if not self.api_base.endswith("/v1") and "/v1" not in self.api_base:
                    self.api_base = f"{self.api_base}/v1"

        if not self.api_key:
            raise ValueError(
                "No API key found. Set one of: LLM_MODEL_API_KEY, OPENAI_API_KEY, or AZURE_OPENAI_KEY"
            )

        if not self.api_base:
            raise ValueError(
                "No API base URL found. Set one of: LLM_MODEL_BASE_URL, OPENAI_API_BASE, or AZURE_OPENAI_ENDPOINT"
            )

    async def _get_oauth_token(self) -> str:
        """Get OAuth2 access token from Microsoft Azure AD."""
        # Check if we have a valid cached token
        if self._oauth_token and time.time() < self._oauth_token_expiry - 60:
            return self._oauth_token

        token_url = f"https://login.microsoftonline.com/{self.oauth_tenant_id}/oauth2/v2.0/token"
        token_payload = {
            "grant_type": "client_credentials",
            "client_id": self.oauth_client_id,
            "client_secret": self.oauth_client_secret,
            "scope": self.oauth_scope,
        }

        async with httpx.AsyncClient(timeout=30.0) as client:
            try:
                response = await client.post(token_url, data=token_payload)
                response.raise_for_status()
                data = response.json()

                self._oauth_token = data["access_token"]
                # Token usually expires in 3600 seconds (1 hour)
                expires_in = data.get("expires_in", 3600)
                self._oauth_token_expiry = time.time() + expires_in

                return self._oauth_token

            except httpx.HTTPStatusError as e:
                raise LLMError(f"OAuth2 token request failed: {e.response.status_code} - {e.response.text}")
            except Exception as e:
                raise LLMError(f"Failed to get OAuth2 token: {str(e)}")

    async def _get_headers(self) -> Dict[str, str]:
        """Get the appropriate headers for the API call."""
        headers = {
            "Content-Type": "application/json",
        }

        if self.use_oauth:
            # LLM Gateway with OAuth2
            oauth_token = await self._get_oauth_token()
            headers["Authorization"] = f"Bearer {oauth_token}"
            headers["X-LLM-Gateway-Key"] = self.api_key
        elif "azure" in self.api_base.lower():
            # Azure OpenAI
            headers["api-key"] = self.api_key
        else:
            # Standard OpenAI
            headers["Authorization"] = f"Bearer {self.api_key}"

        return headers

    async def chat(
        self,
        messages: List[Dict[str, str]],
        temperature: float = 0.7,
        max_tokens: int = 2000,
        json_mode: bool = False,
    ) -> LLMResponse:
        """
        Send a chat completion request.

        Args:
            messages: List of message dicts with 'role' and 'content'
            temperature: Sampling temperature
            max_tokens: Maximum tokens in response
            json_mode: Whether to request JSON output

        Returns:
            LLMResponse with content and metadata
        """
        start_time = time.time()

        headers = await self._get_headers()

        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }

        if json_mode:
            payload["response_format"] = {"type": "json_object"}

        # Build endpoint URL
        endpoint = f"{self.api_base}/chat/completions"

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            try:
                response = await client.post(endpoint, headers=headers, json=payload)
                response.raise_for_status()
                data = response.json()

                latency_ms = int((time.time() - start_time) * 1000)

                content = data["choices"][0]["message"]["content"]
                tokens_used = data.get("usage", {}).get("total_tokens", 0)

                return LLMResponse(
                    content=content,
                    tokens_used=tokens_used,
                    latency_ms=latency_ms,
                    model=self.model,
                    raw_response=data,
                )

            except httpx.HTTPStatusError as e:
                latency_ms = int((time.time() - start_time) * 1000)
                error_detail = e.response.text if e.response else str(e)
                raise LLMError(f"API error: {e.response.status_code} - {error_detail}")
            except httpx.RequestError as e:
                raise LLMError(f"Request failed: {str(e)}")

    async def chat_with_retry(
        self,
        messages: List[Dict[str, str]],
        retries: int = 3,
        **kwargs
    ) -> LLMResponse:
        """Chat with automatic retry on failure."""
        last_error = None

        for attempt in range(retries):
            try:
                return await self.chat(messages, **kwargs)
            except LLMError as e:
                last_error = e
                if attempt < retries - 1:
                    await self._backoff(attempt)

        raise last_error

    async def _backoff(self, attempt: int):
        """Exponential backoff between retries."""
        wait_time = (2 ** attempt) + (time.time() % 1)  # Add jitter
        await asyncio.sleep(wait_time)

    def format_system_prompt(self, prompt: str) -> Dict[str, str]:
        """Format a system prompt message."""
        return {"role": "system", "content": prompt}

    def format_user_prompt(self, prompt: str) -> Dict[str, str]:
        """Format a user prompt message."""
        return {"role": "user", "content": prompt}

    def format_assistant_response(self, response: str) -> Dict[str, str]:
        """Format an assistant response message."""
        return {"role": "assistant", "content": response}

    def get_config_info(self) -> Dict[str, Any]:
        """Get configuration info for debugging."""
        return {
            "api_base": self.api_base,
            "model": self.model,
            "use_oauth": self.use_oauth,
            "has_api_key": bool(self.api_key),
            "has_oauth_config": all([
                self.oauth_client_id,
                self.oauth_client_secret,
                self.oauth_tenant_id,
                self.oauth_scope,
            ]) if self.use_oauth else False,
        }


class LLMError(Exception):
    """Error from LLM API."""
    pass
