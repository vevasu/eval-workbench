# Writer and Critic: a multi-agent app

Four agents work as a team to turn a brief into a publication-ready post, blog post or email summary.

```
Brief -> Planner -> Writer -> [ Critic -> approved? stop : Writer revises ] x up to 2 -> Editor -> Final
```

| Agent | Job | Temperature |
|---|---|---|
| Planner | Turns the brief into an outline | 0.5 |
| Writer | Writes the first draft, then revises it using the Critic's feedback | 0.9 |
| Critic | Scores the draft 1-5 on five dimensions and lists issues, as JSON | 0.2 |
| Editor | Final polish against your editing criteria | 0.2 |

The loop stops when the Critic's average score reaches `APPROVE_SCORE` (default 4.0) or after `MAX_REVISION_ROUNDS` (default 2). No agent framework and no SDK: `writer_critic/llm.py` makes plain HTTPS calls to OpenAI or Anthropic.

## Set up

```
cd examples/writer-critic
pip install -r requirements.txt
copy .env.example .env        # then set OPENAI_API_KEY or ANTHROPIC_API_KEY in .env
```

## Run

Web app, with a live timeline of each agent's work:

```
python -m uvicorn app:app --port 8200
```

Open http://127.0.0.1:8200.

Command line:

```
python cli.py --topic "Why small code reviews beat big ones" --audience "engineering managers" ^
  --points "big reviews get rubber-stamped; small ones ship faster" --format "LinkedIn post"
```

If it won't start: run the command from inside `examples/writer-critic` (from the repository root you get "Could not import module app"), and if you see "only one usage of each socket address", something is already using port 8200, so pick another with `--port 8201`.

Tests (use a scripted fake model, so no API calls): `pip install pytest`, then `python -m pytest`.

## Code map

| File | What it holds |
|---|---|
| `writer_critic/prompts.py` | One system prompt per agent, and the default editing criteria |
| `writer_critic/agents.py` | `Agent` base class and `Planner`, `Writer`, `Critic`, `Editor` |
| `writer_critic/pipeline.py` | The orchestrator: who runs next, and the critique loop |
| `writer_critic/models.py` | Data passed between agents (`Brief`, `Review`, `Step`, `Result`) |
| `writer_critic/llm.py` | The only file that talks to a provider |
| `app.py`, `static/index.html`, `cli.py` | Web and command-line front ends |

To add an agent (say a fact-checker), subclass `Agent` in `agents.py`, add its prompt to `prompts.py`, and call it from `Pipeline.run`.

## Tracing with Eval Workbench (optional)

Install the SDK (`pip install -e ../../sdk/python`, or from a hosted Workbench as shown on its **Get started** page) and set `EVAL_WORKBENCH_URL` and `EVAL_WORKBENCH_API_KEY` in `.env`. Each run is then sent to the Workbench as a trace, with one span per agent and one per model call, under **Writer & Critic (live)**. It is scored by a guardrail check: the final text must not contain buzzwords such as "leverage" or "synergy". Without the SDK or keys, the app runs normally.
