"""
models/evaluation.py
--------------------
Evaluation data models.

question_id is now a **string** throughout to match the hierarchical
QuestionNode IDs introduced in models/paper.py.
"""

from __future__ import annotations

from pydantic import BaseModel
from typing import Dict, List, Optional
from enum import Enum


# ---------------------------------------------------------------------------
# Core Models
# ---------------------------------------------------------------------------

class StudentInfo(BaseModel):
    student_name: str
    roll_number:  Optional[str] = None


class BloomOutcome(str, Enum):
    correct   = "correct"
    partial   = "partial"
    incorrect = "incorrect"


class BloomDepthStat(BaseModel):
    total_marks:    float
    awarded_marks:  float
    percentage:     float
    question_count: int


class EvaluationSummary(BaseModel):
    full_marks:           float
    total_attempted:      float
    total_marks_awarded:  float
    percentage:           float
    overall_feedback:     str
    bloom_breakdown:      Dict[str, BloomDepthStat] = {}


class ConceptVerdict(str, Enum):
    correct   = "correct"
    partial   = "partial"
    incorrect = "incorrect"


class ConceptEvaluation(BaseModel):
    concept_name:    str
    marks_allocated: float
    marks_awarded:   float
    verdict:         ConceptVerdict
    reason:          str


class QuestionEvaluation(BaseModel):
    question_id:            str           # ← string now (was int)
    maximum_marks:          float
    marks_awarded:          float
    concept_evaluations:    List[ConceptEvaluation]
    justification:          str
    strengths:              Optional[List[str]] = None
    areas_for_improvement:  Optional[List[str]] = None
    bloom_depth:            Optional[str]       = None
    bloom_outcome:          Optional[str]       = None
    course_outcome:         Optional[str]       = None
    counted:                bool               = True


class ExtractedAnswer(BaseModel):
    """One OCR-extracted answer from the student's answer sheet."""
    question_id:     str     # ← string now (was int)
    answer_markdown: str


class EvaluationReport(BaseModel):
    """Internal storage model — full report including OCR-extracted answers."""
    student_info:              StudentInfo
    extracted_answers:         List[ExtractedAnswer]  = []
    evaluation_summary:        EvaluationSummary
    question_wise_evaluation:  List[QuestionEvaluation]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _bloom_outcome(marks_awarded: float, maximum_marks: float) -> str:
    if maximum_marks <= 0:
        return BloomOutcome.incorrect.value
    if marks_awarded >= maximum_marks:
        return BloomOutcome.correct.value
    if marks_awarded > 0:
        return BloomOutcome.partial.value
    return BloomOutcome.incorrect.value


def build_evaluation_summary(
    overall_feedback: str,
    question_wise_evaluation: list,
    full_marks: float,
) -> EvaluationSummary:
    """
    Compute all numeric summary fields from graded questions.
    Only counted=True questions contribute to totals.
    """
    counted_qs = [q for q in question_wise_evaluation if q.counted]

    total_attempted = sum(q.maximum_marks for q in counted_qs)
    total_awarded   = sum(q.marks_awarded  for q in counted_qs)
    percentage      = round((total_awarded / full_marks * 100), 2) if full_marks > 0 else 0.0

    bloom_totals: Dict[str, dict] = {}
    for q in counted_qs:
        depth = q.bloom_depth
        if not depth:
            continue
        if depth not in bloom_totals:
            bloom_totals[depth] = {"total_marks": 0.0, "awarded_marks": 0.0, "question_count": 0}
        bloom_totals[depth]["total_marks"]    += q.maximum_marks
        bloom_totals[depth]["awarded_marks"]  += q.marks_awarded
        bloom_totals[depth]["question_count"] += 1

    bloom_breakdown: Dict[str, BloomDepthStat] = {
        depth: BloomDepthStat(
            total_marks=round(v["total_marks"], 2),
            awarded_marks=round(v["awarded_marks"], 2),
            percentage=round(v["awarded_marks"] / v["total_marks"] * 100, 2)
                       if v["total_marks"] > 0 else 0.0,
            question_count=v["question_count"],
        )
        for depth, v in bloom_totals.items()
    }

    return EvaluationSummary(
        full_marks=round(full_marks, 2),
        total_attempted=round(total_attempted, 2),
        total_marks_awarded=round(total_awarded, 2),
        percentage=percentage,
        overall_feedback=overall_feedback,
        bloom_breakdown=bloom_breakdown,
    )


# ---------------------------------------------------------------------------
# Submission API models
# ---------------------------------------------------------------------------

class SubmissionResponse(BaseModel):
    submission_id:     str
    paper_id:          str
    answer_sha256:     str
    is_duplicate:      bool
    student_info:      StudentInfo
    extracted_answers: List[ExtractedAnswer]
    message:           str


class SubmissionSummaryResponse(BaseModel):
    submission_id:  str
    paper_id:       str
    answer_sha256:  str
    student_name:   str
    roll_number:    Optional[str]
    has_evaluation: bool
    created_at:     str


class SubmissionStudentInfoUpdateRequest(BaseModel):
    student_name: str
    roll_number:  Optional[str] = None


class SubmissionDeleteResponse(BaseModel):
    submission_id: str
    message:       str


# ---------------------------------------------------------------------------
# Evaluation API models
# ---------------------------------------------------------------------------

class EvaluateRequest(BaseModel):
    submission_id: str


class EvaluationResponse(BaseModel):
    eval_id:                   str
    paper_id:                  str
    submission_id:             str
    answer_sha256:             str
    is_duplicate:              bool
    student_info:              StudentInfo
    extracted_answers:         List[ExtractedAnswer]
    evaluation_summary:        EvaluationSummary
    question_wise_evaluation:  List[QuestionEvaluation]
    confirmed:                 bool
    message:                   str


class EvaluationSummaryResponse(BaseModel):
    eval_id:       str
    paper_id:      str
    submission_id: str
    student_name:  str
    roll_number:   Optional[str]
    confirmed:     bool


class EvaluationConfirmRequest(BaseModel):
    student_info:              StudentInfo
    extracted_answers:         List[ExtractedAnswer]    = []
    evaluation_summary:        EvaluationSummary
    question_wise_evaluation:  List[QuestionEvaluation]


class EvaluationConfirmResponse(BaseModel):
    eval_id: str
    message: str


class EvaluationDeleteResponse(BaseModel):
    eval_id: str
    message: str


# ---------------------------------------------------------------------------
# Legacy aliases
# ---------------------------------------------------------------------------

OcrResponse                 = SubmissionResponse
OcrSummaryResponse          = SubmissionSummaryResponse
OcrStudentInfoUpdateRequest = SubmissionStudentInfoUpdateRequest
OcrDeleteResponse           = SubmissionDeleteResponse