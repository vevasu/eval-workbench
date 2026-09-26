import csv
import io
import json
import re
from typing import Optional

from fastapi import HTTPException
from sqlmodel import Session, select

from .models import Run, Suite, TestCase, now_ms
from .scoring import EVALUATORS


def get_suite_or_404(session: Session, project_id: str, suite_id: str) -> Suite:
    suite = session.get(Suite, (project_id, suite_id))
    if suite is None:
        raise HTTPException(status_code=404, detail="Suite not found")
    return suite


def get_run_or_404(session: Session, project_id: str, run_id: str) -> Run:
    run = session.get(Run, (project_id, run_id))
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")
    return run


def validate_checks(checks: list) -> None:
    for c in checks:
        if c.get("type") not in EVALUATORS:
            raise HTTPException(status_code=422, detail=f"Unknown check type '{c.get('type')}'.")
        if c["type"] == "regex":
            try:
                re.compile(c.get("pattern", ""))
            except re.error:
                raise HTTPException(status_code=422, detail="The regex pattern is not valid.")


def make_prefix(name: str) -> str:
    prefix = "".join(re.findall(r"\b[a-zA-Z]", name)[:2]).upper() or "S"
    return prefix + "X" if len(prefix) < 2 else prefix


def create_suite(session: Session, project_id: str, data: dict) -> Suite:
    base = data.get("id") or re.sub(r"[^a-z0-9]+", "-", data["name"].lower()).strip("-")[:30] or "suite"
    suite_id, i = base, 2
    while session.get(Suite, (project_id, suite_id)):
        if data.get("id"):
            raise HTTPException(status_code=409, detail=f"A suite with id '{suite_id}' already exists.")
        suite_id, i = f"{base}-{i}", i + 1
    suite = Suite(
        project_id=project_id, id=suite_id, prefix=data.get("prefix") or make_prefix(data["name"]), name=data["name"],
        description=data.get("description") or "", pipeline=data.get("pipeline") or "chat",
        sla_ms=int(data.get("sla_ms") or 3000), system_prompt=data.get("system_prompt") or "",
        context=data.get("context"), created_at=now_ms(),
    )
    session.add(suite)
    return suite


def next_case_id(session: Session, suite: Suite) -> str:
    existing = {c.id for c in session.exec(
        select(TestCase).where(TestCase.project_id == suite.project_id, TestCase.suite_id == suite.id)).all()}
    n = len(existing) + 1
    while f"{suite.prefix}-{n:03d}" in existing:
        n += 1
    return f"{suite.prefix}-{n:03d}"


def add_case(session: Session, suite: Suite, data: dict) -> TestCase:
    validate_checks(data.get("checks") or [])
    case_id = data.get("id") or next_case_id(session, suite)
    if session.get(TestCase, (suite.project_id, suite.id, case_id)):
        raise HTTPException(status_code=409, detail=f"Case '{case_id}' already exists in this suite.")
    count = len(session.exec(select(TestCase).where(
        TestCase.project_id == suite.project_id, TestCase.suite_id == suite.id)).all())
    case = TestCase(
        project_id=suite.project_id, suite_id=suite.id, id=case_id, position=count, tag=data.get("tag") or "",
        input=data["input"], expected=data.get("expected") or "", checks=data.get("checks") or [],
        recorded=data.get("recorded"), recorded_latency_ms=data.get("recorded_latency_ms"),
    )
    session.add(case)
    session.flush()
    return case


def next_run_id(session: Session, suite: Suite) -> str:
    n = len(session.exec(select(Run).where(Run.project_id == suite.project_id, Run.suite_id == suite.id)).all()) + 1
    while session.get(Run, (suite.project_id, f"{suite.prefix}-R{n}")):
        n += 1
    return f"{suite.prefix}-R{n}"


def _split(value: str) -> list:
    return [s.strip() for s in value.split("|") if s.strip()]


def parse_import(fmt: str, content: str, name: Optional[str]) -> dict:
    """Port of the frontend doImport(): returns a suite spec with cases."""
    text = content.strip()
    if not text:
        raise HTTPException(status_code=422, detail="No content to import.")
    try:
        if fmt == "json":
            spec = json.loads(text)
            if isinstance(spec, list):
                spec = {"name": name or "Imported suite", "cases": spec}
        else:
            rows = list(csv.reader(io.StringIO(text)))
            rows = [r for r in rows if any(c.strip() for c in r)]
            header = [h.strip().lower() for h in rows.pop(0)]

            def col(r, k):
                return r[header.index(k)].strip() if k in header and header.index(k) < len(r) else ""

            cases = []
            for r in rows:
                checks = []
                if col(r, "must_not_include"):
                    checks.append({"type": "not_contains", "values": _split(col(r, "must_not_include"))})
                if col(r, "json_keys"):
                    checks.append({"type": "json_keys", "keys": _split(col(r, "json_keys").replace(",", "|"))})
                if col(r, "pattern"):
                    checks.append({"type": "regex", "pattern": col(r, "pattern"), "flags": "i"})
                if col(r, "must_include_any"):
                    checks.append({"type": "contains_any", "values": _split(col(r, "must_include_any"))})
                if col(r, "must_include"):
                    checks.append({"type": "contains_all", "values": _split(col(r, "must_include"))})
                if col(r, "max_length").isdigit() and int(col(r, "max_length")) > 0:
                    checks.append({"type": "max_length", "max": int(col(r, "max_length"))})
                if col(r, "review_rubric"):
                    checks.append({"type": "human", "rubric": col(r, "review_rubric")})
                case = {"id": col(r, "id") or None, "input": col(r, "input"), "expected": col(r, "expected"), "checks": checks}
                if "actual" in header and col(r, "actual"):
                    case["actual"] = col(r, "actual")
                    case["latencyMs"] = int(col(r, "latency_ms") or 0) if col(r, "latency_ms").isdigit() else 0
                cases.append(case)
            spec = {"name": name or "Imported suite", "cases": cases}
    except (ValueError, IndexError, csv.Error) as e:
        raise HTTPException(status_code=422, detail=f"Could not read that content: {e}")
    if not isinstance(spec, dict) or not isinstance(spec.get("cases"), list) or not spec["cases"]:
        raise HTTPException(status_code=422, detail="No test cases found. JSON needs a 'cases' array; CSV needs a header row and at least one case.")
    for i, c in enumerate(spec["cases"]):
        if not isinstance(c, dict) or not c.get("input"):
            raise HTTPException(status_code=422, detail=f"Case {i + 1} has no input.")
        validate_checks(c.get("checks") or [])
    spec["name"] = spec.get("name") or name or "Imported suite"
    return spec
