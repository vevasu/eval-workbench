# Eval Workbench

An AI evaluation and quality workbench for teams building LLM applications. It evaluates, debugs and monitors the quality of AI systems. It does not just run test cases.

The product answers one question: **is my AI system getting better, where is it failing, and why?** Every feature should help answer part of that question. Features that only display pass or fail don't meet the bar.

Long term goal: a public, bring-your-own-key product in the same space as LangSmith and Arize, focused on the evals slice.

## Current state

- `frontend/index.html` is a working MVP. It is one self-contained file (HTML, CSS and vanilla JS, no build step, no framework) and runs in any browser. Open it directly or serve the folder with `python -m http.server`.
- All data lives in browser `localStorage` under the key `eval-workbench.state.v1`. On first load it generates realistic sample data: one story-generation demo suite ("Demo: Story generator", 10 cases, 5 runs, 50 executions). No LLM calls are involved; the simulator replays hand-written outputs.
- `data/sample-data.json` is the same sample data exported as JSON (generate it by running `buildSeed()` in the page). Use it to seed the backend. `python -m app.seed` only replaces the sample suites and never touches other data in the project.
- `templates/` holds the CSV and JSON import templates. The same templates can be downloaded from the Import suite dialog.
- `backend/` is a FastAPI + SQLModel (SQLite) service: projects and hashed API keys, write API, server-side scoring in `app/scoring.py` (a port of the Evaluators module, tested against every result in `sample-data.json`), and `GET /state`, which returns everything in the `sample-data.json` shape for the web app. Suites, cases and runs are keyed by `(project_id, id)`. It also serves `frontend/`.
- `sdk/python/` is the client (`Client.run_suite`, `@trace`, `span`). `examples/story-generator` is an OpenAI app evaluated through it.
- The frontend has two modes. Demo mode uses localStorage as above. API mode is chosen in the sidebar (URL and key kept in `localStorage` under `eval-workbench.api.v1`) and loads `GET /state` into the same `Store.state` shape, so all views are unchanged; write actions are blocked there (`API_WRITE_ACTIONS`). Simulated, recorded and live-model runs exist only in demo mode.
- Private beta support: public `POST /access-requests`, operator approval (`python -m app.manage`), per-project allowances and size limits (`app/limits.py`, `app/settings.py`), rate limits (`app/ratelimit.py`), and `EVAL_WORKBENCH_ENV=production`. See `docs/BETA.md`. The demo-mode banner, request form and **Get started** page (`#/start`, integration guide) are in the frontend; `frontend/admin.html` is the operator page for approving requests.
- Deployed on Google Cloud Run (`eval-workbench`, us-central1, Neon Postgres): https://eval-workbench-5lofnwh6hq-uc.a.run.app. The Docker build serves the SDK wheel at `/sdk/`; keep `SDK_VERSION` in `index.html` and the wheel name in `app/manage.py` in step with `sdk/python`. See `docs/BETA.md`.
- Built so far: phases 0 to 6 of `docs/BUILD_PLAN.md`. Phase 7 (CI integration) is next.

## How to work on this project

- Build one capability at a time. Finish it, test it, then move on.
- Never replace working functionality when adding a feature. Keep the existing architecture and UI unless a change is genuinely necessary, and say why when it is.
- Don't overbuild future capabilities. Leave clean extension points instead.
- After every change, check that all seven pages still render and that the drill-down path still works: dashboard, suite, test case, execution trace, failure reason.
- Keep sample data realistic, so the product can be demonstrated at any point.

## Frontend architecture

The script in `frontend/index.html` is split into modules, each marked by a `/* ---------------- Name ---------------- */` comment.

| Module | Responsibility | Future extension point |
|---|---|---|
| Util | Formatting, seeded PRNG, helpers | |
| Taxonomy | `CATEGORIES` (failure categories), `REVIEW_REASONS` | Custom taxonomies per project |
| Evaluators | Registry of check types. Each has `label`, default `category`, `describe(check)` and `run(output, check)` | LLM-as-a-judge and custom evaluators register here |
| Telemetry | `buildSpans()` builds the span tree for each execution | Agent and tool-call traces, tokens and cost on spans |
| Targets | Adapters that produce an output for a test case: `simulated`, `recorded`, `live` (Claude, only inside claude.ai) | HTTP endpoint target, provider targets with the user's own key |
| Run execution | `executeRun(suite, cfg, onProgress)` runs every case, evaluates it, records telemetry | Moves to the SDK and backend |
| Analytics | `summarize()`, `compareRuns()`, regressions, fixes, latency regressions | Automatic regression detection, alerts |
| Store | `load`, `save`, `reset` against localStorage | Replace with an API client (keep localStorage as a demo mode) |
| Seed data | `SEED_SUITES` and `buildSeed()` | |
| Charts | Hand-written SVG line chart, bar lists, pass/fail/review bar | |
| Views | One render function per page, hash router `route()`, delegated events | |

