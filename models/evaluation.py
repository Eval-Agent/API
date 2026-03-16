from pydantic import BaseModel
from typing import Dict, List, Optional
from enum import Enum


# ---------------------------------------------------------------------------
# Core Models
# ---------------------------------------------------------------------------

class StudentInfo(BaseModel):
    student_name: str
    roll_number: Optional[str] = None


class BloomOutcome(str, Enum):
    """
    Per-question Bloom's taxonomy outcome — computed in Python from marks.
    correct  (green)  : marks_awarded == maximum_marks
    partial  (yellow) : 0 < marks_awarded < maximum_marks
    incorrect (red)   : marks_awarded == 0
    """
    correct   = "correct"    # full marks — green
    partial   = "partial"    # some marks — yellow
    incorrect = "incorrect"  # zero marks — red


class BloomDepthStat(BaseModel):
    """Per-Bloom's-level aggregated stats — all computed in Python."""
    total_marks: float        # sum of maximum_marks for questions at this level
    awarded_marks: float      # sum of marks_awarded for questions at this level
    percentage: float         # awarded / total * 100, or 0 if no questions at this level
    question_count: int       # number of questions at this level


class EvaluationSummary(BaseModel):
    """
    Storage + response model.
    All numeric fields are computed in Python — Gemini only generates overall_feedback.
    bloom_breakdown is keyed by ExpectedDepth value (e.g. "remember", "analyze").
    """
    full_marks: float
    total_attempted: float
    total_marks_awarded: float
    percentage: float
    overall_feedback: str
    bloom_breakdown: Dict[str, BloomDepthStat] = {}


class ConceptVerdict(str, Enum):
    correct   = "correct"
    partial   = "partial"
    incorrect = "incorrect"


class ConceptEvaluation(BaseModel):
    concept_name: str
    marks_allocated: float
    marks_awarded: float
    verdict: ConceptVerdict
    reason: str


class QuestionEvaluation(BaseModel):
    question_id: int
    maximum_marks: float
    marks_awarded: float
    concept_evaluations: List[ConceptEvaluation]
    justification: str
    strengths: Optional[List[str]] = None
    areas_for_improvement: Optional[List[str]] = None
    # Bloom's fields — populated by the evaluator service, never by Gemini
    bloom_depth: Optional[str] = None    # e.g. "analyze"  — from rubric
    bloom_outcome: Optional[str] = None  # "correct" | "partial" | "incorrect"


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
# Helpers
# ---------------------------------------------------------------------------

def _bloom_outcome(marks_awarded: float, maximum_marks: float) -> str:
    """Determine colour-coded outcome from raw marks."""
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

    bloom_breakdown  — keyed by depth level (e.g. "remember", "analyze").
                       Only levels that appear in the evaluated questions are included.
                       percentage = awarded / total * 100 per level.
    """
    total_attempted = sum(q.maximum_marks for q in question_wise_evaluation)
    total_awarded   = sum(q.marks_awarded  for q in question_wise_evaluation)
    percentage      = round((total_awarded / full_marks * 100), 2) if full_marks > 0 else 0.0

    # Aggregate per Bloom's level
    bloom_totals: Dict[str, dict] = {}
    for q in question_wise_evaluation:
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
        full_marks=full_marks,
        total_attempted=total_attempted,
        total_marks_awarded=total_awarded,
        percentage=percentage,
        overall_feedback=overall_feedback,
        bloom_breakdown=bloom_breakdown,
    )


# ---------------------------------------------------------------------------
# Submission API models  (the OCR step, exposed as "submissions" in the API)
# ---------------------------------------------------------------------------

class SubmissionResponse(BaseModel):
    """Returned after POST /papers/{paper_id}/submissions."""
    submission_id: str
    paper_id: str
    answer_sha256: str
    is_duplicate: bool
    student_info: StudentInfo
    extracted_answers: List[ExtractedAnswer]
    message: str


class SubmissionSummaryResponse(BaseModel):
    """Returned in list view — one row per uploaded answer sheet."""
    submission_id: str
    paper_id: str
    answer_sha256: str
    student_name: str
    roll_number: Optional[str]
    has_evaluation: bool
    created_at: str


class SubmissionStudentInfoUpdateRequest(BaseModel):
    student_name: str
    roll_number: Optional[str] = None


class SubmissionDeleteResponse(BaseModel):
    submission_id: str
    message: str


# ---------------------------------------------------------------------------
# Evaluation API models
# ---------------------------------------------------------------------------

class EvaluateRequest(BaseModel):
    """Body for POST /submissions/{submission_id}/evaluation:generate."""
    submission_id: str


class EvaluationResponse(BaseModel):
    """Returned after evaluate and on GET detail."""
    eval_id: str
    paper_id: str
    submission_id: str
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
    submission_id: str
    student_name: str
    roll_number: Optional[str]
    confirmed: bool


class EvaluationConfirmRequest(BaseModel):
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


# ---------------------------------------------------------------------------
# Legacy aliases — so existing internal imports (OcrResponse etc.) keep working
# ---------------------------------------------------------------------------

OcrResponse                 = SubmissionResponse
OcrSummaryResponse          = SubmissionSummaryResponse
OcrStudentInfoUpdateRequest = SubmissionStudentInfoUpdateRequest
OcrDeleteResponse           = SubmissionDeleteResponse