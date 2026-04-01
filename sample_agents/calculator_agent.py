"""
Calculator Agent - Country info, currency conversion, and math.

A tool-using agent that wraps REST Countries, exchange rate APIs,
and provides safe local math evaluation.
No LLM or API keys required - uses completely free, open APIs.

Tools:
  - get_country_info(country) -> capital, population, currencies, languages
  - convert_currency(amount, from_code, to_code) -> converted amount
  - calculate(expression) -> math result

Port: 8006
"""

import os
import re
import ast
import time
import operator
import httpx
from typing import Optional, List, Dict, Any

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

COUNTRIES_URL = "https://restcountries.com/v3.1/name"
EXCHANGE_URL = "https://api.exchangerate-api.com/v4/latest"

# Safe math operators
SAFE_OPS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.Pow: operator.pow,
    ast.Mod: operator.mod,
    ast.USub: operator.neg,
}


def safe_eval(expr: str) -> Optional[float]:
    """Safely evaluate a math expression using AST parsing."""
    expr = expr.strip()
    # Allow only digits, operators, parentheses, decimal points, spaces
    if not re.match(r'^[\d\s\+\-\*\/\(\)\.\%\^]+$', expr):
        return None
    # Replace ^ with ** for power
    expr = expr.replace('^', '**')
    try:
        tree = ast.parse(expr, mode='eval')
        return _eval_node(tree.body)
    except Exception:
        return None


def _eval_node(node):
    """Recursively evaluate an AST node."""
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
        return node.value
    elif isinstance(node, ast.BinOp):
        left = _eval_node(node.left)
        right = _eval_node(node.right)
        op_type = type(node.op)
        if op_type in SAFE_OPS:
            return SAFE_OPS[op_type](left, right)
    elif isinstance(node, ast.UnaryOp):
        operand = _eval_node(node.operand)
        op_type = type(node.op)
        if op_type in SAFE_OPS:
            return SAFE_OPS[op_type](operand)
    raise ValueError(f"Unsupported expression: {ast.dump(node)}")


def detect_intent(text: str) -> Dict[str, Any]:
    """Detect what the user wants: country info, currency conversion, or math."""
    lower = text.lower().strip()

    # Currency conversion patterns
    currency_match = re.search(
        r'(?:convert\s+)?(\d+(?:\.\d+)?)\s*([a-zA-Z]{3})\s+(?:to|in|into)\s+([a-zA-Z]{3})',
        lower
    )
    if currency_match:
        return {
            "type": "currency",
            "amount": float(currency_match.group(1)),
            "from": currency_match.group(2).upper(),
            "to": currency_match.group(3).upper(),
        }

    # Country info patterns
    country_patterns = [
        r"(?:country info|info about|information about|tell me about|about)\s+(?:the\s+)?(.+?)(?:\?|$|\.|\!)",
        r"(?:capital of|population of|currency of|languages? (?:of|in|spoken in))\s+(?:the\s+)?(.+?)(?:\?|$|\.|\!)",
        r"(?:what (?:is|are) the (?:capital|population|currenc|language))\S*\s+(?:of|in)\s+(?:the\s+)?(.+?)(?:\?|$|\.|\!)",
    ]
    for pattern in country_patterns:
        match = re.search(pattern, lower)
        if match:
            return {"type": "country", "country": match.group(1).strip().title()}

    # Math patterns
    math_match = re.search(r'(?:calculate|compute|what is|eval(?:uate)?|solve)\s+(.+?)(?:\?|$)', lower)
    if math_match:
        expr = math_match.group(1).strip()
        if re.match(r'^[\d\s\+\-\*\/\(\)\.\%\^]+$', expr):
            return {"type": "math", "expression": expr}

    # Bare math expression
    if re.match(r'^[\d\s\+\-\*\/\(\)\.\%\^]+$', lower):
        return {"type": "math", "expression": lower}

    # Fallback: try as country name
    stop_words = {"tell", "me", "about", "what", "is", "the", "a", "country", "info", "information"}
    words = [w for w in text.split() if w.lower() not in stop_words]
    if words:
        return {"type": "country", "country": " ".join(words).strip().title()}

    return {"type": "unknown"}


async def get_country_info(country: str) -> Optional[Dict[str, Any]]:
    """Get country information from REST Countries API."""
    async with httpx.AsyncClient(timeout=10.0, verify=False) as client:
        resp = await client.get(
            f"{COUNTRIES_URL}/{country}",
            params={"fields": "name,capital,currencies,population,languages,timezones,region,flags"},
        )
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        data = resp.json()

    if not data or not isinstance(data, list):
        return None

    c = data[0]
    currencies = c.get("currencies", {})
    currency_info = []
    for code, info in currencies.items():
        currency_info.append({"code": code, "name": info.get("name", ""), "symbol": info.get("symbol", "")})

    return {
        "name": c.get("name", {}).get("common", country),
        "official_name": c.get("name", {}).get("official", ""),
        "capital": c.get("capital", ["N/A"])[0] if c.get("capital") else "N/A",
        "population": c.get("population", 0),
        "region": c.get("region", ""),
        "languages": list(c.get("languages", {}).values()),
        "currencies": currency_info,
        "timezones": c.get("timezones", []),
    }


