"""The four agents. Each has a role (system prompt), builds its own input message, and returns an AgentOutput.

To add an agent: subclass Agent, set `name` and `system_prompt`, implement build_message(), and call it from
pipeline.py.
"""
import time

from . import prompts
from .llm import LLM
from .models import AgentOutput, Brief, Review
from .tracing import span


class Agent:
    name = "agent"
    system_prompt = ""
    temperature = 0.7
    json_mode = False

    def __init__(self, llm: LLM) -> None:
        self.llm = llm

    def build_message(self, **context) -> str:
        raise NotImplementedError

    def run(self, **context) -> AgentOutput:
        with span(f"agent.{self.name}", agent=self.name):
            started = time.time()
            reply = self.llm.complete(self.system_prompt, self.build_message(**context),
                                      temperature=self.temperature, json_mode=self.json_mode)
            return AgentOutput(agent=self.name, text=reply.text, seconds=time.time() - started,
                               input_tokens=reply.input_tokens, output_tokens=reply.output_tokens)


class Planner(Agent):
    """Turns the brief into an outline, so the Writer has a structure to follow."""
    name = "planner"
    system_prompt = prompts.PLANNER_PROMPT
    temperature = 0.5

    def build_message(self, brief: Brief) -> str:
        return (f"Format: {brief.format}\nTopic: {brief.topic}\nTarget audience: {brief.audience}\n"
                f"Key points:\n{brief.points_text()}")


class Writer(Agent):
    """Writes the first draft from the outline, and revises it when the Critic sends feedback."""
    name = "writer"
    system_prompt = prompts.WRITER_PROMPT
    temperature = 0.9

    def build_message(self, brief: Brief, outline: str, previous_draft: str = "", review: Review = None) -> str:
        message = (f"Format: {brief.format}\nTopic: {brief.topic}\nTarget audience: {brief.audience}\n"
                   f"Key points:\n{brief.points_text()}\n\nOUTLINE:\n{outline}")
        if previous_draft and review:
            issues = "\n".join(f"- {i}" for i in review.issues) or "- (none listed)"
            message += (f"\n\nPREVIOUS DRAFT:\n{previous_draft}\n\nCRITIC'S ISSUES:\n{issues}\n\n"
                        f"CRITIC'S INSTRUCTIONS:\n{review.instructions}")
        return message


class Critic(Agent):
    """Scores a draft against the criteria and says what to fix. Replies in JSON."""
    name = "critic"
    system_prompt = prompts.CRITIC_PROMPT
    temperature = 0.2
    json_mode = True

    def build_message(self, brief: Brief, draft: str) -> str:
        return f"EDITING CRITERIA:\n{brief.criteria}\n\nDRAFT:\n{draft}"

    def review(self, brief: Brief, draft: str) -> tuple:
        """Returns (AgentOutput, Review)."""
        output = self.run(brief=brief, draft=draft)
        return output, Review.parse(output.text)


class Editor(Agent):
    """Does the final polish: applies the criteria and any issues the Critic left."""
    name = "editor"
    system_prompt = prompts.EDITOR_PROMPT
    temperature = 0.2

    def build_message(self, brief: Brief, draft: str, review: Review = None) -> str:
        message = f"EDITING CRITERIA:\n{brief.criteria}\n\nDRAFT:\n{draft}"
        if review and (review.issues or review.instructions):
            issues = "\n".join(f"- {i}" for i in review.issues)
            message += f"\n\nCRITIC'S LAST REVIEW:\nIssues:\n{issues}\nInstructions: {review.instructions}"
        return message
