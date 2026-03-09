import os
from pathlib import Path
from google import genai
from google.genai import types
from pydantic import BaseModel
from typing import List

from models.schemas import ParsedPaper, PaperMetadata, ParsedQuestion


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


class _QuizSchema(BaseModel):
    metadata: _Metadata
    questions: List[_Question]


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
        self.model = os.getenv("OCR_MODEL", "gemini-3.1-flash-lite-preview")
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

        parsed = _QuizSchema.model_validate_json(response.text)

        return ParsedPaper(
            metadata=PaperMetadata(**parsed.metadata.model_dump()),
            questions=[
                ParsedQuestion(**q.model_dump()) for q in parsed.questions
            ],
        )
