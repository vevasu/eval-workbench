import time
from typing import Any, Optional

from sqlalchemy import BigInteger, Index
from sqlmodel import JSON, Column, Field, SQLModel


def now_ms() -> int:
    return int(time.time() * 1000)


def ms_column(nullable: bool = False):
    """Epoch milliseconds do not fit in a 32-bit Postgres INTEGER, so timestamps are BIGINT."""
    return Column(BigInteger, nullable=nullable)


class Project(SQLModel, table=True):
    id: str = Field(primary_key=True)
    name: str
    created_at: int = Field(default_factory=now_ms, sa_column=ms_column())
    # The AI judge: the project's own model key, encrypted (app/keystore.py), and the model it uses.
    judge_key: Optional[str] = None
    judge_model: str = ""


class ApiKey(SQLModel, table=True):
    id: str = Field(primary_key=True)
    project_id: str = Field(foreign_key="project.id", index=True)
    name: str = ""
    prefix: str
    key_hash: str = Field(unique=True, index=True)
    created_at: int = Field(default_factory=now_ms, sa_column=ms_column())
    revoked_at: Optional[int] = Field(default=None, sa_column=ms_column(nullable=True))


# Suites, cases and runs are keyed by (project_id, id) so two projects can use the same public IDs.
class Suite(SQLModel, table=True):
    project_id: str = Field(foreign_key="project.id", primary_key=True)
    id: str = Field(primary_key=True)
    prefix: str
    name: str
    description: str = ""
    pipeline: str = "chat"
    sla_ms: int
    system_prompt: str = ""
    context: Any = Field(default=None, sa_column=Column(JSON))
    created_at: int = Field(default_factory=now_ms, sa_column=ms_column())
    live_checks: Any = Field(default=None, sa_column=Column(JSON))  # run on every production request, set in the web app


class TestCase(SQLModel, table=True):
    project_id: str = Field(primary_key=True)
    suite_id: str = Field(primary_key=True)
    id: str = Field(primary_key=True)
    position: int = 0
    tag: str = ""
    input: str
    expected: str = ""
    checks: Any = Field(default_factory=list, sa_column=Column(JSON))
    recorded: Optional[str] = None
    recorded_latency_ms: Optional[int] = None
    origin: Optional[str] = None  # "<run id>/<case id>" of the production trace this case was created from


class Run(SQLModel, table=True):
    project_id: str = Field(primary_key=True)
    id: str = Field(primary_key=True)
    suite_id: str = Field(index=True)
    version: str = ""
    model: str = ""
    target: str = "simulated"
    note: str = ""
    started_at: int = Field(sa_column=ms_column())
    finished_at: Optional[int] = Field(default=None, sa_column=ms_column(nullable=True))
    sla_ms: int


class Result(SQLModel, table=True):
    __table_args__ = (Index("ix_result_project_timestamp", "project_id", "timestamp"),)
    id: Optional[int] = Field(default=None, primary_key=True)
    project_id: str = Field(index=True)
    run_id: str = Field(index=True)
    case_id: str = Field(index=True)
    input: str = ""
    expected: str = ""
    actual: str = ""
    verdict: str
    category: Optional[str] = None
    reason: str = ""
    checks: Any = Field(default_factory=list, sa_column=Column(JSON))
    latency_ms: int = 0
    timestamp: int = Field(default_factory=now_ms, sa_column=ms_column())
    model: str = ""
    version: str = ""
    # Production traces: who the request came from, how to group it, and what it used. Empty for test runs.
    user_id: Optional[str] = Field(default=None, index=True)
    session_id: Optional[str] = Field(default=None, index=True)
    tags: Any = Field(default=None, sa_column=Column(JSON))
    meta: Any = Field(default=None, sa_column=Column(JSON))  # "metadata" in the API; that name is taken in SQLAlchemy
    tokens_in: Optional[int] = None
    tokens_out: Optional[int] = None
    cost_usd: Optional[float] = None
    # A person's decision. verdict and category then hold it, and review keeps the automatic ones:
    # {verdict, category, note, reviewer, reviewedAt, autoVerdict, autoCategory}. reviewed_at is for filtering.
    review: Any = Field(default=None, sa_column=Column(JSON))
    reviewed_at: Optional[int] = Field(default=None, sa_column=ms_column(nullable=True))


class Span(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    result_id: int = Field(foreign_key="result.id", index=True)
    name: str
    kind: str = "other"
    start: float = 0
    dur: float = 0
    depth: int = 0
    attrs: Any = Field(default_factory=dict, sa_column=Column(JSON))


class AccessRequest(SQLModel, table=True):
    """Someone asked for private beta access. The operator approves it, which creates a project and an API key."""
    id: Optional[int] = Field(default=None, primary_key=True)
    email: str = Field(index=True)
    name: str = ""
    use_case: str = ""
    status: str = "pending"  # pending, approved or rejected
    project_id: Optional[str] = None
    created_at: int = Field(default_factory=now_ms, sa_column=ms_column())
    decided_at: Optional[int] = Field(default=None, sa_column=ms_column(nullable=True))
