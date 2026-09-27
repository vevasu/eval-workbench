"""The orchestrator: decides which agent runs next and passes results between them.

    Planner -> Writer -> [ Critic -> (approved? stop : Writer revises) ] x up to MAX_ROUNDS -> Editor
"""
from typing import Callable, Optional

from . import config
from .agents import Critic, Editor, Planner, Writer
from .llm import LLM
from .models import Brief, Result, Step


class Pipeline:
    def __init__(self, llm: LLM, max_rounds: int = config.MAX_ROUNDS, approve_score: float = config.APPROVE_SCORE,
                 on_event: Optional[Callable[[dict], None]] = None) -> None:
        self.planner, self.writer, self.critic, self.editor = Planner(llm), Writer(llm), Critic(llm), Editor(llm)
        self.max_rounds, self.approve_score = max_rounds, approve_score
        self.on_event = on_event or (lambda event: None)

    def _record(self, result: Result, agent: str, label: str, round_no: int, output, review=None) -> None:
        step = Step(agent=agent, label=label, round=round_no, output=output, review=review)
        result.steps.append(step)
        self.on_event({"type": "step", "step": step.to_dict()})

    def _starting(self, agent: str, label: str, round_no: int) -> None:
        self.on_event({"type": "start", "agent": agent, "label": label, "round": round_no})

    def run(self, brief: Brief) -> Result:
        result = Result(brief=brief)

        self._starting("planner", "Planning the outline", 0)
        plan = self.planner.run(brief=brief)
        result.outline = plan.text
        self._record(result, "planner", "Outline", 0, plan)

        self._starting("writer", "Writing the first draft", 0)
        draft_out = self.writer.run(brief=brief, outline=result.outline)
        draft = result.first_draft = draft_out.text
        self._record(result, "writer", "First draft", 0, draft_out)

        review = None
        for round_no in range(1, self.max_rounds + 1):
            self._starting("critic", f"Reviewing draft (round {round_no})", round_no)
            critic_out, review = self.critic.review(brief, draft)
            result.reviews.append(review)
            self._record(result, "critic", f"Review, round {round_no}", round_no, critic_out, review)
            if review.approved(self.approve_score):
                result.approved_early = True
                break
            self._starting("writer", f"Revising the draft (round {round_no})", round_no)
            revised = self.writer.run(brief=brief, outline=result.outline, previous_draft=draft, review=review)
            draft = revised.text
            self._record(result, "writer", f"Revision, round {round_no}", round_no, revised)

        self._starting("editor", "Final edit", self.max_rounds)
        final_out = self.editor.run(brief=brief, draft=draft, review=review)
        result.final = final_out.text
        self._record(result, "editor", "Final version", result.rounds, final_out)
        self.on_event({"type": "done", "result": result.to_dict()})
        return result
