"""
models/rubric.py
----------------
Rubric data models.

question_id is now a **string** to match the hierarchical QuestionNode IDs
in models/paper.py.  All other fields are unchanged.
"""

from __future__ import annotations

from pydantic import BaseModel
from typing import List, Optional
from enum import Enum


# ---------------------------------------------------------------------------
# Rubric Models
# ---------------------------------------------------------------------------

class ExpectedDepth(str, Enum):
    """Bloom's Taxonomy cognitive levels."""
    remember   = "remember"
    understand = "understand"
    apply      = "apply"
    analyze    = "analyze"
    evaluate   = "evaluate"
    create     = "create"


class Concept(BaseModel):
    concept_name:    str
    description:     str
    keywords:        List[str]
    marks_allocated: float
    mandatory:       bool


class PartialMarkingRule(BaseModel):
    keyword_only_percentage:      float
    partial_explanation_percentage: float


class RubricQuestion(BaseModel):
    question_id:   str              # ← string now (was int)
    question_text: str
    total_marks:   float
    question_type: str = "descriptive"    # "mcq" | "descriptive"

    # Descriptive-only fields (None for MCQ)
    expected_depth:       Optional[ExpectedDepth]      = None
    concepts:             Optional[List[Concept]]      = None
    partial_marking_rule: Optional[PartialMarkingRule] = None

    # MCQ-only fields (None for descriptive)
    correct_options: Optional[List[str]] = None   # e.g. ["B. Decision Tree"]
    options:         Optional[List[str]] = None   # all printed options
    is_multi_select: bool                = False


class Rubric(BaseModel):
    """Internal storage model — questions only, no computed fields."""
    questions: List[RubricQuestion]


class RubricResponse(BaseModel):
    """
    API response model.
    total_questions and total_marks are computed in Python.
    """
    total_questions: int
    total_marks:     float
    questions:       List[RubricQuestion]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def build_rubric_response(rubric: Rubric) -> RubricResponse:
    return RubricResponse(
        total_questions=len(rubric.questions),
        total_marks=sum(q.total_marks for q in rubric.questions),
        questions=rubric.questions,
    )