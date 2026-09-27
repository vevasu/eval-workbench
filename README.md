# Eval Workbench

A lightweight evaluation and observability workbench for LLM applications.

It helps teams create structured evaluation cases, run LLM responses against expected behavior, identify failures, and track regressions as prompts or models change.
# Demo video:
https://github.com/user-attachments/assets/0b3a8cbb-48a6-4976-a34a-d3ce691daddb

## Live Demo
https://eval-workbench-917841678315.us-central1.run.app/#/dashboard 

## Why EvalWorkbench?

LLM applications can produce convincing responses while still failing on ambiguity, edge cases, structured outputs, or changes to prompts and models.

EvalWorkbench provides a simple evaluation workflow:

Define → Run → Evaluate → Analyze → Re-test

Instead of evaluating an AI application manually one prompt at a time, test cases can be captured and evaluated systematically.

## What it does
- Create and manage structured LLM evaluation test cases
- Define expected behavior for each test case
- Run test cases against an LLM application
- Compare actual responses with expected outcomes
- Classify results as Pass, Fail, or Review
- Capture evaluation results for individual test cases
- Identify recurring failure patterns
- Inspect evaluation runs and response details
- Track regressions when prompts or application behavior change
- Provide visibility into response latency and evaluation outcomes

## Python SDK

Eval Workbench includes a Python SDK for running evaluation suites from your own application and sending execution results, traces, and spans back to the workbench.

```
pip install -e sdk/python     # from this repository
pip install https://eval-workbench-5lofnwh6hq-uc.a.run.app/sdk/eval_workbench-0.1.0-py3-none-any.whl   # or from the hosted Workbench
```

```python
from eval_workbench import Client, trace, span

client = Client(base_url="http://127.0.0.1:8000", api_key="ewb_...")   # or EVAL_WORKBENCH_URL / EVAL_WORKBENCH_API_KEY

@trace(name="llm.generate", kind="llm")
def my_app(text):
    ...                                                                 # call your application

result = client.run_suite("my-suite", my_app, version="v1.1", model="gpt-4o-mini", note="what changed")
print(result.url)
```

The SDK runs each test case through your function in your own process, times it, records nested spans, uploads the outputs, and the backend scores them. Errors in your function become execution errors. Tests: `cd sdk/python && python -m pytest`.


## Repository

- `frontend/` the web app (single file, no build step) `admin.html`, the operator page for access requests, and `privacy.html`, the privacy notice
- `backend/` FastAPI + SQLite service: API keys, write API, server-side scoring, seed command, tests
- `sdk/python/` Python client with `run_suite`, `@trace` and `span()`
- `examples/` example applications that use the SDK
- `data/sample-data.json` sample suites and run history, used to seed the backend
- `templates/` CSV and JSON templates for importing a suite
- `CLAUDE.md` project context for Claude Code
