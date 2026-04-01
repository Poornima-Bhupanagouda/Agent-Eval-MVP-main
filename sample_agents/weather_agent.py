"""
Weather Agent - Real-time weather forecasts using Open-Meteo API.

A tool-using agent that wraps the Open-Meteo geocoding and forecast APIs.
No LLM or API keys required - uses completely free, open APIs.

Tools:
  - geocode_city(city_name) -> lat/lon coordinates
  - get_forecast(latitude, longitude) -> 3-day weather forecast

Port: 8004
"""

import os
import re
import time
import httpx
from typing import Optional, List, Dict, Any

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

# Weather code descriptions (WMO standard)
WEATHER_CODES = {
    0: "Clear sky", 1: "Mainly clear", 2: "Partly cloudy", 3: "Overcast",
    45: "Foggy", 48: "Depositing rime fog",
    51: "Light drizzle", 53: "Moderate drizzle", 55: "Dense drizzle",
    61: "Slight rain", 63: "Moderate rain", 65: "Heavy rain",
    71: "Slight snow", 73: "Moderate snow", 75: "Heavy snow",
    77: "Snow grains", 80: "Slight rain showers", 81: "Moderate rain showers",
    82: "Violent rain showers", 85: "Slight snow showers", 86: "Heavy snow showers",
    95: "Thunderstorm", 96: "Thunderstorm with slight hail", 99: "Thunderstorm with heavy hail",
}

GEOCODING_URL = "https://geocoding-api.open-meteo.com/v1/search"
FORECAST_URL = "https://api.open-meteo.com/v1/forecast"


def extract_city(text: str) -> Optional[str]:
    """Extract city name from natural language input."""
    lower = text.lower().strip()

    # Pattern: "weather in {city}", "forecast for {city}", etc.
    # Stop at punctuation, question marks, or secondary clauses
    patterns = [
        r"(?:weather|forecast|temperature|climate)\s+(?:in|for|at|of)\s+([A-Za-z][A-Za-z\s]{1,30}?)(?:\?|$|\.|,|!|\s+(?:and|what|how|when|where|will|is|are))",
        r"(?:what(?:'s| is) (?:the )?(?:weather|forecast|temperature))\s+(?:in|for|at|of)\s+([A-Za-z][A-Za-z\s]{1,30}?)(?:\?|$|\.|,|!)",
        r"(?:how(?:'s| is) (?:the )?weather)\s+(?:in|for|at)\s+([A-Za-z][A-Za-z\s]{1,30}?)(?:\?|$|\.|,|!)",
        r"(?:will it rain|is it (?:cold|hot|warm))\s+(?:in|at)\s+([A-Za-z][A-Za-z\s]{1,30}?)(?:\?|$|\.|,|!)",
        r"weather\s+forecast\s+for\s+([A-Za-z][A-Za-z\s]{1,30}?)(?:\?|$|\.|,|!)",
    ]

    for pattern in patterns:
        match = re.search(pattern, lower)
        if match:
            city = match.group(1).strip().rstrip('.,!?').strip()
            if city:
                return city.title()

    # If the input is short (likely already a city name), use as-is
    words = text.strip().split()
    if len(words) <= 4 and not any(w.lower() in ("weather", "forecast", "what", "how", "will", "is", "are", "it") for w in words):
        return text.strip().rstrip('.,!?').title()

    # Last resort: take only capitalised/significant words, stop at first sentence boundary
    stop_words = {"the", "in", "for", "at", "of", "what", "is", "how", "weather",
                  "forecast", "temperature", "will", "it", "rain", "cold", "hot",
                  "plan", "trip", "to", "a", "weekend", "and", "about", "tell", "me",
                  "like", "some", "famous", "landmarks", "are", "what's", "whats"}
    # Work sentence-by-sentence — only use the first sentence
    first_sentence = re.split(r'[.!?]', text)[0].strip()
    candidates = [
        w.strip('.,!?;:') for w in first_sentence.split()
        if w.strip('.,!?;:').lower() not in stop_words and len(w.strip('.,!?;:')) > 1
    ]
    if candidates:
        return " ".join(candidates).strip().title()

    return None


async def geocode_city(city_name: str) -> Optional[Dict[str, Any]]:
    """Geocode a city name to coordinates using Open-Meteo."""
    async with httpx.AsyncClient(timeout=10.0, verify=False) as client:
        resp = await client.get(GEOCODING_URL, params={"name": city_name, "count": 1, "language": "en"})
        resp.raise_for_status()
        data = resp.json()

    results = data.get("results", [])
    if not results:
        return None

    r = results[0]
    return {
        "name": r.get("name", city_name),
        "country": r.get("country", ""),
        "latitude": r.get("latitude"),
        "longitude": r.get("longitude"),
        "timezone": r.get("timezone", "auto"),
    }


