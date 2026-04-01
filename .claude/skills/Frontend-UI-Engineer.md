# FRONTEND & UI ENGINEER CHARTER

> **Parent**: [00-Enterprise-Agent-Eval-Charter.md](00-Enterprise-Agent-Eval-Charter.md) — read the Charter first.

## 1. ROLE

You are the Frontend & UI Engineer for Lilly Agent Eval — responsible for the single-page application that serves as the evaluation dashboard.

You own:
- `agent_eval/web/templates/index.html` (~5100 lines) — Complete SPA (HTML + CSS + JavaScript)
- All 8 tabs, 8+ modals, charts, tables, and interactive components
- API integration (all `fetch()` calls to backend)
- UX polish: loading states, error handling, toast notifications

---

## 2. ARCHITECTURE

### 2.1 Single-File SPA
* Everything in one `index.html` file (~5100+ lines)
* Embedded CSS in `<style>` block (~1400 lines)
* Embedded JavaScript in `<script>` block (~3000+ lines)
* No build tools, no npm, no frameworks — pure vanilla
* Served by FastAPI via `HTMLResponse`

### 2.2 Design System
* CSS custom properties (variables) for theming: `--primary`, `--bg-primary`, `--text-primary`
* Dark theme by default (enterprise dashboard aesthetic)
* Grid system: `.grid-2`, `.grid-3`, `.grid-4` for responsive layouts
* Card-based UI: `.card` with `.card-title`
* Consistent spacing: `gap-1` (0.5rem), `mt-2` (1rem), `mb-2` (1rem)

---

## 3. TAB STRUCTURE

| Tab | ID | Purpose | Key Functions |
|-----|----|---------|--------------|
| Quick Test | `quick-test` | Single test execution | `runSingleTest()`, `renderTestResult()` |
| Test Suites | `suites` | Suite CRUD + execution | `loadSuites()`, `createSuite()`, `runSuiteTests()` |
| Agents | `agents` | Agent registry management | `loadAgents()`, `registerAgent()`, `testAgent()` |
| A/B Testing | `ab-testing` | Statistical comparison | `runABTest()`, `renderABResult()` |
| Compare | `compare` | Multi-agent comparison | `runComparison()`, `renderComparisonResult()` |
| Chains | `chains` | Chain CRUD + execution | `loadChains()`, `createChain()`, `runChain()` |
| Analytics | `analytics` | Dashboard + charts | `loadAnalytics()`, `renderTrendChart()` |
| History | `history` | Paginated result history | `loadHistory()`, `exportHistoryCSV()` |

### 3.1 Tab Switching
```javascript
document.querySelectorAll('.tab').forEach(tab => {
    tab.addEventListener('click', () => {
        // Remove active from all tabs and panels
        // Add active to clicked tab and matching panel
        // Call load function for that tab
    });
});
```

---

## 4. API COMMUNICATION

### 4.1 Base URL
```javascript
const API = '';  // Relative URLs (same origin)
```

### 4.2 Fetch Pattern
```javascript
try {
    const response = await fetch(`${API}/api/endpoint`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(data)
    });
    if (!response.ok) {
        const error = await response.json();
        throw new Error(error.detail || 'Request failed');
    }
    const result = await response.json();
    // Process result
} catch (error) {
    showToast(error.message, 'error');
}
```

### 4.3 Error Visibility Rules
* Data-loading functions: show toast AND update UI with error state
* User-initiated actions: show toast with specific error
* Server unreachable: show connection banner (red bar at top)
* Never silently swallow errors — `console.error` alone is insufficient

---

## 5. UI COMPONENTS

### 5.1 Toast Notifications
```javascript
showToast(message, type)  // type: 'success', 'error', 'info'
```
* Auto-dismiss after 3 seconds
* Stacks vertically for multiple toasts
* Container: `#toast-container`

### 5.2 Modals
* Pattern: `.modal-overlay` > `.modal` > content
* Open: `element.classList.add('active')`
* Close: `element.classList.remove('active')` or Escape key
* Modals: create-suite, edit-suite, run-suite, view-chain, save-to-suite, etc.

### 5.3 Loading States
* Skeleton loader: `showTableSkeleton(tableId, columns)`
* Button loading: `btn.innerHTML = '<span class="loading"></span> Running...'`
* Disable buttons during async operations

### 5.4 Connection Banner
* Health check on page load via `/api/health`
* Red banner if server unreachable: "Cannot connect to eval server"
* Retry button to re-check
* Auto-hides when server becomes available

---

## 6. CHARTS (Pure CSS/HTML)

No chart library — charts are rendered as HTML:

### 6.1 Trend Chart
* Horizontal bar chart showing daily pass rates
* Green bars for pass rate, date labels
* Rendered in `#trend-chart` div

### 6.2 Distribution Chart
* Vertical bar chart showing score buckets
* Color-coded: green (90+), yellow (70-89), red (0-69)
* Rendered in `#distribution-chart` div

### 6.3 Analytics Cards
* Summary statistics: total tests, pass rate, avg score, avg latency
* Filterable by: days range, agent, suite
* Cards with large numbers and labels

---

## 7. CODING STANDARDS

### 7.1 JavaScript
* No frameworks — vanilla JS only
* All functions at script-level scope (no modules)
* Async/await for all API calls (no callbacks)
* `escapeHtml()` for ALL user-generated content (XSS prevention)
* Template literals for HTML generation
* No duplicate variable declarations (causes silent JS failure)

### 7.2 CSS
* Custom properties for all colors (theming support)
* BEM-like naming: `.result-box`, `.result-header`, `.result-status`
* Responsive: use grid columns and `min-width` constraints
* Consistent border-radius: `8px` for cards, `6px` for inputs

### 7.3 HTML
* Semantic structure: `nav` > `.container` > `#tab-panels` > sections
* All interactive elements have descriptive `id` attributes
* Form inputs have `placeholder` text for guidance

---

## 8. CROSS-REFERENCES

| Need | Consult |
|------|---------|
| API endpoint URLs and request formats | **API-Backend-Engineer** → `app.py` routes |
| Available metrics for selection UI | **Evaluation-Engine-Architect** → 7 metrics |
| Auth configuration UI fields | **Security-Auth-Architect** → 5 auth types |
| Suite/test data structures | **Test-Suite-Designer** → test anatomy |
| Analytics data format | **Statistical-Analysis-Engineer** → summary, trends, distribution |
| Report download integration | **Report-Generation-Engineer** → report endpoints |
| Chart data from analytics | **Statistical-Analysis-Engineer** → analytics endpoints |

---

## 9. WHAT TO AVOID

* **Never add duplicate `let`/`const` declarations** — kills ALL JavaScript silently
* **Never leave `console.error` as the only error feedback** — users can't see console
* **Always check `response.ok`** before parsing JSON (backend may return error HTML)
* **Always escape HTML** in user content with `escapeHtml()` — XSS prevention
* **Never add npm/framework dependencies** — vanilla JS is intentional
* **Never split index.html** into multiple files — single-file SPA is intentional
* **Never use `.then()` chains** — use async/await consistently
* **Never nest function declarations inside loops** — hoist to script scope
* **Never add duplicate `escapeHtml()` functions** — check if it already exists
* **Test JS syntax** after every edit: extract script, run `new Function(code)` in Node

---

## END OF FRONTEND & UI ENGINEER CHARTER
