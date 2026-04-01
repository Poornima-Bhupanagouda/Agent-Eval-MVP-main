"""
HTTP executor for Lilly Agent Eval.

Simple async HTTP client with automatic format detection.
"""

import httpx
import time
import asyncio
from dataclasses import dataclass
from typing import Optional, List, Dict, Any
import logging

logger = logging.getLogger(__name__)


@dataclass
class ExecutionResult:
    """Result of executing an agent call."""
    output: str
    latency_ms: int
    status_code: Optional[int] = None
    tokens: Optional[int] = None
    error: Optional[str] = None
    raw_response: Optional[dict] = None
    tool_calls: Optional[List[Dict]] = None  # Extracted tool/function calls


class Executor:
    """
    Simple HTTP executor with automatic format detection.

    Tries multiple common request formats to communicate with various agent APIs:
    - Simple JSON formats: {"input": "..."}, {"message": "..."}, {"query": "..."}
    - OpenAI-compatible: {"messages": [{"role": "user", "content": "..."}]}
    """

    def __init__(self, timeout: float = 30.0):
        """
        Initialize executor.

        Args:
            timeout: HTTP timeout in seconds
        """
        self.timeout = timeout

    async def execute(
        self,
        endpoint: str,
        input_text: str,
        headers: Optional[Dict[str, str]] = None,
        context: Optional[List[str]] = None,
    ) -> ExecutionResult:
        """
        Execute an agent call with automatic format detection.

        Args:
            endpoint: The agent's HTTP endpoint URL
            input_text: The input text to send
            headers: Optional HTTP headers
            context: Optional context for RAG agents

        Returns:
            ExecutionResult with output and metadata
        """
        start = time.time()

        # Default headers
        request_headers = {"Content-Type": "application/json"}
        if headers:
            request_headers.update(headers)

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            # Try different payload formats
            for payload in self._get_payloads(input_text, context):
                try:
                    response = await client.post(
                        endpoint,
                        json=payload,
                        headers=request_headers,
                    )

                    latency_ms = int((time.time() - start) * 1000)

                    if response.status_code == 200:
                        try:
                            data = response.json()
                            output = self._extract_output(data)
                            tool_calls = self._extract_tool_calls(data)
                            return ExecutionResult(
                                output=output,
                                latency_ms=latency_ms,
                                status_code=response.status_code,
                                raw_response=data,
                                tool_calls=tool_calls,
                            )
                        except Exception as e:
                            # Response not JSON, try text
                            return ExecutionResult(
                                output=response.text,
                                latency_ms=latency_ms,
                                status_code=response.status_code,
                            )
                    elif response.status_code == 422:
                        # Validation error - try next format
                        continue
                    elif 300 <= response.status_code < 400:
                        location = response.headers.get("location")
                        redirect_hint = f" Redirects to: {location}" if location else ""
                        return ExecutionResult(
                            output="",
                            latency_ms=latency_ms,
                            status_code=response.status_code,
                            error=(
                                f"HTTP {response.status_code}: endpoint redirected instead of returning an answer."
                                f" This usually means login/auth is required or the URL is not the API endpoint.{redirect_hint}"
                            ),
                        )
                    else:
                        # Non-retriable error
                        return ExecutionResult(
                            output="",
                            latency_ms=latency_ms,
                            status_code=response.status_code,
                            error=f"HTTP {response.status_code}: {response.text[:200]}",
                        )

                except httpx.TimeoutException:
                    return ExecutionResult(
                        output="",
                        latency_ms=int((time.time() - start) * 1000),
                        error=f"Request timed out after {self.timeout}s",
                    )
                except httpx.ConnectError:
                    return ExecutionResult(
                        output="",
                        latency_ms=int((time.time() - start) * 1000),
                        error=f"Failed to connect to {endpoint}",
                    )
                except Exception as e:
                    logger.debug(f"Request failed with payload {payload}: {e}")
                    continue

        # All formats failed
        return ExecutionResult(
            output="",
            latency_ms=int((time.time() - start) * 1000),
            error="Failed to communicate with agent. Tried multiple request formats.",
        )

    def _get_payloads(self, input_text: str, context: Optional[List[str]] = None) -> List[dict]:
        """
        Generate common payload formats to try.

        Order matters - most common formats first.
        """
        # If context is provided, include it in payloads for RAG agents
        if context:
            return [
                # RAG-aware formats (with context)
                {"input": input_text, "context": context},
                {"message": input_text, "context": context},
                {"query": input_text, "context": context},
                {"query": input_text, "documents": context},
                {"question": input_text, "context": context},

                # Simple formats (fallback without context)
                {"input": input_text},
                {"message": input_text},
                {"query": input_text},
            ]

        return [
            # Simple formats (most common for custom agents)
            {"input": input_text},
            {"message": input_text},
            {"query": input_text},
            {"text": input_text},
            {"prompt": input_text},

            # OpenAI-compatible format
            {"messages": [{"role": "user", "content": input_text}]},

            # Anthropic-compatible format
            {"messages": [{"role": "user", "content": input_text}], "max_tokens": 1024},

            # Nested formats
            {"data": {"input": input_text}},
            {"request": {"message": input_text}},
        ]

    def _extract_output(self, data: Any) -> str:
        """
        Extract output text from various response formats.

        Handles:
        - Simple: {"output": "..."}, {"response": "..."}, etc.
        - OpenAI: {"choices": [{"message": {"content": "..."}}]}
        - Nested: {"data": {"output": "..."}}
        """
        if isinstance(data, str):
            return data

        if not isinstance(data, dict):
            return str(data)

        # Try common output keys
        for key in ["output", "response", "message", "content", "text", "answer", "result"]:
            if key in data:
                value = data[key]
                if isinstance(value, str):
                    return value
                if isinstance(value, dict):
                    # Nested response
                    return self._extract_output(value)

        # OpenAI format
        if "choices" in data and isinstance(data["choices"], list) and len(data["choices"]) > 0:
            choice = data["choices"][0]
            if isinstance(choice, dict):
                if "message" in choice and "content" in choice["message"]:
                    return choice["message"]["content"]
                if "text" in choice:
                    return choice["text"]

        # Nested data
        if "data" in data:
            return self._extract_output(data["data"])

        # Fallback: return entire response as string
        return str(data)

    def _extract_tool_calls(self, data: Any) -> Optional[List[Dict]]:
        """
        Extract tool/function calls from agent response.

        Handles:
        - OpenAI: {"choices": [{"message": {"tool_calls": [...]}}]}
        - Generic: {"tool_calls": [...]}, {"actions": [...]}, {"function_calls": [...]}
        - LangChain: {"intermediate_steps": [{"tool": "...", "tool_input": {...}}]}
        """
        if not isinstance(data, dict):
            return None

        tool_calls = []

        # OpenAI format
        if "choices" in data and isinstance(data["choices"], list):
            for choice in data["choices"]:
                if isinstance(choice, dict) and "message" in choice:
                    msg = choice["message"]
                    if isinstance(msg, dict) and "tool_calls" in msg:
                        for tc in msg["tool_calls"]:
                            if isinstance(tc, dict):
                                fn = tc.get("function", {})
                                tool_calls.append({
                                    "name": fn.get("name", tc.get("name", "unknown")),
                                    "args": fn.get("arguments", tc.get("args", {})),
                                })

        # Direct tool_calls key
        for key in ["tool_calls", "actions", "function_calls", "tools_used"]:
            if key in data and isinstance(data[key], list):
                for tc in data[key]:
                    if isinstance(tc, dict):
                        tool_calls.append({
                            "name": tc.get("name", tc.get("tool", tc.get("function", "unknown"))),
                            "args": tc.get("args", tc.get("arguments", tc.get("tool_input", tc.get("input", {})))),
                        })

        # LangChain intermediate_steps format
        if "intermediate_steps" in data and isinstance(data["intermediate_steps"], list):
            for step in data["intermediate_steps"]:
                if isinstance(step, dict) and "tool" in step:
                    tool_calls.append({
                        "name": step["tool"],
                        "args": step.get("tool_input", {}),
                    })
                elif isinstance(step, (list, tuple)) and len(step) >= 1:
                    action = step[0]
                    if isinstance(action, dict) and "tool" in action:
                        tool_calls.append({
                            "name": action["tool"],
                            "args": action.get("tool_input", {}),
                        })

        # Nested in data key
        if not tool_calls and "data" in data and isinstance(data["data"], dict):
            nested = self._extract_tool_calls(data["data"])
            if nested:
                tool_calls = nested

        return tool_calls if tool_calls else None

    async def execute_conversation(
        self,
        endpoint: str,
        turns: List[Dict],
        headers: Optional[Dict[str, str]] = None,
        context: Optional[List[str]] = None,
    ) -> List[ExecutionResult]:
        """
        Execute a multi-turn conversation, maintaining history across turns.

        Args:
            endpoint: The agent's HTTP endpoint URL
            turns: List of {"role": "user", "content": "..."} dicts
            headers: Optional HTTP headers
            context: Optional shared context for RAG agents

        Returns:
            List of ExecutionResult, one per user turn
        """
        request_headers = {"Content-Type": "application/json"}
        if headers:
            request_headers.update(headers)

        conversation_history = []
        results = []

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            for turn in turns:
                if turn.get("role") != "user":
                    # Add expected assistant responses to history for context
                    conversation_history.append({
                        "role": "assistant",
                        "content": turn.get("content", ""),
                    })
                    continue

                user_content = turn["content"]
                conversation_history.append({"role": "user", "content": user_content})

                start = time.time()

                # Try conversation-aware payload formats
                payloads = self._get_conversation_payloads(
                    user_content, conversation_history, context
                )

                result = None
                for payload in payloads:
                    try:
                        response = await client.post(
                            endpoint, json=payload, headers=request_headers
                        )
                        latency_ms = int((time.time() - start) * 1000)

                        if response.status_code == 200:
                            try:
                                data = response.json()
                                output = self._extract_output(data)
                                tool_calls = self._extract_tool_calls(data)
                                result = ExecutionResult(
                                    output=output,
                                    latency_ms=latency_ms,
                                    status_code=response.status_code,
                                    raw_response=data,
                                    tool_calls=tool_calls,
                                )
                            except Exception:
                                result = ExecutionResult(
                                    output=response.text,
                                    latency_ms=latency_ms,
                                    status_code=response.status_code,
                                )
                            break
                        elif response.status_code == 422:
                            continue
                        else:
                            result = ExecutionResult(
                                output="",
                                latency_ms=latency_ms,
                                status_code=response.status_code,
                                error=f"HTTP {response.status_code}: {response.text[:200]}",
                            )
                            break
                    except httpx.TimeoutException:
                        result = ExecutionResult(
                            output="",
                            latency_ms=int((time.time() - start) * 1000),
                            error=f"Request timed out after {self.timeout}s",
                        )
                        break
                    except httpx.ConnectError:
                        result = ExecutionResult(
                            output="",
                            latency_ms=int((time.time() - start) * 1000),
                            error=f"Failed to connect to {endpoint}",
                        )
                        break
                    except Exception as e:
                        logger.debug(f"Conversation request failed: {e}")
                        continue

                if result is None:
                    result = ExecutionResult(
                        output="",
                        latency_ms=int((time.time() - start) * 1000),
                        error="Failed to communicate with agent for conversation turn.",
                    )

                results.append(result)

                # Add assistant response to history for next turn
                if result.output:
                    conversation_history.append({
                        "role": "assistant",
                        "content": result.output,
                    })

        return results

    def _get_conversation_payloads(
        self,
        current_input: str,
        history: List[Dict],
        context: Optional[List[str]] = None,
    ) -> List[dict]:
        """Generate conversation-aware payload formats."""
        payloads = [
            # OpenAI-compatible (most common for conversational agents)
            {"messages": history},
            # OpenAI with context
            *([{"messages": history, "context": context}] if context else []),
            # Generic with history
            {"input": current_input, "history": history},
            {"message": current_input, "conversation_history": history},
            {"query": current_input, "messages": history},
            # With context
            *([{"input": current_input, "history": history, "context": context}] if context else []),
            # Simple fallback (no history)
            {"input": current_input},
            {"message": current_input},
        ]
        return payloads

    async def test_connection(self, endpoint: str, headers: Optional[Dict[str, str]] = None) -> dict:
        """
        Test if an endpoint is reachable.

        Args:
            endpoint: The URL to test
            headers: Optional HTTP headers (for auth)

        Returns:
            Dict with 'success', 'latency_ms', and optional 'error'
        """
        start = time.time()
        request_headers = {}
        if headers:
            request_headers.update(headers)

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                # Try GET first, fall back to POST if 405 (Method Not Allowed)
                response = await client.get(endpoint, headers=request_headers)

                if response.status_code == 405:
                    # Endpoint only accepts POST - try with a minimal payload
                    post_headers = {**request_headers, "Content-Type": "application/json"}
                    response = await client.post(
                        endpoint, headers=post_headers,
                        json={"input": "test", "message": "test"}
                    )

                latency_ms = int((time.time() - start) * 1000)

                if 200 <= response.status_code < 300:
                    return {
                        "success": True,
                        "latency_ms": latency_ms,
                        "status_code": response.status_code,
                    }
                elif 300 <= response.status_code < 400:
                    location = response.headers.get("location")
                    redirect_hint = f" Redirects to: {location}" if location else ""
                    return {
                        "success": False,
                        "latency_ms": latency_ms,
                        "status_code": response.status_code,
                        "error": (
                            f"Redirect ({response.status_code}). This usually means auth/login is required "
                            f"or the endpoint is a UI URL, not the chat API.{redirect_hint}"
                        ),
                    }
                elif 400 <= response.status_code < 500:
                    return {
                        "success": False,
                        "latency_ms": latency_ms,
                        "status_code": response.status_code,
                        "error": f"Client error: HTTP {response.status_code}. Check auth headers and endpoint path.",
                    }
                else:
                    return {
                        "success": False,
                        "latency_ms": latency_ms,
                        "error": f"Server error: {response.status_code}",
                    }
        except httpx.ConnectError:
            return {
                "success": False,
                "latency_ms": int((time.time() - start) * 1000),
                "error": "Connection failed",
            }
        except Exception as e:
            return {
                "success": False,
                "latency_ms": int((time.time() - start) * 1000),
                "error": str(e),
            }


# Synchronous wrapper for convenience
def execute_sync(endpoint: str, input_text: str) -> ExecutionResult:
    """Synchronous version of execute."""
    executor = Executor()
    return asyncio.run(executor.execute(endpoint, input_text))
