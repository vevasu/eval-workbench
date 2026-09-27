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
- `sdk/python/` is the client (`Client.run_suite`, `@trace`, `span`, `observe`). The example apps (`examples/`, including the story generator that is deployed as its own Cloud Run service) were removed from this repository to keep it to the Workbench; their last version is at commit `eed0ed6` (`git checkout eed0ed6 -- examples`).
- The frontend has two modes. Demo mode uses localStorage as above. API mode is chosen in the sidebar (URL and key kept in `localStorage` under `eval-workbench.api.v1`) and loads `GET /state` into the same `Store.state` shape, so all views are unchanged; suites, cases and runs are created, edited and deleted through the API there (`apiWrite()`, then `Api.refresh()`), and only `API_WRITE_ACTIONS` (starting a simulated run, restoring sample data) stay demo-only. Simulated, recorded and live-model runs exist only in demo mode.
- Production monitoring: live traffic sent with `client.observe()` (`POST /ingest`) is stored as runs with target `production`, one per version and model. `GET /state` leaves these out; the Production page and the Traces page's Production tab read them through the `Prod` module (demo: computed from localStorage; API: `/production/stats`, `/production/traces`, refreshed in the background). The demo seed includes three weeks of traffic to the story generator (runs `DS-R6` and `DS-R7`) where v1.4 fails more than v1.3.
- Private beta support: public `POST /access-requests`, operator approval (`python -m app.manage`), per-project allowances and size limits (`app/limits.py`, `app/settings.py`), rate limits (`app/ratelimit.py`), and `EVAL_WORKBENCH_ENV=production`. See `docs/BETA.md`. The demo-mode banner, request form and **Get started** page (`#/start`, integration guide) are in the frontend; `frontend/admin.html` is the operator page for approving requests; `frontend/privacy.html` is the privacy notice (keep it accurate when data handling changes).
- Deployed on Google Cloud Run (`eval-workbench`, us-central1, Neon Postgres): https://eval-workbench-5lofnwh6hq-uc.a.run.app. The Docker build serves the SDK wheel at `/sdk/`; keep `SDK_VERSION` in `index.html` and the wheel name in `app/manage.py` in step with `sdk/python`. See `docs/BETA.md`.
- Schema changes go through Alembic migrations (`backend/migrations`, applied on startup by `app/migrate.py`). Never rely on `create_all` to change an existing table. See `docs/BETA.md`.
- Human review: `#/review` lists results waiting for a person (verdict Review), spot checks of passing production requests and past decisions; `Reviews` in the frontend and `app/routers/reviews.py` in the backend. The demo seed includes reviews by "Priya" (test runs DS-R1 to DS-R3) and "Sam" (spot checks).
- AI judge and checks on live traffic: an `llm_judge` check asks a model (the project's own OpenAI key, saved encrypted by `app/keystore.py`) whether an answer meets its criteria (`app/judge.py`). Each suite can have `liveChecks`, set on the Production page, that run on every production request after the app's own checks. Test runs are judged during upload; production requests are judged in a background thread.
- Built so far: phases 0 to 8b of `docs/BUILD_PLAN.md`. Phase 9 (CI integration) is next.

## How to work on this project

- Build one capability at a time. Finish it, test it, then move on.
- Never replace working functionality when adding a feature. Keep the existing architecture and UI unless a change is genuinely necessary, and say why when it is.
- Don't overbuild future capabilities. Leave clean extension points instead.
- After every change, check that every page still renders (in demo mode and API mode) and that the drill-down paths still work: dashboard, suite, test case, execution trace, failure reason; Production, failure reason, request, Add to test suite, test case; and Review queue, item, Save and next.
- Keep sample data realistic, so the product can be demonstrated at any point.

## Frontend architecture

The script in `frontend/index.html` is split into modules, each marked by a `/* ---------------- Name ---------------- */` comment.

| Module | Responsibility | Future extension point |
|---|---|---|
| Util | Formatting, seeded PRNG, helpers | |
| Taxonomy | `CATEGORIES` (failure categories), `REVIEW_REASONS` | Custom taxonomies per project |
| Evaluators | Registry of check types. Each has `label`, default `category`, `describe(check)` and `run(output, check)`. `evaluate()` runs them and `decide()` turns results into a verdict (used again after an AI judge answers) | Custom evaluators register here |
| Telemetry | `buildSpans()` builds the span tree for each execution | Agent and tool-call traces, tokens and cost on spans |
| Targets | Adapters that produce an output for a test case: `simulated`, `recorded`, `live` (Claude, only inside claude.ai) | HTTP endpoint target, provider targets with the user's own key |
| Run execution | `executeRun(suite, cfg, onProgress)` runs every case, evaluates it, records telemetry | Moves to the SDK and backend |
| Analytics | `summarize()`, `compareRuns()`, regressions, fixes, latency regressions, `liveStats()` for production windows | Automatic regression detection, alerts |
| Store | `load`, `save`, `reset` against localStorage, and the `Api` client | Replace with an API client (keep localStorage as a demo mode) |
| Production data | `Prod.stats()`, `traces()`, `trace()`: `{ data }`, `{ pending }` or `{ error }`, from localStorage in demo mode or `/production` in API mode | Alerts on failure-rate changes, OpenTelemetry ingestion |
| Human review | `Reviews.queue()`, `target()`, `save()`; `applyReview()`, `isSpotCheck()` | Review assignments, agreement between reviewers |
| Seed data | `SEED_SUITES` and `buildSeed()` | |
| Charts | Hand-written SVG line chart, bar lists, pass/fail/review bar | |
| Views | One render function per page, hash router `route()`, delegated events | |

Pages and routes: `#/dashboard`, `#/production?suite&version&w&metric`, `#/start`, `#/suites`, `#/suites/:id`, `#/run`, `#/cases`, `#/cases/:suiteId/:caseId`, `#/results`, `#/results/:runId`, `#/compare?suite&a&b`, `#/traces?src=live|runs` (production requests by default), `#/trace/:runId/:caseId` (a test execution, or a production request when the run's target is `production`), `#/review?kind=pending|spot|done&suite&source&reason`, `#/review/:runId/:caseId` (decide one result; the queue filters ride along for Save and next). Filters live in the URL query string.

Notes:
- The `live` target and the Claude `downloads` capability only work when the page is published inside claude.ai. Outside claude.ai, `window.claude` doesn't exist, so the live target is disabled and downloads use a normal browser download. Don't remove this code; it's harmless.
- Published at https://claude.ai/artifact/RsA9KvD5ebHFfp68adwPLf (the claude.ai version).

## Data model

This is the shape the backend should mirror. Field names are the ones used in `sample-data.json`.

**Suite**: `id`, `prefix` (for case and run IDs, such as `RW`), `name`, `description`, `pipeline` (`chat`, `tools` or `rag`), `slaMs`, `systemPrompt`, `context` (reference data), `createdAt`, optional `liveChecks[]` (run on every production request), `cases[]`.

**Test case**: `id` (such as `RW-006`), `input`, `expected` (human-readable expected behaviour), `tag`, `checks[]`, optional `recorded` and `recordedLatencyMs` (actual output uploaded for offline scoring), optional `origin` (`<runId>/<caseId>` of the production request it was created from), optional `sim` and `hard` (simulator only; not part of the real product).

**Check**: `type` plus type-specific fields, and an optional `category` override for its failure category.
- `contains_all` with `values[]`. Partly met sends the case to review.
- `contains_any` with `values[]`
- `not_contains` with `values[]`
- `regex` with `pattern`, `flags`
- `json_keys` with `keys[]`, optional `strict`
- `max_length` with `max`
- `human` with `rubric`. Always sends the case to review.
- `llm_judge` with `criteria`, optional `sample` (percent of production requests to judge). A model decides pass or fail with a reason; until it answers the check is `pending`.

**Run**: `id` (such as `RW-R5`), `suiteId`, `version`, `model`, `target` (`simulated`, `recorded`, `live`, `sdk`, or `production` for live traffic), `note` (what changed), `startedAt`, `finishedAt`, `slaMs`, `results[]`.

**Result (one execution)**: `caseId`, `input`, `expected`, `actual`, `verdict` (`Pass`, `Fail` or `Review`), `category`, `reason`, `checks[]` (each with `pass`, `partial`, `manual`, `detail`), `latencyMs`, `timestamp`, `model`, `version`, `spans[]`. Optional `review` when a person decided it: `{ verdict, category, note, reviewer, reviewedAt, autoVerdict, autoCategory }`. Production requests (case IDs such as `LIVE-00042`) also have `userId`, `sessionId`, `tags[]`, `metadata{}`, and `tokensIn`, `tokensOut`, `costUsd` summed from span attributes (`spanTotals()` / `span_totals()`).

**Span**: `name`, `kind` (`root`, `llm`, `tool`, `retrieval`, `other`), `start` and `dur` in ms relative to the request, `depth`, `attrs`.

## Scoring rules

These must behave identically wherever scoring happens (frontend today, backend later).

1. Execution error: Fail, category `Execution error`.
2. Any check fails outright: Fail. The category comes from the first failed check (its override, or the evaluator default). If the output looks like a refusal and the case doesn't expect one, the category becomes `Unwarranted refusal`, unless it's `Policy violation`.
3. Otherwise, a partly met `contains_all`: Review, category `Partial match`.
4. Otherwise, an AI judge that hasn't answered yet: Review, category `Awaiting AI judge`. (A judge is skipped, `skipped: true`, when rule 2 or 3 already decided; once it answers, its pass or fail counts like any other check. If it can't run, it becomes a manual check.)
5. Otherwise, a `human` check: Review, category `Awaiting human review`.
6. Otherwise, latency over the suite SLA: Fail, category `Latency SLA breach`.
7. Otherwise: Pass.

A production request whose input is the same as a test case's (any suite in the project; capitals and extra spaces don't matter, `same_input()`) is also checked by that test case's checks, after the app's own and before the suite's live checks. Those check results carry `fromCase` (`<suiteId>/<caseId>`) and the result takes the case's `expected`, so a suite that is changed and imported applies to the next live request.

