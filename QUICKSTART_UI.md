# Quick Start - Web UI

## Start the Server

```bash
cd /Users/L040495/Library/CloudStorage/OneDrive-EliLillyandCompany/Projects/agent-eval-mvp

# Set Python path and start
export PYTHONPATH=/Users/L040495/Library/CloudStorage/OneDrive-EliLillyandCompany/Projects/agent-eval-mvp
python3 agent_eval/web/app.py
```

## Open Browser

Navigate to: **http://localhost:8000**

You should see:
- 🤖 **Agent Eval** header (dark theme)
- Dashboard with quick stats
- Navigation: Dashboard | Test Cases | Results | Settings

## Try It Out

### 1. View Available Agents
Click "Test Cases" → See 5 agents with checkboxes:
- ✓ Rule Validation Agent
- ✓ Quality Assessment Agent
- ✓ Tool Validation Agent
- ✓ Context Validation Agent
- ✓ Hallucination Check Agent

### 2. Create a Test Case
Fill in the form:
- **Test Name:** "My First Test"
- **Input:** "Summarize this text in 3 sentences"
- **Max Words:** 50
- **Must Contain:** summary
- **Select agents** (click checkboxes)
- **Click "Create Test Case"**

You should see: ✓ Success message!

### 3. View API Docs
Navigate to: **http://localhost:8000/docs**

Interactive Swagger UI with all endpoints!

## Troubleshooting

### Port already in use?
```bash
# Use different port
uvicorn agent_eval.web.app:app --port 8001
```

### Can't find modules?
```bash
# Make sure PYTHONPATH is set
export PYTHONPATH=$(pwd)
python3 agent_eval/web/app.py
```

## What Works Now

✅ Dark theme UI
✅ Agent listing with descriptions
✅ Test case creation form
✅ Visual agent selection
✅ Settings configuration
✅ API documentation
✅ Responsive design

## Next: Run Real Tests

To actually execute tests (coming next):
1. Configure your agent endpoint in Settings
2. Create test cases
3. Run tests
4. View results in Results page
