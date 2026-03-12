from pydantic import BaseModel
from typing import List

from models.rubric import Rubric, RubricResponse


# ---------------------------------------------------------------------------
# Paper OCR Models
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
# Paper API Request / Response Models
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