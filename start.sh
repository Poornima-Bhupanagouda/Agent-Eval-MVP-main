#!/bin/bash
# Start the Lilly Agent Eval platform and agents
# Usage: ./start.sh              - Start eval platform + RAG agent
#        ./start.sh --full       - Start all agents (including travel fleet)
#        ./start.sh stop         - Stop all services

PID_DIR=".agent_eval_pids"
EVAL_PID_FILE="$PID_DIR/eval.pid"
AGENT_PID_FILE="$PID_DIR/agent.pid"
WEATHER_PID_FILE="$PID_DIR/weather.pid"
WIKI_PID_FILE="$PID_DIR/wiki.pid"
CALC_PID_FILE="$PID_DIR/calc.pid"
ORCH_PID_FILE="$PID_DIR/orchestrator.pid"

FULL_MODE=false
if [ "$1" = "--full" ]; then
    FULL_MODE=true
fi

stop_services() {
    echo "Stopping services..."
    # Kill from PID files
    for pidfile in "$EVAL_PID_FILE" "$AGENT_PID_FILE" "$WEATHER_PID_FILE" "$WIKI_PID_FILE" "$CALC_PID_FILE" "$ORCH_PID_FILE"; do
        if [ -f "$pidfile" ]; then
            pid=$(cat "$pidfile")
            kill "$pid" 2>/dev/null || true
            echo "  Stopped PID $pid"
            rm -f "$pidfile"
        fi
    done
    # Kill anything still on our ports (only our known ports)
    for port in 8000 8003 8004 8005 8006 8010; do
        pids=$(lsof -ti:$port 2>/dev/null || true)
        if [ -n "$pids" ]; then
            echo "$pids" | xargs kill 2>/dev/null || true
            echo "  Cleared port $port"
        fi
    done
    echo "All services stopped."
}

# Handle "stop" command
if [ "$1" = "stop" ]; then
    stop_services
    exit 0
fi

TOTAL_STEPS=5
if [ "$FULL_MODE" = true ]; then
    TOTAL_STEPS=7
fi

echo ""
echo "  Lilly Agent Eval - Starting Services"
if [ "$FULL_MODE" = true ]; then
    echo "  Mode: FULL (eval + RAG + travel agent fleet)"
fi
echo "========================================"
echo ""

# Step 1: Clean up any leftover processes from previous sessions
echo "[1/${TOTAL_STEPS}] Cleaning up old processes..."
stop_services 2>/dev/null
mkdir -p "$PID_DIR"
sleep 1

# Step 2: Load environment
echo "[2/${TOTAL_STEPS}] Loading environment..."
if [ -f .env ]; then
    export $(grep -v '^#' .env | grep -v '^\s*$' | xargs)
    echo "  Loaded .env"
else
    echo "  No .env file found (using defaults)"
fi

# Step 3: Start Smart RAG Agent
echo "[3/${TOTAL_STEPS}] Starting HR Policy RAG Agent on port 8003..."
python3 -m uvicorn sample_agents.smart_rag_agent:app --host 127.0.0.1 --port 8003 &
AGENT_PID=$!
echo $AGENT_PID > "$AGENT_PID_FILE"

# Wait for agent to be ready (retry up to 15 seconds)
echo -n "  Waiting for agent"
for i in $(seq 1 15); do
    if curl -s http://127.0.0.1:8003/ > /dev/null 2>&1; then
        echo " ready! (${i}s)"
        break
    fi
    if ! kill -0 $AGENT_PID 2>/dev/null; then
        echo ""
        echo "  ERROR: RAG Agent failed to start. Check logs above."
        exit 1
    fi
    echo -n "."
    sleep 1
done

# Verify agent is actually running
if ! kill -0 $AGENT_PID 2>/dev/null; then
    echo ""
    echo "  ERROR: RAG Agent crashed during startup."
    exit 1
fi
if ! curl -s http://127.0.0.1:8003/ > /dev/null 2>&1; then
    echo ""
    echo "  WARNING: RAG Agent started but not responding to health checks yet."
    echo "  The agent may still be loading KB documents. Continuing startup..."
fi

# Step 4: Start Evaluation Platform
echo "[4/${TOTAL_STEPS}] Starting Eval Platform on port 8000..."
python3 -m uvicorn agent_eval.web.app:app --host 127.0.0.1 --port 8000 &
EVAL_PID=$!
echo $EVAL_PID > "$EVAL_PID_FILE"

# Wait for eval platform to be ready
echo -n "  Waiting for platform"
for i in $(seq 1 10); do
    if curl -s http://127.0.0.1:8000/api/health > /dev/null 2>&1; then
        echo " ready! (${i}s)"
        break
    fi
    if ! kill -0 $EVAL_PID 2>/dev/null; then
        echo ""
        echo "  ERROR: Eval Platform failed to start. Check logs above."
        kill $AGENT_PID 2>/dev/null
        exit 1
    fi
    echo -n "."
    sleep 1
