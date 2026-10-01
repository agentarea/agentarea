"""Decision toolset: structured questions answered by a decision model.

A decision model (TypeSafe Jev and kin, "System One") reads a state and answers
typed questions about it with calibrated probabilities, far cheaper than a chat
model round-trip. The model is the workspace instance named in the toolset
settings (``model_id``); the platform resolves it into ``backend``.
"""

from __future__ import annotations

import json
from decimal import Decimal
from enum import StrEnum
from typing import Any, Protocol

from pydantic import BaseModel, Field

from .decorator_tool import Toolset, tool_method
from .tool_authz import unrestricted
from .tool_definition import toolset

DECIDE_TOOLSET = "agentarea/decide"


class DecisionQuestionType(StrEnum):
    """The question types this tool accepts; the decision model's own vocabulary
    (``agentarea_llm.domain.media.DecisionQuestionType``), which the SDK cannot import.
    """

    CHOICE = "choice"
    NOUL = "noul"
    SCORE = "score"


class DecisionQuestion(BaseModel):
    type: DecisionQuestionType = Field(
        description=(
            "choice: pick one option from criteria; noul: probability the statement in "
            "instructions is true; score: rate against the criteria list"
        )
    )
    instructions: str = Field(description="The question, asked about the state")
    criteria: dict[str, str] | list[str] | None = Field(
        default=None,
        description=(
            "choice: {option: what it means}; score: the scale, lowest first; "
            "noul: optional {'true': ..., 'false': ...}"
        ),
    )


class DecisionOutcome(Protocol):
    answers: dict[str, dict[str, Any]]
    cost: Decimal


class DecisionBackend(Protocol):
    async def evaluate(self, state: str, questions: dict[str, Any]) -> DecisionOutcome: ...


@toolset(
    namespace=DECIDE_TOOLSET,
    display_name="Decisions",
    description=(
        "Ask the workspace's decision model structured questions about a state: pick an "
        "option, the likelihood a statement holds, or a score."
    ),
    category="reasoning",
    plane="runtime",
)
class DecideToolset(Toolset):
    def __init__(self, *, backend: DecisionBackend | None = None, decide: bool = True) -> None:
        # Built bare to read its schema (tool_builders); only the activity wires
        # a backend, and a call without one fails.
        super().__init__()
        self._backend = backend
        if not decide:
            self._tool_methods.pop("decide", None)

    @tool_method(
        effect="read",
        description=(
            "Answer questions about a state with a decision model. Each question has a "
            "type: choice (criteria maps option -> meaning; answer carries choice and "
            "probabilities), noul (answer carries noul, the probability the instructions "
            "hold), or score (criteria lists the scale; answer carries score)."
        ),
    )
    @unrestricted("reads and writes no workspace state")
    async def decide(self, state: str, questions: dict[str, DecisionQuestion]) -> dict[str, Any]:
        """Answer questions about a state with a decision model."""
        payload = {
            key: question.model_dump(mode="json", exclude_none=True)
            if isinstance(question, BaseModel)
            else question
            for key, question in questions.items()
        }
        if self._backend is None:
            raise RuntimeError("agentarea/decide has no model backend in this context")
        outcome = await self._backend.evaluate(state, payload)
        return {
            "success": True,
            "result": json.dumps({"answers": outcome.answers}),
            "model_cost": str(outcome.cost),
        }
