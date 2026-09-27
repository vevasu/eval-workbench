# Story generator

Type a story idea, pick a genre, get a story of 80 words or fewer from the OpenAI API. It is also the example application for the Eval Workbench SDK. Run it locally with your key in `.env`, or put it online where visitors enter their own key (see below).

## Run the app

```
pip install fastapi uvicorn
copy .env.example .env      # put your OpenAI key in .env
python -m uvicorn app:app --port 8100
```

Open http://127.0.0.1:8100. The key stays on the server in `.env`. The 80-word limit is set in the prompt and enforced by trimming the reply (`limit_words` in `story.py`).

## Live tracing

If `EVAL_WORKBENCH_URL` and `EVAL_WORKBENCH_API_KEY` are in `.env`, every story made through the app is sent to the Workbench in the background (`client.observe` in `app.py`) and appears on the **Production** page under "Story generator (live)". Each one is scored by two guardrail checks: not cut off, and 80 words or fewer. Stories from one browser tab share a session, the genre is sent as a tag, and token counts and cost (from `PRICES` in `story.py`) come from the OpenAI call's span. Set `APP_VERSION` in `.env` when you change the prompt or model, so the Production page can show whether the new version fails more. If the Workbench is down, the app carries on normally.

`OPENAI_BASE_URL` points the app at any OpenAI-compatible API instead of OpenAI (Azure, OpenRouter, a local model server).

## Put it online (Google Cloud Run)

Visitors enter their own OpenAI key on the page. The key is sent with each request, used for that one OpenAI call, and never stored, logged or sent to the Workbench; the browser keeps it only if the visitor ticks **Remember on this device**. When the server has `OPENAI_API_KEY` set (as when you run it locally with `.env`), the key field is hidden and the server's key is used, so never set it on a public deployment.

Every story is sent to Eval Workbench, so the deployed app shows up on the Workbench's **Production** page. On Cloud Run the app waits for the trace upload (at most 5 seconds) before replying, because Cloud Run pauses the CPU once a response is sent.

One-time setup, from the repository root (Windows `cmd` shown):

1. Deploy the Workbench first, so it serves SDK 0.2.0 (the container installs the SDK from it): `gcloud run deploy eval-workbench --source . --region us-central1`
2. Create a Workbench project and key for the app, with your admin key:
   ```
   curl -X POST https://eval-workbench-5lofnwh6hq-uc.a.run.app/admin/projects -H "Authorization: Bearer ADMIN_KEY" -H "Content-Type: application/json" -d "{\"name\":\"Story generator\",\"id\":\"story-generator\"}"
   curl -X POST https://eval-workbench-5lofnwh6hq-uc.a.run.app/admin/projects/story-generator/keys -H "Authorization: Bearer ADMIN_KEY" -H "Content-Type: application/json" -d "{\"name\":\"cloud run\"}"
   ```
   The second command prints the key (`ewb_...`) once.
3. Store it in Secret Manager and let Cloud Run read it (find PROJECT_NUMBER with `gcloud projects describe YOUR_PROJECT_ID`):
   ```
   echo|set /p="ewb_..." | gcloud secrets create story-workbench-key --data-file=-
   gcloud secrets add-iam-policy-binding story-workbench-key --member=serviceAccount:PROJECT_NUMBER-compute@developer.gserviceaccount.com --role=roles/secretmanager.secretAccessor
   ```
4. Deploy the app:
   ```
   gcloud run deploy story-generator --source examples/story-generator --region us-central1 --allow-unauthenticated --set-env-vars EVAL_WORKBENCH_URL=https://eval-workbench-5lofnwh6hq-uc.a.run.app,APP_VERSION=v1 --set-secrets EVAL_WORKBENCH_API_KEY=story-workbench-key:latest
   ```

The command prints the app's address. To see its traffic, open the Workbench, choose **I have a key**, paste the key from step 2 and open **Production**. After changing the prompt or model, deploy again with a new `APP_VERSION` (for example `--update-env-vars APP_VERSION=v2`), and the Production page compares the two versions.

`.gcloudignore` keeps your local `.env` out of the upload.

## Evaluate and trace it with Eval Workbench

1. Start the Workbench backend (see the repository README) and install the SDK: `pip install -e ../../sdk/python`, or from a hosted Workbench as shown on its **Get started** page.
2. Put `EVAL_WORKBENCH_URL` and `EVAL_WORKBENCH_API_KEY` in `.env`.
3. Run the suite:

```
python run_evals.py --version v1 --note "Baseline prompt"
```

`suite.json` has 8 cases: on-topic checks, a prompt-injection length test, a no-dialogue constraint, and one case for human review. The first run creates the suite in the Workbench. Every run uploads the outputs, latency and spans (`prompt.build`, `llm.generate`, the OpenAI call with token counts, and `word_limit`), then prints a link to the results.

The check "Must not include …" catches stories the word limiter had to cut off, so a model that writes too long shows up as an Incomplete answer, and the `word_limit` span shows by how much.
