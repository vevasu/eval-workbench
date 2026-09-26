# Build plan

Goal of this stage: let any application connect to the Workbench the way it would connect to LangSmith or Arize. The application sends data to the Workbench; the Workbench never calls into the application.

Work through the phases in order. Each phase ends with its acceptance checks passing and the existing UI still working. Don't start the next phase until then.

## Phase 0: Project setup

- Initialise git. Add `.gitignore` (Python, Node, `.env`, `*.db`).
- Target structure:
  ```
  frontend/        existing UI (index.html)
  backend/         FastAPI service
  sdk/python/      Python client package
  examples/        example applications that use the SDK
  data/            sample data for seeding
  templates/       import templates
  docs/
  ```
- Add a short README with how to run each part.

Done when: the frontend opens from `frontend/index.html` exactly as before.

## Phase 1: Backend foundation

- FastAPI, SQLModel (or SQLAlchemy) with SQLite for now. Keep the database layer swappable so Postgres can replace SQLite later.
- Tables mirroring the data model in `CLAUDE.md`: projects, suites, test_cases, runs, results, spans. Store checks, span attrs and evaluator details as JSON columns.
- A seed command that loads `data/sample-data.json` into a demo project.
- Read endpoints: list and get suites, cases, runs, results, and one execution with its spans.

Done when: the seed command runs, and the read endpoints return the sample data with the same field names as the JSON file.

## Phase 2: Projects and API keys

- A project owns its suites and runs. Every query is scoped to a project.
- API keys: generate, list (showing only a prefix), revoke. Store only a hash. Accept the key in `Authorization: Bearer <key>`.
- No user accounts yet. A single admin key from `.env` can create projects and keys.

Done when: requests without a valid key get 401, and one project can't read another project's data.

## Phase 3: Write API and server-side scoring

- Endpoints to create and edit suites and test cases, and to import a suite from the CSV or JSON template format.
- Run lifecycle: `POST /runs` (suite, version, model, note) returns a run ID and the test cases; `POST /runs/{id}/results` accepts a batch of `{caseId, actual, latencyMs, timestamp, spans, error}`; `POST /runs/{id}/complete`.
- Port the Evaluators module and the scoring rules to Python. The backend scores every uploaded output, so verdicts are consistent whichever client sent them.
- Write tests that score the sample data outputs in Python and match the verdicts and categories stored in `sample-data.json`.
- Summary and comparison endpoints that mirror `summarize()` and `compareRuns()`.

Done when: the Python scorer matches every stored verdict and category in the sample data, and a run created and completed through the API shows the right summary.

## Phase 4: Python SDK

- Package in `sdk/python`, configured with the base URL and API key (arguments or environment variables).
- `client.run_suite(suite_id, fn, version=..., model=..., note=...)`: creates the run, calls `fn(input)` for each case in the user's own process, times it, uploads results in batches, completes the run, returns the summary and a link to the results page.
- Tracing: a `@trace` decorator and a `span("name", kind=...)` context manager that record nested spans for the current execution and attach them to the uploaded result.
- Handle errors in `fn` as execution errors, not crashes. Retry uploads on network failures.

Done when: a script of under 15 lines runs a suite against a local function and the run appears in the API.

## Phase 5: Example application

- In `examples/`, a small rewards support assistant that calls a real model with the user's own key from `.env`, using the rewards suite's system prompt and reference data from the sample data.
- A script that runs the rewards suite against it through the SDK, with LLM and prompt steps traced.

Done when: running the example produces a new run of the rewards suite with real outputs, latency and spans.

## Phase 6: Frontend on the API

- Add an API client in the Store module. Keep localStorage as a demo mode, used when no API is configured.
- A small settings screen for the API base URL and key, kept in the browser.
- Every page reads from the API in API mode. The Run evaluation page shows how to run a suite from code (SDK snippet) alongside the existing simulated option.
- Serve the frontend from the backend so one command runs everything.

Done when: every page shows the same data in API mode as in demo mode for the seeded project, and runs created by the SDK example appear on the dashboard, in comparisons and in trace views.

## Phase 7: CI integration

- A CLI in the SDK: `workbench run --suite <id> --entry module:function --version <v> --fail-on-regression`.
- Exit with a non-zero code when the new run has regressions against the previous run, or when the pass rate drops below a threshold.
- An example GitHub Actions workflow.

Done when: the CLI fails on a run with a regression and passes on a clean one.

## Later, not in this stage

- Trace ingestion in OpenTelemetry / OpenInference format for production traffic.
- LLM-as-a-judge evaluators, registered in the evaluator registry.
- Human review queue for Review results.
- Token and cost tracking on spans.
- Dataset versioning and experiment comparison.
- Alerts on regressions and SLA breaches.
- User accounts, hosting and deployment for the public version.
