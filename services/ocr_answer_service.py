"""
services/ocr_answer_service.py
-------------------------------
Extracts student answers from answer-sheet PDFs using Gemini.

Each extracted answer keeps:
* question_id: canonical paper question id when confidently matched;
               otherwise the raw visible label.
* raw_question_id: the exact visible label from the student's script.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import List, Optional, Sequence

from google import genai
from google.genai import types
from pydantic import BaseModel

from services.token_logger import log_token_usage


# ---------------------------------------------------------------------------
# Internal LLM schema
# ---------------------------------------------------------------------------

class _StudentInfo(BaseModel):
    student_name: str
    roll_number: Optional[str] = None


class _Answer(BaseModel):
    # Canonical paper question id when confidently matched; else raw label.
    question_id: str
    # Visible handwritten label captured from script.
    raw_question_id: Optional[str] = None
    answer_markdown: str


class _AnswerSchema(BaseModel):
    student_info: _StudentInfo
    answers: List[_Answer]


class QuestionContextItem(BaseModel):
    question_id: str
    question_text: str


# ---------------------------------------------------------------------------
# System prompt
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


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------

class OCRAnswerService:
    def __init__(self):
        api_key = os.getenv("GEMINI_API_KEY") or os.getenv("api_key")
        if not api_key:
            raise EnvironmentError("GEMINI_API_KEY environment variable not set.")
        self.client = genai.Client(api_key=api_key)
        self.model = os.getenv("OCR_MODEL", "gemini-2.0-flash-lite")
        self.system_prompt = _load_system_prompt()

    def _build_context_block(self, question_context: Sequence[QuestionContextItem]) -> str:
        """Inject canonical question-id context used for semantic id assignment."""
        lines = [
            "QUESTION_CONTEXT_FOR_CANONICAL_MAPPING",
            "Use only these canonical paper question IDs when assigning answers.question_id:",
        ]
        for item in question_context:
            qid = (item.question_id or "").strip()
            qtxt = (item.question_text or "").strip()
            if not qid:
                continue
            lines.append(f"- {qid}: {qtxt}")
        return "\n".join(lines)

    async def extract_answers(
        self,
        pdf_bytes: bytes,
        question_context: Optional[Sequence[QuestionContextItem]] = None,
    ) -> _AnswerSchema:
        """
        Returns raw parsed schema so orchestrator can access
        both student_info and answers.
        """
        context_items = [q for q in (question_context or []) if q.question_id.strip()]
        system_instruction = self.system_prompt
        if context_items:
            system_instruction = (
                f"{self.system_prompt}\n\n{self._build_context_block(context_items)}"
            )

        response = self.client.models.generate_content(
            model=self.model,
            config=types.GenerateContentConfig(
                thinking_config=types.ThinkingConfig(thinking_level="minimal"),
                media_resolution="MEDIA_RESOLUTION_HIGH",
                system_instruction=system_instruction,
                response_json_schema=_AnswerSchema.model_json_schema(),
            ),
            contents=[
                types.Part.from_bytes(
                    data=pdf_bytes,
                    mime_type="application/pdf",
                )
            ],
        )
        log_token_usage("OCR (answers)", self.model, response)
        return _AnswerSchema.model_validate_json(response.text)
