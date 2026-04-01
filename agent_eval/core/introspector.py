"""
Agent introspection for Lilly Agent Eval.

Discovers agent capabilities by querying the agent directly.
"""

import httpx
import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional, Dict, List
import logging

from .executor import Executor

logger = logging.getLogger(__name__)


@dataclass
class AgentProfile:
    """Profile of a discovered agent."""
    endpoint: str
    name: str
    purpose: str
    agent_type: str  # "rag", "conversational", "tool_using", "simple"
    domain: str  # "hr_policies", "customer_support", "healthcare", "general"
    capabilities: List[str]
    raw_response: str
    discovered: bool = True  # False only if agent is completely unreachable
    discovery_error: Optional[str] = None  # Error message if discovery failed
    auth_hint: Optional[str] = None  # Detected auth type: "api_key", "bearer", "none"
    auth_header: Optional[str] = None  # Detected auth header name: "X-API-Key", etc.
    discovered_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())

    def to_dict(self) -> dict:
        """Convert to dictionary."""
        return {
            "endpoint": self.endpoint,
            "name": self.name,
            "purpose": self.purpose,
            "agent_type": self.agent_type,
            "domain": self.domain,
            "capabilities": self.capabilities,
            "raw_response": self.raw_response,
            "discovered": self.discovered,
            "discovery_error": self.discovery_error,
            "auth_hint": self.auth_hint,
            "auth_header": self.auth_header,
            "discovered_at": self.discovered_at,
        }