async def get_forecast(latitude: float, longitude: float) -> Dict[str, Any]:
    """Get current weather + 3-day forecast from Open-Meteo."""
    params = {
        "latitude": latitude,
        "longitude": longitude,
        "current": "temperature_2m,relative_humidity_2m,weather_code,wind_speed_10m",
        "daily": "temperature_2m_max,temperature_2m_min,precipitation_sum,weather_code",
        "timezone": "auto",
        "forecast_days": 3,
    }
    async with httpx.AsyncClient(timeout=10.0, verify=False) as client:
        resp = await client.get(FORECAST_URL, params=params)
        resp.raise_for_status()
        return resp.json()


def format_forecast(city_info: Dict, forecast_data: Dict) -> str:
    """Format forecast data as natural language."""
    current = forecast_data.get("current", {})
    daily = forecast_data.get("daily", {})

    temp = current.get("temperature_2m", "N/A")
    humidity = current.get("relative_humidity_2m", "N/A")
    wind = current.get("wind_speed_10m", "N/A")
    code = current.get("weather_code", 0)
    condition = WEATHER_CODES.get(code, "Unknown")

    city = city_info["name"]
    country = city_info.get("country", "")
    location = f"{city}, {country}" if country else city

    lines = [f"Weather in {location}:", f"Currently: {temp}C, {condition}"]
    lines.append(f"Humidity: {humidity}% | Wind: {wind} km/h")

    dates = daily.get("time", [])
    highs = daily.get("temperature_2m_max", [])
    lows = daily.get("temperature_2m_min", [])
    precip = daily.get("precipitation_sum", [])
    codes = daily.get("weather_code", [])

    if dates:
        lines.append("\n3-Day Forecast:")
        for i, date in enumerate(dates):
            hi = highs[i] if i < len(highs) else "?"
            lo = lows[i] if i < len(lows) else "?"
            rain = precip[i] if i < len(precip) else 0
            wc = codes[i] if i < len(codes) else 0
            desc = WEATHER_CODES.get(wc, "Unknown")
            rain_str = f", {rain}mm precip" if rain and rain > 0 else ""
            lines.append(f"  {date}: {lo}C - {hi}C, {desc}{rain_str}")

    return "\n".join(lines)


# === FastAPI Application ===

app = FastAPI(
    title="Weather Agent",
    description="Real-time weather forecasts using Open-Meteo API (no API key needed)",
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
    input: str = Field(..., description="Natural language weather query")


class ChatResponse(BaseModel):
    output: str
    tool_calls: Optional[List[Dict[str, Any]]] = None
    latency_ms: Optional[int] = None


@app.get("/")
async def root():
    return {
        "name": "Weather Agent",
        "version": "1.0.0",
        "status": "healthy",
        "description": "Real-time weather forecasts via Open-Meteo (no API key needed)",
    }


@app.get("/health")
async def health():
    return {"status": "healthy"}


@app.post("/describe")
async def describe():
    return {
        "name": "Weather Agent",
        "purpose": "Provides real-time weather forecasts by geocoding city names and fetching forecasts from the Open-Meteo API. No API key required.",
        "type": "tool_using",
        "domain": "weather",
        "capabilities": ["tool_calling", "real_time_data", "question_answering"],
        "tools": [
            {"name": "geocode_city", "description": "Convert city name to latitude/longitude coordinates"},
            {"name": "get_forecast", "description": "Get current weather and 3-day forecast for coordinates"},
        ],
    }


@app.post("/chat", response_model=ChatResponse)
async def chat(request: ChatRequest):
    start = time.time()
    tool_calls = []

    city = extract_city(request.input)
    if not city:
        return ChatResponse(
            output="I couldn't identify a city in your request. Try asking like: 'What's the weather in Paris?'",
            tool_calls=[],
            latency_ms=int((time.time() - start) * 1000),
        )

    # Tool 1: Geocode
    tool_calls.append({"name": "geocode_city", "args": {"city_name": city}})
    city_info = await geocode_city(city)

    if not city_info:
        return ChatResponse(
            output=f"Could not find location '{city}'. Please check the city name and try again.",
            tool_calls=tool_calls,
            latency_ms=int((time.time() - start) * 1000),
        )

    # Tool 2: Forecast
    tool_calls.append({
        "name": "get_forecast",
        "args": {"latitude": city_info["latitude"], "longitude": city_info["longitude"]},
    })
    forecast_data = await get_forecast(city_info["latitude"], city_info["longitude"])

    output = format_forecast(city_info, forecast_data)
    latency = int((time.time() - start) * 1000)

    return ChatResponse(output=output, tool_calls=tool_calls, latency_ms=latency)


def main():
    import uvicorn
    port = int(os.environ.get("WEATHER_AGENT_PORT", 8004))
    host = os.environ.get("HOST", "127.0.0.1")
    print(f"\nWeather Agent starting at http://{host}:{port}")
    print(f"  API docs: http://{host}:{port}/docs")
    print(f"  Uses Open-Meteo API (no API key needed)\n")
    uvicorn.run(app, host=host, port=port)


if __name__ == "__main__":
    main()