Production traffic follows the same rules, except that a request sent without any checks skips the "no checks: Review" rule: it is judged on errors and latency only (steps 1, 6 and 7), so live traffic doesn't flood review.

A person's review overrides all of the above: `verdict` and `category` become the reviewer's (Pass, or Fail with a category), and the automatic ones are kept in `review.autoVerdict` and `review.autoCategory`. Undo puts them back. Spot checks are production requests with verdict Pass whose id number is a multiple of 20 (`isSpotCheck()` / `is_spot_check()`).

Pass rate is Pass divided by all results. Review is not a pass.

Production windows are `(from, to]`, cut into equal buckets from `from`; changes compare against the window of the same length before it. `liveStats()` in the frontend and `live_stats()` in `app/live.py` must give identical results.

Comparison between a baseline and a candidate run: a regression is Pass to Fail; degraded is Pass to Review; a fix is anything to Pass; still failing is Fail to Fail; a latency regression is at least 30% and 300 ms slower.

## UI conventions

- Enterprise style: navy sidebar, cool light background, Hanken Grotesk for text, JetBrains Mono only for IDs, prompts, outputs and traces. Colors are CSS tokens on `:root` with a dark mode.
- Status colors: pass green, fail red, review amber. Keep them consistent everywhere.
- Copy: sentence case, plain verbs, name things by what users understand. Buttons say exactly what happens.
- Every number should link to the level below it where possible (drill-down is a core principle).
- Responsive down to mobile, visible keyboard focus.
