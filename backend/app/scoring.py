"""Python port of the frontend Evaluators module, evaluate(), summarize() and compareRuns().

Behaviour must stay identical to frontend/index.html (see the scoring rules in CLAUDE.md).
"""
import json
import math
import re
from typing import Any, Optional

REFUSAL_RE = re.compile(r"\b(can't|cannot|unable to|not able to|won't be able)\b", re.I)


def norm(s: Any) -> str:
    text = "" if s is None else str(s)
    return re.sub(r"\s+", " ", text.lower().replace("‘", "'").replace("’", "'"))


def fmt_ms(v: float) -> str:
    return f"{v / 1000:.2f} s" if v >= 1000 else f"{round(v)} ms"


def _quoted(values: list) -> str:
    return ", ".join(f'"{v}"' for v in values)


def _contains_all(out, c):
    o = norm(out)
    miss = [v for v in c["values"] if norm(v) not in o]
    n = len(c["values"])
    detail = f"Missing {_quoted(miss)}" if miss else f"Found all {n} required term{'s' if n > 1 else ''}"
    return {"pass": not miss, "partial": 0 < len(miss) < n, "detail": detail}


def _contains_any(out, c):
    o = norm(out)
    hit = next((v for v in c["values"] if norm(v) in o), None)
    return {"pass": hit is not None, "detail": f'Found "{hit}"' if hit is not None else f"None of {_quoted(c['values'])} found"}


def _not_contains(out, c):
    o = norm(out)
    hit = [v for v in c["values"] if norm(v) in o]
    return {"pass": not hit, "detail": f"Found forbidden {_quoted(hit)}" if hit else "No forbidden terms found"}


def _regex(out, c):
    flags = 0
    for f in c.get("flags") or "":
        flags |= {"i": re.I, "m": re.M, "s": re.S}.get(f, 0)
    try:
        pattern = re.compile(c["pattern"], flags)
    except re.error:
        return {"pass": False, "detail": "The pattern is not a valid regular expression"}
    ok = pattern.search(str(out)) is not None
    return {"pass": ok, "detail": "Output matches the pattern" if ok else "Output does not match the required pattern"}


def _json_keys(out, c):
    s = str(out)
    a, b = s.find("{"), s.rfind("}")
    if a < 0 or b < a:
        return {"pass": False, "detail": "No JSON object found in the output"}
    try:
        obj = json.loads(s[a : b + 1])
    except ValueError:
        return {"pass": False, "detail": "Output contains braces but is not valid JSON"}
    miss = [k for k in c["keys"] if not isinstance(obj, dict) or k not in obj]
    extra = len(s[:a].strip()) + len(s[b + 1 :].strip())
    if miss:
        return {"pass": False, "detail": f"JSON is missing {', '.join(miss)}"}
    if c.get("strict") and extra:
        return {"pass": False, "detail": "JSON is wrapped in extra text"}
    return {"pass": True, "detail": f"Valid JSON with {', '.join(c['keys'])}"}


def _max_length(out, c):
    n = len(str(out))
    return {"pass": n <= c["max"], "detail": f"{n} characters against a limit of {c['max']}"}


def _human(out, c):
    return {"pass": None, "manual": True, "detail": c.get("rubric", "")}


# Register new evaluator types here (LLM-as-a-judge, custom checks).
EVALUATORS = {
    "contains_all": {"label": "Must include all", "category": "Incomplete answer", "run": _contains_all,
                     "describe": lambda c: _quoted(c["values"])},
    "contains_any": {"label": "Must include one of", "category": "Incorrect answer", "run": _contains_any,
                     "describe": lambda c: " or ".join(f'"{v}"' for v in c["values"])},
    "not_contains": {"label": "Must not include", "category": "Hallucination", "run": _not_contains,
                     "describe": lambda c: _quoted(c["values"])},
    "regex": {"label": "Matches pattern", "category": "Format violation", "run": _regex,
              "describe": lambda c: f"/{c['pattern']}/{c.get('flags') or ''}"},
    "json_keys": {"label": "Valid JSON with keys", "category": "Format violation", "run": _json_keys,
                  "describe": lambda c: ", ".join(c["keys"])},
    "max_length": {"label": "Max length", "category": "Instruction not followed", "run": _max_length,
                   "describe": lambda c: f"{c['max']} characters"},
    "human": {"label": "Human review", "category": None, "run": _human, "describe": lambda c: c.get("rubric", "")},
}


def expects_refusal(checks: list) -> bool:
    return any(REFUSAL_RE.search(v) for c in checks or [] for v in (c.get("values") or []))


