# Story generator

Type a story idea, pick a genre, get a story of 80 words or fewer from the OpenAI API. It is also the example application for the Eval Workbench SDK.

## Run the app

```
pip install fastapi uvicorn
copy .env.example .env      # put your OpenAI key in .env
python -m uvicorn app:app --port 8100
```

Open http://127.0.0.1:8100. The key stays on the server in `.env`. The 80-word limit is set in the prompt and enforced by trimming the reply (`limit_words` in `story.py`).

## Live tracing

If `EVAL_WORKBENCH_URL` and `EVAL_WORKBENCH_API_KEY` are in `.env`, every story made through the app is sent to the Workbench in the background (`client.observe` in `app.py`) and appears under the suite "Story generator (live)". Each one is scored by two guardrail checks: not cut off, and 80 words or fewer. If the Workbench is down, the app carries on normally.

## Evaluate and trace it with Eval Workbench

1. Start the Workbench backend (see the repository README) and install the SDK: `pip install -e ../../sdk/python`, or from a hosted Workbench as shown on its **Get started** page.
2. Put `EVAL_WORKBENCH_URL` and `EVAL_WORKBENCH_API_KEY` in `.env`.
3. Run the suite:

```
python run_evals.py --version v1 --note "Baseline prompt"
```

`suite.json` has 8 cases: on-topic checks, a prompt-injection length test, a no-dialogue constraint, and one case for human review. The first run creates the suite in the Workbench. Every run uploads the outputs, latency and spans (`prompt.build`, `llm.generate`, the OpenAI call with token counts, and `word_limit`), then prints a link to the results.

The check "Must not include …" catches stories the word limiter had to cut off, so a model that writes too long shows up as an Incomplete answer, and the `word_limit` span shows by how much.
