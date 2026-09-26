from typing import Any, Optional

from pydantic import BaseModel, ConfigDict
from pydantic.alias_generators import to_camel


class CamelModel(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, from_attributes=True)


class SpanOut(CamelModel):
    name: str
    kind: str
    start: float
    dur: float
    depth: int
    attrs: dict = {}


class ResultOut(CamelModel):
    case_id: str
    input: str = ""
    expected: str = ""
    actual: str = ""
    verdict: str
    category: str = ""
    reason: str = ""
    checks: list = []
    latency_ms: int = 0
    timestamp: int
    model: str = ""
    version: str = ""
    spans: list[SpanOut] = []


class CaseOut(CamelModel):
    id: str
    tag: str = ""
    input: str
    expected: str = ""
    checks: list = []
    recorded: Optional[str] = None
    recorded_latency_ms: Optional[int] = None


class SuiteOut(CamelModel):
    id: str
    prefix: str
    name: str
    description: str = ""
    pipeline: str
    sla_ms: int
    system_prompt: str = ""
    context: Any = None
    created_at: int
    cases: Optional[list[CaseOut]] = None


class RunOut(CamelModel):
    id: str
    suite_id: str
    version: str = ""
    model: str = ""
    target: str = "simulated"
    note: str = ""
    started_at: int
    finished_at: Optional[int] = None
    sla_ms: int
    results: Optional[list[ResultOut]] = None