Pages and routes: `#/dashboard`, `#/start`, `#/suites`, `#/suites/:id`, `#/run`, `#/cases`, `#/cases/:suiteId/:caseId`, `#/results`, `#/results/:runId`, `#/compare?suite&a&b`, `#/traces`, `#/trace/:runId/:caseId`. Filters live in the URL query string.

Notes:
- The `live` target and the Claude `downloads` capability only work when the page is published inside claude.ai. Outside claude.ai, `window.claude` doesn't exist, so the live target is disabled and downloads use a normal browser download. Don't remove this code; it's harmless.
- Published at https://claude.ai/artifact/RsA9KvD5ebHFfp68adwPLf (the claude.ai version).

## Data model

This is the shape the backend should mirror. Field names are the ones used in `sample-data.json`.

**Suite**: `id`, `prefix` (for case and run IDs, such as `RW`), `name`, `description`, `pipeline` (`chat`, `tools` or `rag`), `slaMs`, `systemPrompt`, `context` (reference data), `createdAt`, `cases[]`.

**Test case**: `id` (such as `RW-006`), `input`, `expected` (human-readable expected behaviour), `tag`, `checks[]`, optional `recorded` and `recordedLatencyMs` (actual output uploaded for offline scoring), optional `sim` and `hard` (simulator only; not part of the real product).

**Check**: `type` plus type-specific fields, and an optional `category` override for its failure category.
- `contains_all` with `values[]`. Partly met sends the case to review.
- `contains_any` with `values[]`
- `not_contains` with `values[]`
- `regex` with `pattern`, `flags`
- `json_keys` with `keys[]`, optional `strict`
- `max_length` with `max`
- `human` with `rubric`. Always sends the case to review.

**Run**: `id` (such as `RW-R5`), `suiteId`, `version`, `model`, `target`, `note` (what changed), `startedAt`, `finishedAt`, `slaMs`, `results[]`.

**Result (one execution)**: `caseId`, `input`, `expected`, `actual`, `verdict` (`Pass`, `Fail` or `Review`), `category`, `reason`, `checks[]` (each with `pass`, `partial`, `manual`, `detail`), `latencyMs`, `timestamp`, `model`, `version`, `spans[]`.

**Span**: `name`, `kind` (`root`, `llm`, `tool`, `retrieval`, `other`), `start` and `dur` in ms relative to the request, `depth`, `attrs`.

## Scoring rules

These must behave identically wherever scoring happens (frontend today, backend later).

1. Execution error: Fail, category `Execution error`.
2. Any check fails outright: Fail. The category comes from the first failed check (its override, or the evaluator default). If the output looks like a refusal and the case doesn't expect one, the category becomes `Unwarranted refusal`, unless it's `Policy violation`.
3. Otherwise, a partly met `contains_all`: Review, category `Partial match`.
4. Otherwise, a `human` check: Review, category `Awaiting human review`.
5. Otherwise, latency over the suite SLA: Fail, category `Latency SLA breach`.
6. Otherwise: Pass.

Pass rate is Pass divided by all results. Review is not a pass.

Comparison between a baseline and a candidate run: a regression is Pass to Fail; degraded is Pass to Review; a fix is anything to Pass; still failing is Fail to Fail; a latency regression is at least 30% and 300 ms slower.

## UI conventions

- Enterprise style: navy sidebar, cool light background, Hanken Grotesk for text, JetBrains Mono only for IDs, prompts, outputs and traces. Colors are CSS tokens on `:root` with a dark mode.
- Status colors: pass green, fail red, review amber. Keep them consistent everywhere.
- Copy: sentence case, plain verbs, name things by what users understand. Buttons say exactly what happens.
- Every number should link to the level below it where possible (drill-down is a core principle).
- Responsive down to mobile, visible keyboard focus.
