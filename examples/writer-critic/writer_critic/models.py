"""Plain data passed between the agents and the orchestrator."""
import json
from dataclasses import dataclass, field
from typing import Optional

from .prompts import DEFAULT_CRITERIA


@dataclass
class Brief:
    topic: str
    audience: str = "a general audience"
    key_points: list = field(default_factory=list)
    format: str = "LinkedIn post"
    criteria: str = DEFAULT_CRITERIA

    def points_text(self) -> str:
        return "\n".join(f"- {p}" for p in self.key_points) or "- (none given)"

    def summary(self) -> str:
        return f"{self.format} about {self.topic} for {self.audience}"


@dataclass
class AgentOutput:
    """What one agent call produced, plus what it cost."""
    agent: str
    text: str
    seconds: float = 0.0
    input_tokens: int = 0
    output_tokens: int = 0


@dataclass
class Review:
    """The Critic's structured verdict on one draft."""
    scores: dict = field(default_factory=dict)
    issues: list = field(default_factory=list)
    instructions: str = ""
    verdict: str = "revise"
    parse_error: Optional[str] = None

    @property
    def average(self) -> float:
        nums = [v for v in self.scores.values() if isinstance(v, (int, float))]
        return sum(nums) / len(nums) if nums else 0.0

    def approved(self, threshold: float) -> bool:
        return self.average >= threshold

    @classmethod
    def parse(cls, text: str) -> "Review":
        """Read the Critic's JSON reply. A bad reply becomes a 'revise' review instead of crashing the run."""
        start, end = text.find("{"), text.rfind("}")
        try:
            data = json.loads(text[start:end + 1])
            scores = {k: v for k, v in (data.get("scores") or {}).items() if isinstance(v, (int, float))}
            return cls(scores=scores, issues=[str(i) for i in data.get("issues", [])],
                       instructions=str(data.get("revision_instructions", "")), verdict=str(data.get("verdict", "revise")))
        except (ValueError, AttributeError, TypeError):
            return cls(issues=["The critic's reply was not valid JSON."], instructions=text[:500], parse_error=text[:200])

    def to_dict(self) -> dict:
        return {"scores": self.scores, "average": round(self.average, 2), "issues": self.issues,
                "instructions": self.instructions, "verdict": self.verdict}


@dataclass
class Step:
    """One agent call in the run, for the timeline."""
    agent: str
    label: str
    round: int
    output: AgentOutput
    review: Optional[Review] = None

    def to_dict(self) -> dict:
        d = {"agent": self.agent, "label": self.label, "round": self.round, "text": self.output.text,
             "seconds": round(self.output.seconds, 2), "inputTokens": self.output.input_tokens,
             "outputTokens": self.output.output_tokens}
        if self.review:
            d["review"] = self.review.to_dict()
        return d


@dataclass
class Result:
    brief: Brief
    outline: str = ""
    first_draft: str = ""
    final: str = ""
    reviews: list = field(default_factory=list)
    steps: list = field(default_factory=list)
    approved_early: bool = False

    @property
    def rounds(self) -> int:
        return len(self.reviews)

    def words(self, text: str) -> int:
        return len(text.split())

    def to_dict(self) -> dict:
        before, after = self.words(self.first_draft), self.words(self.final)
        return {"outline": self.outline, "firstDraft": self.first_draft, "final": self.final, "rounds": self.rounds,
                "approvedEarly": self.approved_early, "wordsBefore": before, "wordsAfter": after,
                "inputTokens": sum(s.output.input_tokens for s in self.steps),
                "outputTokens": sum(s.output.output_tokens for s in self.steps),
                "seconds": round(sum(s.output.seconds for s in self.steps), 2)}