class AgentIntrospector:
    """
    Discover agent capabilities by querying it.

    Strategy:
    1. Test connectivity (fail fast if agent is down)
    2. Try /describe, /metadata, /info endpoints (structured introspection)
    3. Send discovery prompts via the chat endpoint
    4. If all else fails but agent IS reachable, return a basic profile
       with discovered=True so evaluation can still proceed
    """

    DISCOVERY_PROMPTS = [
        "What is your role and purpose? What kind of questions can you answer?",
        "Describe yourself: what are you designed to do?",
    ]

    # Keywords to detect agent type
    TYPE_KEYWORDS = {
        "rag": ["context", "documents", "knowledge base", "retrieval", "upload", "provided"],
        "conversational": ["chat", "conversation", "memory", "history", "follow-up", "multi-agent", "multi-turn"],
        "tool_using": ["tools", "functions", "actions", "api", "execute", "call"],
    }

    # Keywords to detect domain
    DOMAIN_KEYWORDS = {
        "hr_policies": ["hr", "human resources", "employee", "pto", "time off", "vacation", "benefits", "policy"],
        "customer_support": ["customer", "support", "help", "ticket", "issue", "product", "order", "return"],
        "healthcare": ["health", "medical", "patient", "doctor", "medication", "prescription", "symptom"],
        "finance": ["finance", "money", "account", "transaction", "payment", "invoice", "budget"],
        "legal": ["legal", "contract", "compliance", "regulation", "law", "agreement"],
        "technical": ["code", "programming", "software", "technical", "api", "debug", "error"],
    }

    def __init__(self, timeout: float = 30.0):
        """Initialize introspector with timeout."""
        self.executor = Executor(timeout=timeout)

    async def introspect(
        self,
        endpoint: str,
        headers: Optional[Dict[str, str]] = None
    ) -> AgentProfile:
        """
        Query agent to discover its purpose and capabilities.

        Strategy (ordered by speed):
        1. Try /describe with auth headers — fast, no LLM call, proves connectivity
        2. Try root / endpoint (often has agent identity, usually no auth needed)
        3. If no structured endpoint works, test connectivity
        4. Send discovery prompts to the chat endpoint (with auth)
        5. Fallback: reachable but unidentified → default profile

        Returns:
            AgentProfile. Check .discovered flag:
            - True: agent responded (fully or partially identified)
            - False: agent is unreachable (evaluation should not proceed)
        """
        # Step 1: Try /describe with auth headers — fastest path
        describe_result = await self._try_describe_endpoints(endpoint, headers)
        if describe_result:
            # Enrich with auth hints from root endpoint if not already set
            if not describe_result.auth_hint:
                auth_info = await self._check_root_auth(endpoint)
                if auth_info:
                    describe_result.auth_hint = auth_info.get("auth_hint")
                    describe_result.auth_header = auth_info.get("auth_header")
            return describe_result

        # Step 2: Try root / endpoint — often has agent identity, no auth
        root_result = await self._try_root_endpoint(endpoint)
        if root_result:
            return root_result

        # Step 3: No structured endpoint — test basic connectivity
        conn = await self.executor.test_connection(endpoint, headers=headers)
        if not conn.get("success"):
            error_msg = conn.get("error", "Connection failed")
            return AgentProfile(
                endpoint=endpoint,
                name="Unreachable Agent",
                purpose="",
                agent_type="unknown",
                domain="unknown",
                capabilities=[],
                raw_response="",
                discovered=False,
                discovery_error=f"Cannot connect to agent: {error_msg}",
            )

        # Step 4: Agent is reachable. Try discovery prompts (with auth).
        for prompt in self.DISCOVERY_PROMPTS:
            result = await self.executor.execute(endpoint, prompt, headers=headers)
            if result.output and len(result.output.strip()) > 10:
                return self._parse_response(endpoint, result.output)

        # Step 5: Agent is reachable but we couldn't identify it.
        # Still return discovered=True so evaluation can proceed.
        return AgentProfile(
            endpoint=endpoint,
            name="Agent",
            purpose="Agent is reachable but could not be fully identified",
            agent_type="simple",
            domain="general",
            capabilities=[],
            raw_response="",
            discovered=True,
            discovery_error="Agent is reachable but did not respond to discovery prompts. Using default profile.",
        )

    async def _check_root_auth(
        self,
        endpoint: str,
    ) -> Optional[Dict]:
        """Quick check of root endpoint for auth requirements only."""
        from urllib.parse import urlparse

        parsed = urlparse(endpoint)
        root_url = f"{parsed.scheme}://{parsed.netloc}"

        try:
            async with httpx.AsyncClient(timeout=3.0) as client:
                response = await client.get(root_url)
                if response.status_code == 200:
                    try:
                        data = response.json()
                    except Exception:
                        return None
                    if isinstance(data, dict):
                        raw_auth = data.get("auth") or data.get("authentication") or data.get("auth_type")
                        if raw_auth:
                            raw_auth_str = str(raw_auth).lower()
                            if "api_key" in raw_auth_str or "apikey" in raw_auth_str:
                                return {"auth_hint": "api_key", "auth_header": data.get("auth_header", "X-API-Key")}
                            elif "bearer" in raw_auth_str or "token" in raw_auth_str:
                                return {"auth_hint": "bearer", "auth_header": None}
        except Exception:
            pass
        return None

    async def _try_root_endpoint(
        self,
        endpoint: str,
    ) -> Optional[AgentProfile]:
        """
        Try the root / endpoint which often returns health/identity info.

        Many agents have a GET / that returns status, name, and capabilities
        without requiring authentication.
        """
        from urllib.parse import urlparse

        parsed = urlparse(endpoint)
        root_url = f"{parsed.scheme}://{parsed.netloc}"

        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                response = await client.get(root_url)
                if response.status_code == 200:
                    try:
                        data = response.json()
                    except Exception:
                        return None

                    if not isinstance(data, dict):
                        return None

                    # Check if root response has identity info
                    has_identity = any(
                        data.get(k) for k in [
                            "name", "agent", "agent_name", "title",
                            "purpose", "description", "about",
                        ]
                    )
                    if not has_identity:
                        return None

                    name = (
                        data.get("name")
                        or data.get("agent_name")
                        or data.get("agent")
                        or data.get("title")
                        or "Agent"
                    )
                    # Capitalize simple slug names like "hr-policy-rag"
                    if "-" in name and name == name.lower():
                        name = name.replace("-", " ").replace("_", " ").title()

                    purpose = (
                        data.get("purpose")
                        or data.get("description")
                        or data.get("about")
                        or ""
                    )
                    agent_type = (
                        data.get("type")
                        or data.get("agent_type")
                        or "simple"
                    )
                    domain = data.get("domain") or "general"
                    capabilities = data.get("capabilities", [])
                    if isinstance(capabilities, str):
                        capabilities = [capabilities]

                    # Infer type/domain from name+purpose if not explicit
                    combined = f"{name} {purpose}".lower()
                    if agent_type == "simple":
                        for type_name, keywords in self.TYPE_KEYWORDS.items():
                            if any(kw in combined for kw in keywords):
                                agent_type = type_name
                                break
                    if domain == "general":
                        for domain_name, keywords in self.DOMAIN_KEYWORDS.items():
                            if any(kw in combined for kw in keywords):
                                domain = domain_name
                                break

                    # Detect auth hint from root response
                    auth_hint = None
                    auth_header = None
                    raw_auth = data.get("auth") or data.get("authentication") or data.get("auth_type")
                    if raw_auth:
                        raw_auth_str = str(raw_auth).lower()
                        if "api_key" in raw_auth_str or "apikey" in raw_auth_str:
                            auth_hint = "api_key"
                            auth_header = data.get("auth_header", "X-API-Key")
                        elif "bearer" in raw_auth_str or "token" in raw_auth_str:
                            auth_hint = "bearer"
                        elif "none" in raw_auth_str or "false" in raw_auth_str:
                            auth_hint = "none"

                    return AgentProfile(
                        endpoint=endpoint,
                        name=name,
                        purpose=purpose,
                        agent_type=agent_type,
                        domain=domain,
                        capabilities=capabilities,
                        raw_response=str(data),
                        auth_hint=auth_hint,
                        auth_header=auth_header,
                    )
        except Exception as e:
            logger.debug(f"Root endpoint check failed: {e}")

        return None

    async def _try_describe_endpoints(
        self,
        endpoint: str,
        headers: Optional[Dict[str, str]] = None
    ) -> Optional[AgentProfile]:
        """
        Try multiple introspection endpoint patterns.

        Tries both POST and GET on /describe, /metadata, /info paths
        derived from the chat endpoint URL.
        """
        from urllib.parse import urlparse

        parsed = urlparse(endpoint)
        origin = f"{parsed.scheme}://{parsed.netloc}"  # e.g., http://host:8001

        # Build ordered list of base URLs to try (most likely first)
        base_urls = []
        # 1. Origin (strips the path entirely) — most reliable
        base_urls.append(origin)
        # 2. Parent path (e.g., /v1/chat → /v1)
        if parsed.path and parsed.path != "/":
            parent = parsed.path.rsplit("/", 1)[0]
            if parent and parent != "/":
                parent_url = f"{origin}{parent}"
                if parent_url not in base_urls:
                    base_urls.append(parent_url)

        # Introspection paths to try
        introspection_paths = ["/describe", "/metadata", "/info"]

        request_headers = {"Content-Type": "application/json"}
        if headers:
            request_headers.update(headers)

        async with httpx.AsyncClient(timeout=10.0) as client:
            for base_url in base_urls:
                for path in introspection_paths:
                    url = f"{base_url}{path}"
                    profile = await self._try_single_describe(client, url, endpoint, request_headers)
                    if profile:
                        return profile

        return None

    async def _try_single_describe(
        self,
        client: httpx.AsyncClient,
        url: str,
        original_endpoint: str,
        headers: Dict[str, str],
    ) -> Optional[AgentProfile]:
        """Try a single describe URL with both POST and GET."""
        for method in ["POST", "GET"]:
            try:
                if method == "POST":
                    response = await client.post(url, json={}, headers=headers)
                else:
                    response = await client.get(url, headers=headers)

                if response.status_code == 200:
                    try:
                        data = response.json()
                    except Exception:
                        continue

                    if not isinstance(data, dict):
                        continue

                    # Must have at least a name, purpose, or description to count
                    has_identity = any(
                        data.get(k) for k in ["name", "purpose", "description", "agent_name", "title", "about"]
                    )
                    if not has_identity:
                        continue

                    name = (
                        data.get("name")
                        or data.get("agent_name")
                        or data.get("title")
                        or "Agent"
                    )
                    purpose = (
                        data.get("purpose")
                        or data.get("description")
                        or data.get("about")
                        or ""
                    )
                    agent_type = (
                        data.get("type")
                        or data.get("agent_type")
                        or "simple"
                    )
                    domain = (
                        data.get("domain")
                        or "general"
                    )
                    capabilities = data.get("capabilities", [])
                    if isinstance(capabilities, str):
                        capabilities = [capabilities]

                    # Detect auth hint
                    auth_hint = None
                    auth_header = None
                    raw_auth = data.get("auth") or data.get("authentication") or data.get("auth_type")
                    if raw_auth:
                        raw_auth_str = str(raw_auth).lower()
                        if "api_key" in raw_auth_str or "apikey" in raw_auth_str:
                            auth_hint = "api_key"
                            auth_header = data.get("auth_header", "X-API-Key")
                        elif "bearer" in raw_auth_str or "token" in raw_auth_str:
                            auth_hint = "bearer"

                    return AgentProfile(
                        endpoint=original_endpoint,
                        name=name,
                        purpose=purpose,
                        agent_type=agent_type,
                        domain=domain,
                        capabilities=capabilities,
                        raw_response=str(data),
                        auth_hint=auth_hint,
                        auth_header=auth_header,
                    )
                elif response.status_code == 404:
                    # Path doesn't exist — no point trying GET on same path
                    break

            except (httpx.ConnectError, httpx.TimeoutException):
                # Connection failed — no point trying other methods on same URL
                break
            except Exception as e:
                logger.debug(f"Introspection {method} {url} failed: {e}")
                continue

        return None

    def _parse_response(self, endpoint: str, response: str) -> AgentProfile:
        """
        Parse agent's self-description to extract structured information.

        Uses keyword matching to infer type and domain.
        """
        response_lower = response.lower()

        # Infer agent type
        agent_type = "simple"
        for type_name, keywords in self.TYPE_KEYWORDS.items():
            if any(kw in response_lower for kw in keywords):
                agent_type = type_name
                break

        # Infer domain
        domain = "general"
        for domain_name, keywords in self.DOMAIN_KEYWORDS.items():
            if any(kw in response_lower for kw in keywords):
                domain = domain_name
                break

        # Extract capabilities
        capabilities = self._extract_capabilities(response_lower, agent_type)

        # Extract name (first sentence or truncated response)
        name = self._extract_name(response)

        # Purpose is the full response, truncated if needed
        purpose = response[:500] if len(response) > 500 else response

        return AgentProfile(
            endpoint=endpoint,
            name=name,
            purpose=purpose,
            agent_type=agent_type,
            domain=domain,
            capabilities=capabilities,
            raw_response=response,
        )

    def _extract_name(self, response: str) -> str:
        """Extract a short name from the response."""
        # Look for "I am..." pattern
        match = re.search(r"I am (?:a |an )?([^.!?]+)", response, re.IGNORECASE)
        if match:
            name = match.group(1).strip()
            # Clean up common words
            name = re.sub(r"^(that|which|who)\s+", "", name, flags=re.IGNORECASE)
            if len(name) < 50:
                return name.title()

        # Fall back to first sentence
        first_sentence = response.split(".")[0].strip()
        if len(first_sentence) < 50:
            return first_sentence

        return "AI Assistant"

    def _extract_capabilities(self, response_lower: str, agent_type: str) -> List[str]:
        """Extract capabilities based on response content."""
        capabilities = []

        if agent_type == "rag":
            capabilities.append("context_aware")
            if "upload" in response_lower:
                capabilities.append("document_upload")
            if "question" in response_lower or "answer" in response_lower:
                capabilities.append("qa")

        if agent_type == "conversational":
            capabilities.append("multi_turn")
            if "memory" in response_lower or "remember" in response_lower:
                capabilities.append("memory")

        if agent_type == "tool_using":
            capabilities.append("tool_calling")

        # General capabilities
        if "stream" in response_lower:
            capabilities.append("streaming")

        return capabilities


def get_suggested_metrics(agent_type: str) -> List[str]:
    """Get suggested evaluation metrics based on agent type."""
    base_metrics = ["answer_relevancy"]

    type_metrics = {
        "rag": ["faithfulness", "precision_at_k", "recall_at_k"],
        "conversational": ["coherence", "context_retention"],
        "tool_using": ["tool_correctness", "tool_sequence"],
        "orchestrator": ["tool_correctness", "tool_sequence", "task_completion"],
        "simple": ["answer_relevancy", "similarity"],
    }

    return base_metrics + type_metrics.get(agent_type, [])
