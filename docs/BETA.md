# Running a private beta

The public sees a demo. Anyone can ask for access; you approve by hand; approved people get their own project and an API key. The Workbench never calls a model, so a beta costs you hosting only. Each user's app pays for its own model calls.

## What a visitor sees

Open the site: sample data (a story-generation app tested across five versions), a short explanation, and **Request beta access**. Nothing else is reachable without a key. `/state`, `/suites`, `/runs` and every other data route return 401 without one, and the interactive API docs and the local dev shortcut are off in production.

## Operator workflow

Run these where the backend runs, with the same environment variables as the server (see below).

```
python -m app.manage requests          # pending access requests
python -m app.manage approve 3         # creates a project and prints its API key once, plus setup steps to email
python -m app.manage reject 3
python -m app.manage projects          # every project with usage against its allowance
python -m app.manage newkey <project>  # another key for the same project
python -m app.manage revoke <key id>   # key ids are listed by GET /admin/projects/<project>/keys
python -m app.manage delete-project <project>   # deletes the project and all its data; asks you to type its id
python -m app.manage delete-request 3  # deletes a pending or rejected request and the email in it
```

Or open `<your Workbench address>/admin.html`, paste the admin key, and approve or reject requests in the browser. It shows the message to send, with the key, once.

The same actions exist as admin API calls (`/admin/access-requests`, `/admin/projects/...`) using `Authorization: Bearer <admin key>`.

Keys are stored as hashes. If someone loses theirs, revoke it and issue a new one.

## Privacy notice

`frontend/privacy.html` (served at `/privacy.html`) says what is collected, who processes it (Google Cloud, Neon, Google Fonts) and how to delete it. It is linked from the access request form and the sidebar. The contact address is productlab.support@gmail.com. Update the page and its date whenever you add a processor or start collecting something new. It was written for the beta and has not been reviewed by a lawyer.

## Deleting data

Users can delete their own project at any time: in the web app, **Settings**, then **Delete my project** (they type the project id to confirm), or `client.delete_project("<project id>")` in the SDK, or `DELETE /project?confirm=<project id>` with their key. This removes every suite, case, run, result and trace, all the project's keys, and the access request with their email. If someone asks you by email instead, run `delete-project` (or `DELETE /admin/projects/<project>`). For someone who was never approved, `delete-request` removes their email.

## Configuration

| Variable | Purpose | Default |
|---|---|---|
| `EVAL_WORKBENCH_ENV` | `production` turns off `/docs` and `/dev-connect`, and refuses to start without an admin key | development |
| `EVAL_WORKBENCH_ADMIN_KEY` | Operator key for `/admin/...` (long and random) | none |
| `DATABASE_URL` | Any SQLAlchemy URL. Use Postgres in production. | local SQLite file |
| `TRUST_PROXY` | Set to `1` behind a load balancer so rate limits use the real client IP | off |
| `MAX_RESULTS_PER_PROJECT` | Stored executions per project | 10000 |
| `MAX_SUITES_PER_PROJECT` | Suites per project | 50 |
| `MAX_TEXT_CHARS` | Longest single input or output | 20000 |
| `MAX_SPANS_PER_EXECUTION` | Spans per trace | 200 |
| `MAX_RESULTS_PER_BATCH` | Results per upload | 100 |
| `RATE_LIMIT_INGEST_PER_MIN` | Uploads per project per minute | 120 |
| `RATE_LIMIT_ACCESS_REQUESTS_PER_HOUR` | Access requests per network address | 5 |

Never set `EVAL_WORKBENCH_DEV_KEY` on a shared or public server.

## Deploying

The `Dockerfile` in the repository root builds one image that serves the API and the web app. Build context is the repository root. On the host, set `EVAL_WORKBENCH_ADMIN_KEY`, `DATABASE_URL` (Postgres with persistent storage), `TRUST_PROXY=1`, and put HTTPS in front of it (most hosts do this for you). The image reads `PORT` if the host sets it.

### Current deployment

Live on Google Cloud Run: service `eval-workbench`, region `us-central1`, at https://eval-workbench-5lofnwh6hq-uc.a.run.app. The database is Neon Postgres. `DATABASE_URL` and `EVAL_WORKBENCH_ADMIN_KEY` come from Secret Manager (secrets `eval-workbench-db` and `eval-workbench-admin`); `EVAL_WORKBENCH_ENV=production` and `TRUST_PROXY=1` are plain environment variables. To redeploy from the repository root:

```
gcloud run deploy eval-workbench --source . --region us-central1
```

The image build also packages `sdk/python` as a wheel and serves it at `/sdk/`, which is where beta users install the SDK from. When you change the SDK version, update `SDK_VERSION` in `frontend/index.html` and the wheel name in `backend/app/manage.py` too.

## Backups and restoring

The database relies on Neon's built-in point-in-time restore: Neon keeps a history of every change for a restore window set by your plan (short on the free plan, longer on paid plans). Check it in the Neon console under **Settings**, then **Storage** (history retention), and raise it if the window is shorter than the time you'd take to notice a problem.

To restore after a bad change or accidental deletion:

1. In the Neon console, open the project, then **Branches**, then **Restore** on the main branch, and pick a time just before the problem. Neon keeps the pre-restore state as a backup branch, so a restore can itself be undone.
2. If the connection string changed (for example, you restored into a new branch instead), update the secret and redeploy:
   ```
   gcloud secrets versions add eval-workbench-db --data-file=<file with the new DATABASE_URL>
   gcloud run deploy eval-workbench --source . --region us-central1
   ```
3. Open the site with a beta key and check the data is back.

A restore rolls back the whole database, including access requests and projects created after that time. Anything newer is lost, so tell affected users.

Before a risky change (a schema migration, a bulk delete), take a manual snapshot first: in Neon, create a branch from the main branch named after the date and change. It costs nothing until it diverges, and you can delete it once you are sure.

## What beta users do

1. You send them the key and your Workbench address (`approve` prints the message).
2. They install the SDK from your site (`pip install <your Workbench address>/sdk/eval_workbench-0.1.0-py3-none-any.whl`; the **Get started** page shows the exact command) and set `EVAL_WORKBENCH_URL` and `EVAL_WORKBENCH_API_KEY`.
3. They run a suite with `client.run_suite(...)` or send live traffic with `client.observe(...)`.
4. They open your site, choose **I have a key**, paste it, and see only their own project.

## Before you charge anyone

Still to build: self-serve signup, per-plan quotas and billing, automatic retention limits, terms of service, database migrations, and pagination for large histories. The current allowances are flat beta limits, not plans.
