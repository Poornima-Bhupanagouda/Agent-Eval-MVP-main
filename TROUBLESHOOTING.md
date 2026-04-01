# Troubleshooting Python Cache Issue

## Problem
Server fails to start with error:
```
ImportError: cannot import name 'ExecutionResult' from 'agent_eval.models'
```

Even though the actual code has been fixed and imports are correct.

## Root Cause
Python's import system is caching an old version of the module, likely due to:
1. OneDrive file synchronization delays
2. System-level Python bytecode cache
3. IDE/editor caching
4. Terminal session caching

## Solutions (Try in Order)

### Solution 1: Restart Everything
```bash
# Close your terminal
# Close your IDE/editor
# Wait 30 seconds for OneDrive to sync
# Open fresh terminal
# Navigate to project
cd /Users/L040495/Library/CloudStorage/OneDrive-EliLillyandCompany/Projects/agent-eval-mvp

# Clear all cache
find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null
find . -name "*.pyc" -delete 2>/dev/null

# Start server
./start-agenteval.sh
```

### Solution 2: Force Python Cache Clear
```bash
# Kill all Python processes
pkill -9 python3

# Clear cache with Python
python3 << 'EOF'
import sys
import os
import shutil

# Clear pycache
for root, dirs, files in os.walk('.'):
    for d in dirs:
        if d == '__pycache__':
            path = os.path.join(root, d)
            shutil.rmtree(path, ignore_errors=True)
            print(f"Removed: {path}")
EOF

# Start with no bytecode
export PYTHONDONTWRITEBYTECODE=1
python3 -B -m uvicorn agent_eval.web.app:app --host 0.0.0.0 --port 8000
```

### Solution 3: Move Project Out of OneDrive
```bash
# Copy project to local disk
cp -r /Users/L040495/Library/CloudStorage/OneDrive-EliLillyandCompany/Projects/agent-eval-mvp ~/agent-eval-mvp-local

# Navigate
cd ~/agent-eval-mvp-local

# Clear cache
find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null

# Start
export PYTHONPATH="${PWD}:${PYTHONPATH}"
python3 -m uvicorn agent_eval.web.app:app --host 0.0.0.0 --port 8000
```

### Solution 4: Use Virtual Environment
```bash
# Create fresh venv
python3 -m venv venv_fresh

# Activate
source venv_fresh/bin/activate

# Install deps
pip install -r requirements.txt

# Start
python3 -m uvicorn agent_eval.web.app:app --host 0.0.0.0 --port 8000
```

### Solution 5: Direct Import Test
```bash
# Test if imports work
python3 << 'EOF'
import sys
sys.path.insert(0, '.')

# Test each import
try:
    from agent_eval.adapters.python_function_adapter import PythonFunctionAdapter
    print("✅ python_function_adapter OK")
except Exception as e:
    print(f"❌ python_function_adapter FAILED: {e}")

try:
    from agent_eval.adapters.llm_adapters import LillyGatewayAdapter
    print("✅ llm_adapters OK")
except Exception as e:
    print(f"❌ llm_adapters FAILED: {e}")

print("\nIf all OK, the cache issue is in uvicorn startup")
EOF
```

## Verification Steps

### 1. Check File is Correct
```bash
# Should NOT contain python_function_adapter import
cat agent_eval/adapters/__init__.py | grep -n "python_function"
# Should return nothing

# Should show correct import
head -20 agent_eval/adapters/python_function_adapter.py | grep ExecutionResult
# Should show: from agent_eval.execution.models import ExecutionResult
```

### 2. Check No Cache Files
```bash
# Should be empty or not exist
ls -la agent_eval/adapters/__pycache__/ 2>/dev/null
```

### 3. Test Import Directly
```bash
python3 -c "from agent_eval.adapters.python_function_adapter import PythonFunctionAdapter; print('OK')"
```

## If All Else Fails

### Temporary Workaround: Remove New Adapters
```bash
# Edit agent_eval/web/app.py
# Comment out line ~53-70 (the load_all_adapters function call)

# Start server with just REST adapter
python3 -m uvicorn agent_eval.web.app:app --host 0.0.0.0 --port 8000
```

Then manually import adapters after server starts via API:
```python
# In Python REPL or script
from agent_eval.adapters.python_function_adapter import PythonFunctionAdapter
# etc.
```

## Success Criteria

Server should start and show:
```
INFO:     Application startup complete.
INFO:     Uvicorn running on http://0.0.0.0:8000
```

Test with:
```bash
curl http://localhost:8000/health
# Should return: {"status":"healthy",...}
```

## Contact
If none of these work, the issue may be:
1. OneDrive aggressive caching/syncing
2. macOS file system caching
3. Python installation issue

Consider:
- Disabling OneDrive sync temporarily
- Restarting computer
- Using different Python version
