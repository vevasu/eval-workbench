from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel


class CamelModel(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, from_attributes=True)


# ---- Read models (field names match data/sample-data.json) ----

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
    category: Optional[str] = None
    reason: str = ""
    checks: list = []
    latency_ms: int = 0
    timestamp: int
    model: str = ""
    version: str = ""
    spans: list[SpanOut] = []
    review: Optional[dict] = None  # a person's decision; verdict and category then hold it
    # Production traces only (None for test runs).
    user_id: Optional[str] = None
    session_id: Optional[str] = None
    tags: Optional[list] = None
    metadata: Optional[dict] = Field(default=None, validation_alias="meta")
    tokens_in: Optional[int] = None
    tokens_out: Optional[int] = None
    cost_usd: Optional[float] = None


# Left out of /state, where every result is from a test run and these are always empty.
LIVE_FIELDS = {"user_id", "session_id", "tags", "metadata", "tokens_in", "tokens_out", "cost_usd"}


class CaseOut(CamelModel):
    id: str
    tag: str = ""
    input: str
    expected: str = ""
    checks: list = []
    recorded: Optional[str] = None
    recorded_latency_ms: Optional[int] = None
    origin: Optional[str] = None


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


# ---- Write models ----

class SuiteIn(CamelModel):
    name: str = Field(min_length=1)
    description: str = ""
    pipeline: str = "chat"
    sla_ms: int = 3000
    system_prompt: str = ""
    context: Any = None
    id: Optional[str] = None
    prefix: Optional[str] = None


class SuitePatch(CamelModel):
    name: Optional[str] = None
    description: Optional[str] = None
    pipeline: Optional[str] = None
    sla_ms: Optional[int] = None
    system_prompt: Optional[str] = None
    context: Any = None


class CaseIn(CamelModel):
    id: Optional[str] = None
    input: str = Field(min_length=1)
    expected: str = ""
    tag: str = ""
    checks: list[dict] = []
    recorded: Optional[str] = None
    recorded_latency_ms: Optional[int] = None
    origin: Optional[str] = Field(default=None, max_length=200)  # "<run id>/<case id>" of a production trace


class CasePatch(CamelModel):
    input: Optional[str] = None
    expected: Optional[str] = None
    tag: Optional[str] = None
    checks: Optional[list[dict]] = None


class ImportIn(CamelModel):
    format: Literal["json", "csv"]
    content: str
    name: Optional[str] = None


class RunIn(CamelModel):
    suite_id: str
    version: str = ""
    model: str = ""
    note: str = ""
    target: str = "sdk"


class SpanIn(CamelModel):
    name: str
    kind: str = "other"
    start: float = 0
    dur: float = 0
    depth: int = 0
    attrs: dict = {}


class ResultIn(CamelModel):
    case_id: str
    actual: str = ""
    latency_ms: int = 0
    timestamp: Optional[int] = None
    spans: list[SpanIn] = []
    error: Optional[str] = None


class ResultsIn(CamelModel):
    results: list[ResultIn]


class ReviewIn(CamelModel):
    verdict: Literal["Pass", "Fail"]
    category: Optional[str] = None  # required for Fail: why it failed
    note: str = Field(default="", max_length=1000)
    reviewer: str = Field(default="", max_length=80)


class ProjectIn(CamelModel):
    name: str = Field(min_length=1)
    id: Optional[str] = None


class KeyIn(CamelModel):
    name: str = ""
