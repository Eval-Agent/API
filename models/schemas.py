from pydantic import BaseModel
from typing import List, Optional
from enum import Enum


# ---------------------------------------------------------------------------
# OCR / Question Paper Models
# ---------------------------------------------------------------------------

class PaperMetadata(BaseModel):
    subject_name: str
    subject_code: str
    degree: str
    stream: str
    exam_type: str
    set_no: str
    full_marks: str
    total_duration: float
    total_pages: int


class ParsedQuestion(BaseModel):
    question_id: int
    question_markdown: str
    max_score: int


class ParsedPaper(BaseModel):
    metadata: PaperMetadata
    questions: List[ParsedQuestion]


# ---------------------------------------------------------------------------
# Rubric Models
# ---------------------------------------------------------------------------

class ExpectedDepth(str, Enum):
    definition = "definition"
    short_explanation = "short_explanation"
    detailed_explanation = "detailed_explanation"
    analytical = "analytical"


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
    """Internal storage model — no computed fields."""
    questions: List[RubricQuestion]


class RubricResponse(BaseModel):
    """
    API response model.
    total_questions and total_marks are computed in Python from the
    questions list — Gemini is never asked to produce them.
    """
    total_questions: int
    total_marks: float
    questions: List[RubricQuestion]


def build_rubric_response(rubric: Rubric) -> RubricResponse:
    """Compute total_questions and total_marks from the questions list."""
    return RubricResponse(
        total_questions=len(rubric.questions),
        total_marks=sum(q.total_marks for q in rubric.questions),
        questions=rubric.questions,
    )


# ---------------------------------------------------------------------------
# API Request / Response Models
# ---------------------------------------------------------------------------

class PaperUploadResponse(BaseModel):
    paper_id: str
    sha256_hash: str
    is_duplicate: bool
    parsed_paper: ParsedPaper
    rubric: RubricResponse
    message: str


class PaperConfirmRequest(BaseModel):
    """
    Sent by the client after the user reviews and optionally edits
    the parsed paper and rubric before final persistence.
    """
    paper_id: str
    parsed_paper: ParsedPaper
    rubric: Rubric


class PaperConfirmResponse(BaseModel):
    paper_id: str
    message: str


class PaperSummary(BaseModel):
    paper_id: str
    sha256_hash: str
    subject_name: str
    subject_code: str
    exam_type: str
    confirmed: bool


class PaperDetailResponse(BaseModel):
    paper_id: str
    sha256_hash: str
    confirmed: bool
    parsed_paper: ParsedPaper
    rubric: RubricResponse


class PaperDeleteResponse(BaseModel):
    paper_id: str
    message: str


# ---------------------------------------------------------------------------
# Evaluation Models
# ---------------------------------------------------------------------------

class StudentInfo(BaseModel):
    student_name: str
    roll_number: Optional[str] = None


class EvaluationSummary(BaseModel):
    """
    API storage + response model.
    total_attempted, total_marks_awarded, full_marks, percentage are all
    computed in Python — Gemini only generates overall_feedback.
    """
    full_marks: float
    total_attempted: float
    total_marks_awarded: float
    percentage: float
    overall_feedback: str


def build_evaluation_summary(
    overall_feedback: str,
    question_wise_evaluation: list,
    full_marks: float,
) -> "EvaluationSummary":
    """
    Compute summary fields from graded questions and paper metadata.
    - total_attempted : sum of maximum_marks for answered questions only
    - total_marks_awarded : sum of marks_awarded across answered questions
    - percentage : (total_marks_awarded / full_marks) * 100
    """
    total_attempted = sum(q.maximum_marks  for q in question_wise_evaluation)
    total_awarded   = sum(q.marks_awarded  for q in question_wise_evaluation)
    percentage      = round((total_awarded / full_marks * 100), 2) if full_marks > 0 else 0.0
    return EvaluationSummary(
        full_marks=full_marks,
        total_attempted=total_attempted,
        total_marks_awarded=total_awarded,
        percentage=percentage,
        overall_feedback=overall_feedback,
    )


class ConceptEvaluation(BaseModel):
    concept_name: str
    marks_allocated: float
    marks_awarded: float
    reason: str


class QuestionEvaluation(BaseModel):
    question_id: int
    maximum_marks: float
    marks_awarded: float          # computed: sum of concept marks_awarded
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
# Evaluation API Request / Response Models
# ---------------------------------------------------------------------------

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