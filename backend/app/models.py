import time
from typing import Any, Optional

from sqlmodel import JSON, Column, Field, SQLModel


def _now_ms() -> int:
    return int(time.time() * 1000)


class Project(SQLModel, table=True):
    id: str = Field(primary_key=True)
    name: str
    created_at: int = Field(default_factory=_now_ms)


class Suite(SQLModel, table=True):
    id: str = Field(primary_key=True)
    project_id: str = Field(foreign_key="project.id", index=True)
    prefix: str
    name: str
    description: str = ""
    pipeline: str = "chat"
    sla_ms: int
    system_prompt: str = ""
    context: Any = Field(default=None, sa_column=Column(JSON))
    created_at: int = Field(default_factory=_now_ms)


class TestCase(SQLModel, table=True):
    id: str = Field(primary_key=True)
    suite_id: str = Field(foreign_key="suite.id", index=True)
    tag: str = ""
    input: str
    expected: str = ""
    checks: Any = Field(default_factory=list, sa_column=Column(JSON))
    recorded: Optional[str] = None
    recorded_latency_ms: Optional[int] = None


class Run(SQLModel, table=True):
    id: str = Field(primary_key=True)
    suite_id: str = Field(foreign_key="suite.id", index=True)
    version: str = ""
    model: str = ""
    target: str = "simulated"
    note: str = ""
    started_at: int
    finished_at: Optional[int] = None
    sla_ms: int


class Result(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    run_id: str = Field(foreign_key="run.id", index=True)
    case_id: str = Field(index=True)
    input: str = ""
    expected: str = ""
    actual: str = ""
    verdict: str
    category: str = ""
    reason: str = ""
    checks: Any = Field(default_factory=list, sa_column=Column(JSON))
    latency_ms: int = 0
    timestamp: int = Field(default_factory=_now_ms)
    model: str = ""
    version: str = ""


class Span(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    result_id: int = Field(foreign_key="result.id", index=True)
    name: str
    kind: str = "other"
    start: float = 0
    dur: float = 0
    depth: int = 0
    attrs: Any = Field(default_factory=dict, sa_column=Column(JSON))
