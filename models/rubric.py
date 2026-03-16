from pydantic import BaseModel
from typing import List
from enum import Enum


# ---------------------------------------------------------------------------
# Rubric Models
# ---------------------------------------------------------------------------

class ExpectedDepth(str, Enum):
    """Bloom's Taxonomy cognitive levels — used to set the expected answer depth per question."""
    remember   = "remember"    # Recall facts, definitions, or lists
    understand = "understand"  # Explain, summarise, or describe in own words
    apply      = "apply"       # Use knowledge to solve a problem or demonstrate
    analyze    = "analyze"     # Break down, compare, differentiate, or examine
    evaluate   = "evaluate"    # Justify, critique, assess, or argue a position
    create     = "create"      # Design, construct, propose, or synthesise something new"


class Concept(BaseModel):
    concept_name: str
    description: str
    keywords: List[str]
    marks_allocated: float
    mandatory: bool


class PartialMarkingRule(BaseModel):
    keyword_only_percentage: float
    partial_explanation_percentage: float


class RubricQuestion(BaseModel):
    question_id: int
    question_text: str
    total_marks: float
    expected_depth: ExpectedDepth
    concepts: List[Concept]
    partial_marking_rule: PartialMarkingRule


class Rubric(BaseModel):
    """Internal storage model — questions only, no computed fields."""
    questions: List[RubricQuestion]


class RubricResponse(BaseModel):
    """
    API response model.
    total_questions and total_marks are computed in Python —
    Gemini is never asked to produce them.
    """
    total_questions: int
    total_marks: float
    questions: List[RubricQuestion]


# ---------------------------------------------------------------------------
# Rubric Helpers
# ---------------------------------------------------------------------------

def build_rubric_response(rubric: Rubric) -> RubricResponse:
    """Compute total_questions and total_marks from the questions list."""
    return RubricResponse(
        total_questions=len(rubric.questions),
        total_marks=sum(q.total_marks for q in rubric.questions),
        questions=rubric.questions,
    )