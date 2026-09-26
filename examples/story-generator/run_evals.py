"""Run the story generator against its eval suite and send the results, with traces, to Eval Workbench.

    python run_evals.py --version v1 --note "Baseline prompt"
"""
import argparse
import os
from pathlib import Path

from eval_workbench import Client
from story import generate_story

SUITE_ID = "story-generator"

parser = argparse.ArgumentParser()
parser.add_argument("--version", default="v1")
parser.add_argument("--note", default="")
args = parser.parse_args()

client = Client()  # EVAL_WORKBENCH_URL and EVAL_WORKBENCH_API_KEY, from the environment or .env
if client.get_suite(SUITE_ID) is None:
    client.import_suite((Path(__file__).parent / "suite.json").read_text(encoding="utf-8"))
    print(f"Created suite '{SUITE_ID}' from suite.json")

model = os.environ.get("OPENAI_MODEL", "gpt-4o-mini")
result = client.run_suite(
    SUITE_ID, lambda prompt: generate_story(prompt), version=args.version, model=model, note=args.note,
    on_result=lambda r: print(f"  {r['caseId']}  {r['verdict']:<6} {r['category'] or '':<24} {r['latencyMs']} ms"),
)
s = result.summary
print(f"\n{s['Pass']} pass, {s['Fail']} fail, {s['Review']} review ({s['passRate']:.0%}), p95 {s['p95']} ms")
print(f"Open {result.url}")
