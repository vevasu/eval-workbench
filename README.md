# Eval Workbench

Evaluate, debug and monitor the quality of AI applications: evaluation suites, execution telemetry, failure analysis and run comparison.

## Frontend

Open `frontend/index.html` in a browser, or serve it:

```
cd frontend
python -m http.server 8000
```

Then open http://localhost:8000. Sample data loads on first visit and is saved in the browser. This mode does not need the backend.

## Backend

```
cd backend
pip install -r requirements.txt
python -m app.seed        # loads data/sample-data.json into a demo project (workbench.db)
python -m uvicorn app.main:app --reload
```

The API serves at http://127.0.0.1:8000, with read endpoints for suites, cases, runs and results (see `docs/BUILD_PLAN.md` for what's implemented at each phase). The frontend does not read from it yet; that's Phase 6.

## Repository

- `frontend/` the web app (single file, no build step)
- `backend/` FastAPI + SQLite service (`app/models.py`, `app/routers/`, `app/seed.py`)
- `sdk/python/` Python client package (added from Phase 4)
- `examples/` example applications that use the SDK (added from Phase 5)
- `data/sample-data.json` sample suites and run history, used to seed the backend
- `templates/` CSV and JSON templates for importing a suite
- `docs/BUILD_PLAN.md` the plan for the backend, SDK and integrations
- `CLAUDE.md` project context for Claude Code
