import os
from pathlib import Path
from google import genai
from google.genai import types
from pydantic import BaseModel
from typing import List, Optional

from models.schemas import StudentInfo


# ---------------------------------------------------------------------------
# Internal schemas for LLM structured output
# ---------------------------------------------------------------------------

class _StudentInfo(BaseModel):
    student_name: str
    roll_number: Optional[str] = None


class _Answer(BaseModel):
    question_id: int
    answer_markdown: str


class _AnswerSchema(BaseModel):
    student_info: _StudentInfo
    answers: List[_Answer]


# ---------------------------------------------------------------------------

_SYSTEM_PROMPT_PATH = Path("./instructions/ocr_answer_system_prompt.txt")

_DEFAULT_SYSTEM_PROMPT = """
You are an expert OCR system for student answer sheets.
Extract the student's name and roll number from the answer sheet header.
Then extract each answer exactly as written, preserving mathematical notation in LaTeX markdown.
Match each answer to its question number.
Return structured JSON matching the schema provided.
""".strip()


def _load_system_prompt() -> str:
    if _SYSTEM_PROMPT_PATH.exists():
        return _SYSTEM_PROMPT_PATH.read_text(encoding="utf-8")
    return _DEFAULT_SYSTEM_PROMPT


class OCRAnswerService:
    def __init__(self):
        api_key =  os.getenv("api_key")
        print(api_key)
        if not api_key:
            raise EnvironmentError("GEMINI_API_KEY environment variable not set.")
        
        self.client = genai.Client(api_key=api_key)
        self.model = os.getenv("OCR_MODEL")
        self.system_prompt = _load_system_prompt()

    async def extract_answers(self, pdf_bytes: bytes) -> _AnswerSchema:
        """
        Returns the raw parsed schema so the orchestrator can access
        both student_info and the answers list.
        """
        response = self.client.models.generate_content(
            model=self.model,
            config=types.GenerateContentConfig(
                thinking_config=types.ThinkingConfig(thinking_level="minimal"),
                media_resolution="MEDIA_RESOLUTION_HIGH",
                system_instruction=self.system_prompt,
                response_json_schema=_AnswerSchema.model_json_schema(),
            ),
            contents=[
                types.Part.from_bytes(
                    data=pdf_bytes,
                    mime_type="application/pdf",
                )
            ],
        )
        return _AnswerSchema.model_validate_json(response.text)