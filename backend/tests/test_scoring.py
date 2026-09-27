import json
from pathlib import Path

import pytest

from app.scoring import compare_runs, decide, evaluate, span_totals, summarize

DATA = json.loads((Path(__file__).resolve().parents[2] / "data" / "sample-data.json").read_text(encoding="utf-8"))
CASES = {(s["id"], c["id"]): c for s in DATA["suites"] for c in s["cases"]}


# The checks the demo's production traffic sends (LIVE_STORY_CHECKS and BEDTIME_CHECK in frontend/index.html).
LIVE_CHECKS = [{"type": "not_contains", "values": ["…"], "category": "Incomplete answer"},
               {"type": "regex", "pattern": "^\\s*(\\S+\\s+){0,79}\\S+\\s*$", "category": "Instruction not followed"}]
BEDTIME_CHECK = {"type": "not_contains", "values": ["monster", "blood", "kill", "scary", "dead"], "category": "Policy violation"}
LIVE_JUDGE = DATA["suites"][0]["liveChecks"][0]  # the demo suite's AI judge, set as a check on live traffic
TEST_RUNS = [r for r in DATA["runs"] if r["target"] != "production"]
LIVE_RUNS = [r for r in DATA["runs"] if r["target"] == "production"]


@pytest.mark.parametrize("run", TEST_RUNS, ids=[r["id"] for r in TEST_RUNS])
def test_scorer_matches_every_stored_result(run):
    for r in run["results"]:
        case = CASES[(run["suiteId"], r["caseId"])]
        ev = evaluate(case["checks"], r["actual"], r["latencyMs"], run["slaMs"])
        auto = (r["review"]["autoVerdict"], r["review"]["autoCategory"]) if r.get("review") else (r["verdict"], r["category"])
        assert (ev["verdict"], ev["category"]) == auto, r["caseId"]  # a person's decision replaces the verdict; the automatic one is kept
        assert ev["reason"] == r["reason"], r["caseId"]
        assert ev["checks"] == r["checks"], r["caseId"]


@pytest.mark.parametrize("run", LIVE_RUNS, ids=[r["id"] for r in LIVE_RUNS])
def test_scorer_and_totals_match_every_production_request(run):
    for r in run["results"]:
        judged = next((c for c in r["checks"] if c["type"] == "llm_judge"), None)
        checks = LIVE_CHECKS + ([BEDTIME_CHECK] if r["tags"] == ["bedtime"] else []) + ([LIVE_JUDGE] if judged else [])
        error = next((s["attrs"]["error"] for s in r["spans"] if "error" in s["attrs"]), None)
        ev = evaluate(checks, r["actual"], r["latencyMs"], run["slaMs"], error, live=True)
        if ev["category"] == "Awaiting AI judge":  # fill in what the model answered, as app/judge.py does, and decide again
            pending = next(c for c in ev["checks"] if c.get("pending"))
            refusal = pending.pop("refusalExpected")
            pending.pop("pending")
            pending.update({"pass": judged["pass"], "detail": judged["detail"], "judgedBy": judged["judgedBy"]})
            ev = decide(ev["checks"], r["actual"], r["latencyMs"], run["slaMs"], live=True, refusal_expected=refusal)
        assert (ev["verdict"], ev["category"], ev["reason"], ev["checks"]) == (r["verdict"], r["category"], r["reason"], r["checks"]), r["caseId"]
        totals = span_totals(r["spans"])
        assert (totals["tokensIn"], totals["tokensOut"]) == (r["tokensIn"], r["tokensOut"]), r["caseId"]
        assert totals["costUsd"] == pytest.approx(r["costUsd"], abs=1e-12), r["caseId"]


def test_execution_error_is_a_failure():
    ev = evaluate([{"type": "contains_all", "values": ["x"]}], "", 0, 1000, "Boom")
    assert (ev["verdict"], ev["category"], ev["reason"]) == ("Fail", "Execution error", "Boom")


def test_latency_breach_only_when_everything_else_passes():
    checks = [{"type": "contains_all", "values": ["ok"]}]
    assert evaluate(checks, "ok", 3500, 3000)["category"] == "Latency SLA breach"
    assert evaluate(checks, "nope", 3500, 3000)["category"] == "Incomplete answer"


def test_refusal_becomes_unwarranted_refusal():
    ev = evaluate([{"type": "contains_all", "values": ["60"]}], "Sorry, I cannot help with that.", 100, 1000)
    assert ev["category"] == "Unwarranted refusal"


def test_summary_and_comparison_on_sample_runs():
    runs = {r["id"]: r for r in DATA["runs"]}
    a, b = runs["DS-R4"]["results"], runs["DS-R5"]["results"]
    s = summarize(b)
    assert (s["n"], s["Pass"], s["Fail"], s["Review"]) == (10, 5, 3, 2)
    assert round(s["passRate"], 3) == round(5 / 10, 3)
    diff = compare_runs(a, b)
    assert [p["caseId"] for p in diff["regressions"]] == ["DS-003", "DS-004", "DS-006"]
    assert [p["caseId"] for p in diff["degraded"]] == ["DS-010"] and diff["fixes"] == []
