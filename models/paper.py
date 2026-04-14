from pydantic import BaseModel
from typing import List, Optional
from enum import Enum

from models.rubric import Rubric, RubricResponse


# ---------------------------------------------------------------------------
# Strictness
# ---------------------------------------------------------------------------

class Strictness(str, Enum):
    easy    = "easy"
    medium  = "medium"
    hard    = "hard"
    extreme = "extreme"


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
    course_outcome: Optional[str] = None   # e.g. "CO1", "CO2" — extracted from paper if printed
    bloom_level: Optional[str] = None      # e.g. "Remember", "Analyze" — extracted from paper if printed
    section_name: Optional[str] = None     # e.g. "Part A", "Part B" — which section this question belongs to


class ParsedPaper(BaseModel):
    metadata:  PaperMetadata
    questions: List[ParsedQuestion]
    sections:  List["PaperSection"] = []   # empty for papers without explicit sections


# ---------------------------------------------------------------------------
# Paper API Request / Response Models
# ---------------------------------------------------------------------------

class PaperOcrResponse(BaseModel):
    """Returned after POST /upload — OCR only, no rubric yet."""
    paper_id: str
    sha256_hash: str
    is_duplicate: bool
    parsed_paper: ParsedPaper
    message: str


class PaperUploadResponse(BaseModel):
    """Kept for backwards compatibility. rubric is None until generated."""
    paper_id: str
    sha256_hash: str
    is_duplicate: bool
    parsed_paper: ParsedPaper
    rubric: Optional[RubricResponse] = None
    message: str


class RubricGenerateRequest(BaseModel):
    """Body for POST /papers/{paper_id}/rubric:generate — paper_id is in the URL path."""
    strictness: Strictness = Strictness.medium


class RubricGenerateResponse(BaseModel):
    paper_id: str
    strictness: Strictness
    rubric: RubricResponse
    message: str


class PaperConfirmRequest(BaseModel):
    """
    Body for POST /papers/{paper_id}:confirm — paper_id is in the URL path.
    Send the final (possibly edited) parsed_paper and rubric.
    """
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
    has_rubric: bool


class PaperDetailResponse(BaseModel):
    paper_id: str
    sha256_hash: str
    confirmed: bool
    parsed_paper: ParsedPaper
    rubric: Optional[RubricResponse] = None


class PaperDeleteResponse(BaseModel):
    paper_id: str
    message: str
    ocr_results_deleted: int = 0
    evaluations_deleted: int = 0



# ---------------------------------------------------------------------------
# Paper Sections — "Answer any N of M questions"
# ---------------------------------------------------------------------------

class PaperSection(BaseModel):
    """
    Represents one section of a question paper, e.g. "Part A (2 x 5)".
    required_count      : number of questions the student must answer (N in "any N of M")
    marks_per_question  : marks each question in this section carries
    question_ids        : ordered list of question_ids belonging to this section
    """
    section_name:       str        # e.g. "Part A", "Part B", "Part C"
    required_count:     int        # N — number of questions to count
    marks_per_question: float      # marks each question carries
    question_ids:       List[int]  # question_ids that belong to this section


# Resolve the forward reference used in ParsedPaper.sections
ParsedPaper.model_rebuild()