async def convert_currency(amount: float, from_code: str, to_code: str) -> Optional[Dict[str, Any]]:
    """Convert currency using exchange rate API."""
    async with httpx.AsyncClient(timeout=10.0, verify=False) as client:
        resp = await client.get(f"{EXCHANGE_URL}/{from_code}")
        if resp.status_code != 200:
            return None
        data = resp.json()

    rates = data.get("rates", {})
    if to_code not in rates:
        return None

    rate = rates[to_code]
    converted = round(amount * rate, 2)

    return {
        "amount": amount,
        "from": from_code,
        "to": to_code,
        "rate": rate,
        "result": converted,
    }


def format_country_info(info: Dict[str, Any]) -> str:
    """Format country info as natural language."""
    lines = [f"{info['name']}"]
    if info.get("official_name") and info["official_name"] != info["name"]:
        lines[0] += f" (officially: {info['official_name']})"
    lines.append(f"Capital: {info['capital']}")
    pop = info.get("population", 0)
    if pop > 1_000_000:
        lines.append(f"Population: {pop / 1_000_000:.1f} million")
    else:
        lines.append(f"Population: {pop:,}")
    lines.append(f"Region: {info.get('region', 'N/A')}")
    if info.get("languages"):
        lines.append(f"Languages: {', '.join(info['languages'])}")
    if info.get("currencies"):
        curr_strs = [f"{c['name']} ({c['code']}, {c['symbol']})" for c in info["currencies"]]
        lines.append(f"Currencies: {', '.join(curr_strs)}")
    if info.get("timezones"):
        lines.append(f"Timezones: {', '.join(info['timezones'][:3])}")
    return "\n".join(lines)


# === FastAPI Application ===

app = FastAPI(
    title="Calculator Agent",
    description="Country info, currency conversion, and math (no API key needed)",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class ChatRequest(BaseModel):
    input: str = Field(..., description="Country query, currency conversion, or math expression")


class ChatResponse(BaseModel):
    output: str
    tool_calls: Optional[List[Dict[str, Any]]] = None
    latency_ms: Optional[int] = None


@app.get("/")
async def root():
    return {
        "name": "Calculator Agent",
        "version": "1.0.0",
        "status": "healthy",
        "description": "Country info, currency conversion, and math (no API key needed)",
    }


@app.get("/health")
async def health():
    return {"status": "healthy"}


@app.post("/describe")
async def describe():
    return {
        "name": "Calculator Agent",
        "purpose": "Provides country information, currency conversion, and safe math evaluation. Uses REST Countries and exchange rate APIs. No API key required.",
        "type": "tool_using",
        "domain": "data",
        "capabilities": ["tool_calling", "calculation", "data_lookup"],
        "tools": [
            {"name": "get_country_info", "description": "Get country details: capital, population, currencies, languages"},
            {"name": "convert_currency", "description": "Convert between currencies using live exchange rates"},
            {"name": "calculate", "description": "Safely evaluate a math expression"},
        ],
    }


@app.post("/chat", response_model=ChatResponse)
async def chat(request: ChatRequest):
    start = time.time()
    tool_calls = []
    output = ""

    intent = detect_intent(request.input)

    if intent["type"] == "currency":
        tool_calls.append({
            "name": "convert_currency",
            "args": {"amount": intent["amount"], "from": intent["from"], "to": intent["to"]},
        })
        result = await convert_currency(intent["amount"], intent["from"], intent["to"])
        if result:
            output = (
                f"{result['amount']} {result['from']} = {result['result']} {result['to']}\n"
                f"Exchange rate: 1 {result['from']} = {result['rate']} {result['to']}"
            )
        else:
            output = f"Could not convert {intent['from']} to {intent['to']}. Please check the currency codes."

    elif intent["type"] == "country":
        tool_calls.append({"name": "get_country_info", "args": {"country": intent["country"]}})
        info = await get_country_info(intent["country"])
        if info:
            output = format_country_info(info)
        else:
            output = f"Could not find country '{intent['country']}'. Please check the name and try again."

    elif intent["type"] == "math":
        expr = intent["expression"]
        tool_calls.append({"name": "calculate", "args": {"expression": expr}})
        result = safe_eval(expr)
        if result is not None:
            # Format nicely
            if result == int(result):
                output = f"{expr} = {int(result)}"
            else:
                output = f"{expr} = {result}"
        else:
            output = f"Could not evaluate expression: {expr}"

    else:
        output = "I can help with country information, currency conversion, or math. Try: 'info about France', 'convert 100 USD to EUR', or 'calculate 15 * 23'"

    latency = int((time.time() - start) * 1000)
    return ChatResponse(output=output, tool_calls=tool_calls, latency_ms=latency)


def main():
    import uvicorn
    port = int(os.environ.get("CALC_AGENT_PORT", 8006))
    host = os.environ.get("HOST", "127.0.0.1")
    print(f"\nCalculator Agent starting at http://{host}:{port}")
    print(f"  API docs: http://{host}:{port}/docs")
    print(f"  Uses REST Countries + Exchange Rate API (no API key needed)\n")
    uvicorn.run(app, host=host, port=port)


if __name__ == "__main__":
    main()
