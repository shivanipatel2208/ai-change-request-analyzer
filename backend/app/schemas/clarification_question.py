"""Pydantic schemas for ClarificationQuestion. Populated by the AI module;
answering one (see app/api/change_requests.py::answer_clarification_question)
is the one human-writable action on it - everything else stays exactly what
the AI produced."""
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, field_validator

from app.models.enums import Priority


class ClarificationQuestionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    analysis_id: int
    question: str
    priority: Priority
    reason: str
    resolved: bool
    # None until someone answers it (see ClarificationQuestionAnswer below).
    answer_text: Optional[str] = None
    answered_by: Optional[int] = None
    answered_at: Optional[datetime] = None


class ClarificationQuestionAnswer(BaseModel):
    """PATCH .../clarification-questions/{id}/answer body - the actual
    missing information, typed in by whoever has it. Answering always marks
    the question resolved; there's no separate "just mark resolved with no
    text" path, since an unexplained resolved=True would be indistinguishable
    from the AI's question having simply been ignored."""

    answer: str

    @field_validator("answer")
    @classmethod
    def _not_blank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("An answer is required.")
        return value
