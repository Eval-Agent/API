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
    total_questions: int
    total_marks: int
    questions: List[RubricQuestion]


# ---------------------------------------------------------------------------
# API Request / Response Models
# ---------------------------------------------------------------------------

class PaperUploadResponse(BaseModel):
    paper_id: str
    sha256_hash: str
    is_duplicate: bool
    parsed_paper: ParsedPaper
    rubric: Rubric
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
    rubric: Rubric


class PaperDeleteResponse(BaseModel):
    paper_id: str
    message: str