def evaluate(checks_def: list, output: str, latency_ms: float, sla_ms: Optional[float], error: Optional[str] = None,
             live: bool = False) -> dict:
    """Score one execution. `live` is for production traffic: a request sent without checks is judged on errors
    and latency only, instead of going to review (nobody reviews every live request)."""
    if error:
        return {"verdict": "Fail", "category": "Execution error", "reason": error, "checks": []}
    checks = []
    for c in checks_def or []:
        ev = EVALUATORS.get(c.get("type"))
        if ev is None:
            checks.append({"type": c.get("type"), "label": c.get("type"), "pass": False, "detail": "Unknown check type"})
            continue
        checks.append({"type": c["type"], "label": ev["label"], "spec": ev["describe"](c),
                       "category": c.get("category") or ev["category"], **ev["run"](output, c)})
    hard = [r for r in checks if not r.get("manual") and r["pass"] is False and not r.get("partial")]
    partial = [r for r in checks if r.get("partial")]
    manual = next((r for r in checks if r.get("manual")), None)
    if not checks and not live:
        return {"verdict": "Review", "category": "Awaiting human review",
                "reason": "No automated checks are defined for this case.", "checks": checks}
    if hard:
        cat = hard[0].get("category") or "Incorrect answer"
        if REFUSAL_RE.search(str(output)) and not expects_refusal(checks_def) and cat != "Policy violation":
            cat = "Unwarranted refusal"
        return {"verdict": "Fail", "category": cat, "reason": f"{hard[0]['label']} failed: {hard[0]['detail']}.", "checks": checks}
    if partial:
        return {"verdict": "Review", "category": "Partial match",
                "reason": f"{partial[0]['label']} only partly met: {partial[0]['detail']}.", "checks": checks}
    if manual:
        return {"verdict": "Review", "category": "Awaiting human review",
                "reason": f"Needs a reviewer to judge: {manual['detail']}", "checks": checks}
    if sla_ms and latency_ms > sla_ms:
        return {"verdict": "Fail", "category": "Latency SLA breach",
                "reason": f"Answer was correct but took {fmt_ms(latency_ms)} against a {fmt_ms(sla_ms)} SLA.", "checks": checks}
    if not checks:
        return {"verdict": "Pass", "category": None, "reason": "No errors and within the latency SLA. No content checks were sent.",
                "checks": checks}
    return {"verdict": "Pass", "category": None, "reason": "All automated checks passed.", "checks": checks}


TOKENS_IN = ("prompt_tokens", "input_tokens")
TOKENS_OUT = ("completion_tokens", "output_tokens")


def span_totals(spans: list) -> dict:
    """Tokens and cost for one execution, summed from span attributes (prompt_tokens or input_tokens,
    completion_tokens or output_tokens, cost_usd). Set them on the span of each model call, not on its parents.
    Same as spanTotals() in the frontend."""
    totals = {"tokensIn": None, "tokensOut": None, "costUsd": None}
    for sp in spans or []:
        attrs = (sp.get("attrs") if isinstance(sp, dict) else getattr(sp, "attrs", None)) or {}
        for field, keys in (("tokensIn", TOKENS_IN), ("tokensOut", TOKENS_OUT), ("costUsd", ("cost_usd",))):
            for k in keys:
                v = attrs.get(k)
                if isinstance(v, (int, float)) and not isinstance(v, bool) and v >= 0:
                    totals[field] = (totals[field] or 0) + v
    for field in ("tokensIn", "tokensOut"):
        if totals[field] is not None:
            totals[field] = int(totals[field])
    return totals


def _pct(sorted_vals: list, p: float):
    if not sorted_vals:
        return None
    i = min(len(sorted_vals) - 1, max(0, math.ceil(p * len(sorted_vals)) - 1))
    return sorted_vals[i]


def summarize(results: list) -> dict:
    counts = {"Pass": 0, "Fail": 0, "Review": 0}
    cats: dict = {}
    reviews: dict = {}
    for r in results:
        counts[r["verdict"]] += 1
        if r["verdict"] == "Fail":
            cats[r["category"]] = cats.get(r["category"], 0) + 1
        if r["verdict"] == "Review":
            reviews[r["category"]] = reviews.get(r["category"], 0) + 1
    n = len(results)
    lat = sorted(r["latencyMs"] for r in results if r["latencyMs"] > 0)
    return {"n": n, **counts, "passRate": counts["Pass"] / n if n else 0, "p50": _pct(lat, 0.5), "p95": _pct(lat, 0.95),
            "avg": sum(lat) / len(lat) if lat else None, "cats": cats, "reviews": reviews,
            "sla": cats.get("Latency SLA breach", 0)}


def compare_runs(a_results: list, b_results: list) -> dict:
    A = {r["caseId"]: r for r in a_results}
    out = {"regressions": [], "degraded": [], "fixes": [], "stillFailing": [], "stable": [], "latency": [], "added": [], "removed": []}
    for rb in b_results:
        ra = A.get(rb["caseId"])
        if ra is None:
            out["added"].append(rb)
            continue
        pair = {"caseId": rb["caseId"], "a": ra, "b": rb}
        if ra["verdict"] == "Pass" and rb["verdict"] == "Fail":
            out["regressions"].append(pair)
        elif ra["verdict"] == "Pass" and rb["verdict"] == "Review":
            out["degraded"].append(pair)
        elif ra["verdict"] != "Pass" and rb["verdict"] == "Pass":
            out["fixes"].append(pair)
        elif ra["verdict"] == "Fail" and rb["verdict"] == "Fail":
            out["stillFailing"].append(pair)
        else:
            out["stable"].append(pair)
        if rb["latencyMs"] - ra["latencyMs"] > 300 and rb["latencyMs"] > ra["latencyMs"] * 1.3:
            out["latency"].append(pair)
    present = {r["caseId"] for r in b_results}
    out["removed"] = [r for r in a_results if r["caseId"] not in present]
    return out
