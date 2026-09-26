import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from writer_critic import prompts  # noqa: E402
from writer_critic.llm import LLMResponse  # noqa: E402
from writer_critic.models import Brief, Review  # noqa: E402
from writer_critic.pipeline import Pipeline  # noqa: E402

BRIEF = Brief(topic="Small code reviews", audience="managers", key_points=["ship faster", "stay focused"])


def review(score, issues=("too wordy",)):
    return json.dumps({"scores": {"clarity": score, "concision": score}, "issues": list(issues),
                       "revision_instructions": "cut it", "verdict": "approve" if score >= 4 else "revise"})


class FakeLLM:
    """Replies by agent (matched on the system prompt), in order. Records every call."""

    def __init__(self, critic_replies):
        self.queues = {prompts.PLANNER_PROMPT: ["OUTLINE"], prompts.WRITER_PROMPT: ["DRAFT 1", "DRAFT 2", "DRAFT 3"],
                       prompts.CRITIC_PROMPT: list(critic_replies), prompts.EDITOR_PROMPT: ["FINAL"]}
        self.calls = []

    def complete(self, system, user, **kwargs):
        self.calls.append((system, user, kwargs))
        return LLMResponse(text=self.queues[system].pop(0), input_tokens=10, output_tokens=5)


def order(result):
    return [s.agent for s in result.steps]


def test_approved_on_first_review_skips_revision():
    result = Pipeline(FakeLLM([review(5)]), max_rounds=2, approve_score=4).run(BRIEF)
    assert order(result) == ["planner", "writer", "critic", "editor"]
    assert result.approved_early and result.rounds == 1 and result.final == "FINAL"


def test_rejected_draft_goes_back_to_the_writer_with_the_critics_feedback():
    llm = FakeLLM([review(2, ["rambling intro"]), review(5)])
    result = Pipeline(llm, max_rounds=2, approve_score=4).run(BRIEF)
    assert order(result) == ["planner", "writer", "critic", "writer", "critic", "editor"]
    revision_prompt = next(u for s, u, _ in llm.calls if s == prompts.WRITER_PROMPT and "PREVIOUS DRAFT" in u)
    assert "DRAFT 1" in revision_prompt and "rambling intro" in revision_prompt
    editor_prompt = next(u for s, u, _ in llm.calls if s == prompts.EDITOR_PROMPT)
    assert "DRAFT 2" in editor_prompt  # the editor polishes the revised draft, not the first one


def test_revision_loop_stops_at_max_rounds_even_if_never_approved():
    result = Pipeline(FakeLLM([review(1), review(1), review(1)]), max_rounds=2, approve_score=4).run(BRIEF)
    assert order(result).count("critic") == 2 and order(result).count("writer") == 3
    assert not result.approved_early and result.final == "FINAL"


def test_bad_critic_json_becomes_a_revise_review_instead_of_crashing():
    parsed = Review.parse("Sorry, I cannot produce JSON")
    assert parsed.average == 0 and not parsed.approved(4) and parsed.parse_error
    result = Pipeline(FakeLLM(["not json", review(5)]), max_rounds=2, approve_score=4).run(BRIEF)
    assert result.reviews[0].parse_error and result.approved_early


def test_events_and_totals():
    events = []
    result = Pipeline(FakeLLM([review(5)]), max_rounds=1, approve_score=4, on_event=events.append).run(BRIEF)
    assert [e["type"] for e in events] == ["start", "step"] * 4 + ["done"]
    assert result.to_dict()["inputTokens"] == 40 and events[-1]["result"]["final"] == "FINAL"
    assert events[5]["step"]["review"]["average"] == 5


def test_critic_is_asked_for_json_and_others_are_not():
    llm = FakeLLM([review(5)])
    Pipeline(llm, max_rounds=1, approve_score=4).run(BRIEF)
    by_agent = {s: kw.get("json_mode") for s, _, kw in llm.calls}
    assert by_agent[prompts.CRITIC_PROMPT] is True and by_agent[prompts.WRITER_PROMPT] is False
