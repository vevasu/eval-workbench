"""Command-line front end. Watch the agents work:

    python cli.py --topic "Why small code reviews beat big ones" --audience "engineering managers" \
        --points "big reviews get rubber-stamped; small ones ship faster" --format "LinkedIn post"
"""
import argparse
import sys

from writer_critic import config, observability
from writer_critic.llm import LLM, LLMError
from writer_critic.models import Brief
from writer_critic.pipeline import Pipeline
from writer_critic.prompts import DEFAULT_CRITERIA


def ask(label: str, value, default: str) -> str:
    if value:
        return value
    if not sys.stdin.isatty():  # no keyboard (script or CI): use the default
        return default
    return input(f"{label} [{default}]: ").strip() or default


def show(event: dict) -> None:
    if event["type"] == "start":
        print(f"  -> {event['label']}...", flush=True)
    elif event["type"] == "step" and event["step"].get("review"):
        r = event["step"]["review"]
        print(f"     critic average {r['average']}/5 ({r['verdict']}); issues: {len(r['issues'])}", flush=True)


def main() -> None:
    sys.stdout.reconfigure(errors="replace")  # some consoles cannot print emoji
    p = argparse.ArgumentParser(description="Multi-agent Writer & Critic")
    p.add_argument("--topic")
    p.add_argument("--audience")
    p.add_argument("--points", help="key points, separated by semicolons")
    p.add_argument("--format", dest="fmt", help="blog post, LinkedIn post or email summary")
    p.add_argument("--criteria")
    a = p.parse_args()

    brief = Brief(
        topic=ask("Topic", a.topic, "Why small code reviews beat big ones"),
        audience=ask("Audience", a.audience, "engineering managers"),
        key_points=[s.strip() for s in ask("Key points (separate with ;)", a.points,
                    "big reviews get rubber-stamped; small ones ship faster; reviewers stay focused").split(";") if s.strip()],
        format=ask("Format", a.fmt, "LinkedIn post"),
        criteria=ask("Editing criteria", a.criteria, DEFAULT_CRITERIA),
    )
    print(f"\nTeam: planner, writer, critic, editor  |  {config.PROVIDER} {config.MODEL}  |  max {config.MAX_ROUNDS} revision rounds")
    try:
        result = observability.run_traced(lambda: Pipeline(LLM(), on_event=show).run(brief), brief)
    except LLMError as e:
        raise SystemExit(f"Error: {e}")

    d = result.to_dict()
    print("\n=== FINAL VERSION ===\n" + result.final)
    print(f"\nRounds of critique: {d['rounds']}{' (approved)' if d['approvedEarly'] else ' (limit reached)'}  |  "
          f"words {d['wordsBefore']} -> {d['wordsAfter']}  |  {d['seconds']}s, {d['inputTokens']}+{d['outputTokens']} tokens")
    if observability.enabled():
        print("Trace sent to Eval Workbench: Traces -> 'Writer & Critic (live)'.")


if __name__ == "__main__":
    main()
