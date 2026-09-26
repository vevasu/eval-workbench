from collections import defaultdict

from sqlmodel import Session, select

from .models import Result, Run, Span, Suite, TestCase
from .schemas import CaseOut, ResultOut, RunOut, SpanOut, SuiteOut


def cases_for(session: Session, project_id: str, suite_id: str) -> list[TestCase]:
    return session.exec(
        select(TestCase)
        .where(TestCase.project_id == project_id, TestCase.suite_id == suite_id)
        .order_by(TestCase.position, TestCase.id)
    ).all()


def suite_out(session: Session, suite: Suite, with_cases: bool = True) -> SuiteOut:
    out = SuiteOut.model_validate(suite)
    if with_cases:
        out.cases = [CaseOut.model_validate(c) for c in cases_for(session, suite.project_id, suite.id)]
    return out


def results_for(session: Session, project_id: str, run_id: str, with_spans: bool = False) -> list[ResultOut]:
    rows = session.exec(
        select(Result).where(Result.project_id == project_id, Result.run_id == run_id).order_by(Result.id)
    ).all()
    outs = [ResultOut.model_validate(r) for r in rows]
    if with_spans and rows:
        spans = session.exec(select(Span).where(Span.result_id.in_([r.id for r in rows])).order_by(Span.id)).all()
        by_result = defaultdict(list)
        for s in spans:
            by_result[s.result_id].append(SpanOut.model_validate(s))
        for row, out in zip(rows, outs):
            out.spans = by_result[row.id]
    return outs


def run_out(session: Session, run: Run, with_results: bool = False, with_spans: bool = False) -> RunOut:
    out = RunOut.model_validate(run)
    if with_results:
        out.results = results_for(session, run.project_id, run.id, with_spans)
    return out
