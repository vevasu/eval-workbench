"""Optional: send each run to Eval Workbench as a trace, scored by simple guardrail checks.

Turned on by setting EVAL_WORKBENCH_API_KEY (and EVAL_WORKBENCH_URL) in .env, with the SDK installed.
"""
import os
from typing import Callable

from . import config
from .models import Brief, Result
from .tracing import Client

SUITE_ID, SUITE_NAME = "writer-critic-live", "Writer & Critic (live)"
# The final text must not contain these buzzwords.
LIVE_CHECKS = [{"type": "not_contains", "category": "Instruction not followed",
                "values": ["synergy", "leverage", "game-changer", "cutting-edge", "revolutionize", "unlock the power", "delve"]}]


def enabled() -> bool:
    return bool(Client and os.environ.get("EVAL_WORKBENCH_API_KEY"))


def run_traced(run: Callable[[], Result], brief: Brief) -> Result:
    """Run the pipeline. If tracing is on, its agent spans are uploaded to the Workbench in the background."""
    if not enabled():
        return run()
    box: dict = {}

    def work(_text: str) -> str:
        box["result"] = run()
        return box["result"].final

    Client().observe(SUITE_ID, work, brief.summary(), suite_name=SUITE_NAME, version="v1",
                     model=config.MODEL, checks=LIVE_CHECKS)
    return box["result"]
