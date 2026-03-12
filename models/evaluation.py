from pydantic import BaseModel
from typing import List, Optional
from enum import Enum


# ---------------------------------------------------------------------------
# Evaluation Core Models
# ---------------------------------------------------------------------------

class StudentInfo(BaseModel):
    student_name: str
    roll_number: Optional[str] = None


class EvaluationSummary(BaseModel):
    """
    Storage + response model.
    full_marks, total_attempted, total_marks_awarded, percentage are all
    computed in Python — Gemini only generates overall_feedback.
    """
    full_marks: float
    total_attempted: float
    total_marks_awarded: float
    percentage: float
    overall_feedback: str


class ConceptVerdict(str, Enum):
    correct   = "correct"
    partial   = "partial"
    incorrect = "incorrect"


class ConceptEvaluation(BaseModel):
    concept_name: str
    marks_allocated: float   # echoed from rubric
    marks_awarded: float     # computed in Python from verdict + partial_marking_rule
    verdict: ConceptVerdict
    reason: str


class QuestionEvaluation(BaseModel):
    question_id: int
    maximum_marks: float
    marks_awarded: float     # computed: sum of concept marks_awarded
    concept_evaluations: List[ConceptEvaluation]
    justification: str
    strengths: Optional[List[str]] = None
    areas_for_improvement: Optional[List[str]] = None


class ExtractedAnswer(BaseModel):
    """One OCR-extracted answer from the student's answer sheet."""
    question_id: int
    answer_markdown: str


class EvaluationReport(BaseModel):
    """Internal storage model — full report including OCR-extracted answers."""
    student_info: StudentInfo
    extracted_answers: List[ExtractedAnswer] = []
    evaluation_summary: EvaluationSummary
    question_wise_evaluation: List[QuestionEvaluation]


# ---------------------------------------------------------------------------
# Evaluation Helpers
# ---------------------------------------------------------------------------

def build_evaluation_summary(
    overall_feedback: str,
    question_wise_evaluation: list,
    full_marks: float,
) -> EvaluationSummary:
    """
    Compute summary fields from graded questions and paper metadata.
    - total_attempted     : sum of maximum_marks for answered questions
    - total_marks_awarded : sum of marks_awarded across answered questions
    - percentage          : (total_marks_awarded / full_marks) * 100
    """
    total_attempted = sum(q.maximum_marks for q in question_wise_evaluation)
    total_awarded   = sum(q.marks_awarded  for q in question_wise_evaluation)
    percentage      = round((total_awarded / full_marks * 100), 2) if full_marks > 0 else 0.0
    return EvaluationSummary(
        full_marks=full_marks,
        total_attempted=total_attempted,
        total_marks_awarded=total_awarded,
        percentage=percentage,
        overall_feedback=overall_feedback,
    )


# ---------------------------------------------------------------------------
# Evaluation API Request / Response Models
# ---------------------------------------------------------------------------

class OcrResponse(BaseModel):
    """Returned after POST /evaluations/ocr."""
    ocr_id: str
    paper_id: str
    answer_sha256: str
    is_duplicate: bool
    student_info: StudentInfo
    extracted_answers: List[ExtractedAnswer]
    message: str


class EvaluateRequest(BaseModel):
    """Body for POST /evaluations/evaluate."""
    ocr_id: str


class EvaluationResponse(BaseModel):
    """Returned after evaluate and on GET detail."""
    eval_id: str
    paper_id: str
    answer_sha256: str
    is_duplicate: bool
    student_info: StudentInfo
    extracted_answers: List[ExtractedAnswer]
    evaluation_summary: EvaluationSummary
    question_wise_evaluation: List[QuestionEvaluation]
    confirmed: bool
    message: str


class EvaluationSummaryResponse(BaseModel):
    """Returned in the list view — one row per student."""
    eval_id: str
    paper_id: str
    student_name: str
    roll_number: Optional[str]
    confirmed: bool


class EvaluationConfirmRequest(BaseModel):
    eval_id: str
    student_info: StudentInfo
    extracted_answers: List[ExtractedAnswer] = []
    evaluation_summary: EvaluationSummary
    question_wise_evaluation: List[QuestionEvaluation]


class EvaluationConfirmResponse(BaseModel):
    eval_id: str
    message: str


class EvaluationDeleteResponse(BaseModel):
    eval_id: str
    message: str


class OcrDeleteResponse(BaseModel):
    ocr_id: str
    message: str


class OcrSummaryResponse(BaseModel):
    """Returned in the OCR list view — one row per uploaded answer sheet."""
    ocr_id: str
    paper_id: str
    answer_sha256: str
    student_name: str
    roll_number: Optional[str]
    has_evaluation: bool
    created_at: str