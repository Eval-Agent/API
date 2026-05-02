import os
from pathlib import Path
from google import genai
from google.genai import types
from pydantic import BaseModel
from typing import List, Optional

from models.schemas import ParsedPaper, PaperMetadata, ParsedQuestion, PaperSection
from services.token_logger import log_token_usage


# ---------------------------------------------------------------------------
# Internal schema for LLM structured output
# ---------------------------------------------------------------------------

class _Metadata(BaseModel):
    subject_name: str
    subject_code: str
    degree: str
    stream: str
    exam_type: str
    set_no: str
    full_marks: str
    total_duration: float
    total_pages: int


class _Question(BaseModel):
    question_id: int
    question_markdown: str
    max_score: int
    course_outcome: Optional[str] = None
    bloom_level: Optional[str] = None
    section_name: Optional[str] = None   # e.g. "Part A", "Part B", "Part C"
    question_type: str = "descriptive"   # "mcq" | "descriptive"
    options: Optional[List[str]] = None  # MCQ options exactly as printed e.g. ["A. ...", "B. ..."]


class _Section(BaseModel):
    """
    One answerable section of the paper.
    required_count  = N  in "Answer any N out of M questions"
    marks_per_question = marks each question in this section carries
    question_ids    = list of question_ids belonging to this section
    """
    section_name:       str
    required_count:     int
    marks_per_question: float
    question_ids:       List[int]


class _QuizSchema(BaseModel):
    metadata:  _Metadata
    questions: List[_Question]
    sections:  List[_Section] = []


# ---------------------------------------------------------------------------

_SYSTEM_PROMPT_PATH = Path("./instructions/ocr-q_system_prompt.txt")

_DEFAULT_SYSTEM_PROMPT = """
You are an expert OCR system for academic question papers.
Extract all questions from the PDF exactly as written, preserving mathematical notation in LaTeX markdown.
Return structured JSON matching the schema provided.
""".strip()


def _load_system_prompt() -> str:
    if _SYSTEM_PROMPT_PATH.exists():
        return _SYSTEM_PROMPT_PATH.read_text(encoding="utf-8")
    return _DEFAULT_SYSTEM_PROMPT


class OCRService:
    def __init__(self):
        api_key = os.getenv("GEMINI_API_KEY") or os.getenv("api_key")
        if not api_key:
            raise EnvironmentError("GEMINI_API_KEY environment variable not set.")
        self.client = genai.Client(api_key=api_key)
        self.model = os.getenv("OCR_MODEL", "gemini-2.0-flash-lite")
        self.system_prompt = _load_system_prompt()

    async def extract_questions(self, pdf_bytes: bytes) -> ParsedPaper:
        response = self.client.models.generate_content(
            model=self.model,
            config=types.GenerateContentConfig(
                thinking_config=types.ThinkingConfig(thinking_level="minimal"),
                media_resolution="MEDIA_RESOLUTION_HIGH",
                system_instruction=self.system_prompt,
                response_json_schema=_QuizSchema.model_json_schema(),
            ),
            contents=[
                types.Part.from_bytes(
                    data=pdf_bytes,
                    mime_type="application/pdf",
                )
            ],
        )

        log_token_usage("OCR (questions)", self.model, response)
        parsed = _QuizSchema.model_validate_json(response.text)

        questions = [
            ParsedQuestion(
                question_id=q.question_id,
                question_markdown=q.question_markdown,
                max_score=q.max_score,
                course_outcome=q.course_outcome or None,
                bloom_level=q.bloom_level or None,
                section_name=q.section_name or None,
                question_type=q.question_type or "descriptive",
                options=q.options or None,
            )
            for q in parsed.questions
        ]

        sections = [
            PaperSection(
                section_name=s.section_name,
                required_count=s.required_count,
                marks_per_question=s.marks_per_question,
                question_ids=s.question_ids,
            )
            for s in parsed.sections
        ]

        return ParsedPaper(
            metadata=PaperMetadata(**parsed.metadata.model_dump()),
            questions=questions,
            sections=sections,
        )