done

# Verify eval platform
if ! kill -0 $EVAL_PID 2>/dev/null; then
    echo ""
    echo "  ERROR: Eval Platform crashed during startup."
    kill $AGENT_PID 2>/dev/null
    exit 1
fi

# Step 5 (full mode): Start Travel Agent Fleet
if [ "$FULL_MODE" = true ]; then
    echo "[5/${TOTAL_STEPS}] Starting Travel Agent Fleet..."

    # Weather Agent (port 8004)
    echo "  Starting Weather Agent on port 8004..."
    python3 -m uvicorn sample_agents.weather_agent:app --host 127.0.0.1 --port 8004 &
    echo $! > "$WEATHER_PID_FILE"

    # Wiki Agent (port 8005)
    echo "  Starting Wiki Agent on port 8005..."
    python3 -m uvicorn sample_agents.wiki_agent:app --host 127.0.0.1 --port 8005 &
    echo $! > "$WIKI_PID_FILE"

    # Calculator Agent (port 8006)
    echo "  Starting Calculator Agent on port 8006..."
    python3 -m uvicorn sample_agents.calculator_agent:app --host 127.0.0.1 --port 8006 &
    echo $! > "$CALC_PID_FILE"

    # Wait for tool agents to be ready
    echo -n "  Waiting for tool agents"
    for i in $(seq 1 10); do
        W=$(curl -s http://127.0.0.1:8004/health 2>/dev/null | grep -c healthy)
        K=$(curl -s http://127.0.0.1:8005/health 2>/dev/null | grep -c healthy)
        C=$(curl -s http://127.0.0.1:8006/health 2>/dev/null | grep -c healthy)
        if [ "$W" -ge 1 ] && [ "$K" -ge 1 ] && [ "$C" -ge 1 ]; then
            echo " ready! (${i}s)"
            break
        fi
        echo -n "."
        sleep 1
    done

    # Step 6: Start Travel Orchestrator (needs tool agents running)
    echo "[6/${TOTAL_STEPS}] Starting Travel Orchestrator on port 8010..."
    python3 -m uvicorn sample_agents.travel_orchestrator:app --host 127.0.0.1 --port 8010 &
    echo $! > "$ORCH_PID_FILE"

    echo -n "  Waiting for orchestrator"
    for i in $(seq 1 10); do
        if curl -s http://127.0.0.1:8010/health > /dev/null 2>&1; then
            echo " ready! (${i}s)"
            break
        fi
        echo -n "."
        sleep 1
    done
fi

# Final verification
STEP_NUM=$((TOTAL_STEPS))
echo "[${STEP_NUM}/${TOTAL_STEPS}] Verifying services..."

AGENT_OK=false
EVAL_OK=false

if curl -s http://127.0.0.1:8003/ | grep -q "healthy" 2>/dev/null; then
    AGENT_OK=true
    echo "  RAG Agent:     OK (port 8003)"
else
    echo "  RAG Agent:     FAILED"
fi

if curl -s http://127.0.0.1:8000/api/health | grep -q "healthy" 2>/dev/null; then
    EVAL_OK=true
    echo "  Eval Platform: OK (port 8000)"
else
    echo "  Eval Platform: FAILED"
fi

if [ "$FULL_MODE" = true ]; then
    for agent_info in "Weather:8004" "Wiki:8005" "Calculator:8006" "Orchestrator:8010"; do
        name="${agent_info%%:*}"
        port="${agent_info##*:}"
        if curl -s "http://127.0.0.1:${port}/health" | grep -q "healthy" 2>/dev/null; then
            echo "  ${name} Agent: OK (port ${port})"
        else
            echo "  ${name} Agent: FAILED (port ${port})"
        fi
    done
fi

echo ""
echo "========================================"
if [ "$AGENT_OK" = true ] && [ "$EVAL_OK" = true ]; then
    echo "  All services running!"
else
    echo "  WARNING: Some services failed to start"
fi
echo ""
echo "  Evaluation Platform: http://127.0.0.1:8000"
echo "  HR Policy RAG Agent: http://127.0.0.1:8003"
if [ "$FULL_MODE" = true ]; then
    echo ""
    echo "  Travel Agent Fleet:"
    echo "    Weather Agent:     http://127.0.0.1:8004"
    echo "    Wiki Agent:        http://127.0.0.1:8005"
    echo "    Calculator Agent:  http://127.0.0.1:8006"
    echo "    Travel Orchestrator: http://127.0.0.1:8010"
fi
echo ""
echo "  Stop services:  ./start.sh stop"
echo "  Press Ctrl+C to stop all services"
echo "========================================"

# Clean shutdown on interrupt - set trap BEFORE wait
trap "stop_services; exit 0" SIGINT SIGTERM
wait
