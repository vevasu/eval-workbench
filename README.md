# Eval Workbench

Evaluate, debug and monitor the quality of AI applications: evaluation suites, execution telemetry, failure analysis and run comparison.

Your application sends data to the Workbench, the way it would to LangSmith or Arize. The Workbench never calls into your application.

## Frontend on its own (demo mode)

Open `frontend/index.html` in a browser, or serve it:

```
cd frontend
python -m http.server 8000
```

Sample data loads on first visit and is saved in the browser. This mode does not need the backend.

## Backend and web app together

```
cd backend
pip install -r requirements.txt
copy .env.example .env          # set EVAL_WORKBENCH_ADMIN_KEY to a long random string
python -m app.seed              # loads data/sample-data.json into a demo project, prints a demo API key once
python -m uvicorn app.main:app  # API and web app at http://127.0.0.1:8000
```

Open http://127.0.0.1:8000, choose **Connect to API** in the sidebar, and paste the key. Every page then reads live data from the API. In this mode the app is read-only; suites and runs come from the API or SDK.

- Docs for the API: http://127.0.0.1:8000/docs
- Create more projects and keys with `POST /admin/projects` and `POST /admin/projects/{id}/keys`, using `Authorization: Bearer <admin key>`. Keys are stored as hashes and shown once.
- Tests: `cd backend && pip install pytest && python -m pytest`

## Public demo and private beta

Live at https://eval-workbench-5lofnwh6hq-uc.a.run.app (Google Cloud Run, Neon Postgres). Visitors see the sample data, a **Get started** guide, and can request access. You approve requests at `/admin.html` or with `python -m app.manage approve <id>`, which creates their project and API key. See `docs/BETA.md` for the operator guide, deployment, configuration and limits.

## Python SDK

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

## Example applications

- `examples/story-generator`: a small OpenAI-backed story writer (80 words or fewer) with an eval suite and live tracing. See its README.
- `examples/writer-critic`: a multi-agent app (Planner, Writer, Critic, Editor) with a critique-and-revise loop, a live web UI, and optional tracing with one span per agent. See its README.

## Repository

- `frontend/` the web app (single file, no build step) and `admin.html`, the operator page for access requests
- `backend/` FastAPI + SQLite service: API keys, write API, server-side scoring, seed command, tests
- `sdk/python/` Python client with `run_suite`, `@trace` and `span()`
- `examples/` example applications that use the SDK
- `data/sample-data.json` sample suites and run history, used to seed the backend
- `templates/` CSV and JSON templates for importing a suite
- `docs/BUILD_PLAN.md` the plan for the backend, SDK and integrations (phases 0 to 6 are built; CI integration is next)
- `CLAUDE.md` project context for Claude Code
