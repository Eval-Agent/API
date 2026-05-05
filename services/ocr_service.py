"""
services/ocr_service.py
-----------------------
Extracts a hierarchical question tree from a question-paper PDF using Gemini.

Key changes from the flat-list implementation
----------------------------------------------
* question_id is a **string** preserved exactly as printed.
* Questions are returned as a **tree** (_QuestionNode with children).
* ChoiceGroups capture either-or alternatives at any nesting level.
* The resulting ParsedPaper exposes a `.questions` property for
  backwards-compatible flat iteration over leaf nodes.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import List, Optional

from google import genai
from google.genai import types
from pydantic import BaseModel, Field

from models.paper import (
    ChoiceGroup,
    PaperMetadata,
    PaperSection,
    ParsedPaper,
    QuestionNode,
)
from services.token_logger import log_token_usage


# ---------------------------------------------------------------------------
# Internal LLM schema
# (mirrors models/paper.py but kept separate so we can freely evolve the
#  LLM contract without breaking the public API model)
# ---------------------------------------------------------------------------

class _Metadata(BaseModel):
    subject_name:   str
    subject_code:   str
    degree:         str
    stream:         str
    exam_type:      str
    set_no:         str
    full_marks:     str
    total_duration: float
    total_pages:    int


class _QuestionNode(BaseModel):
    """Recursive node — mirrors QuestionNode in models/paper.py."""
    question_id:       str
    display_id:        Optional[str]          = None
    question_markdown: str                    = ""
    max_score:         float                  = 0.0
    course_outcome:    Optional[str]          = None
    bloom_level:       Optional[str]          = None
    section_name:      Optional[str]          = None
    question_type:     str                    = "descriptive"
    node_role:         str                    = "question"
    options:           Optional[List[str]]    = None
    children:          List["_QuestionNode"]  = Field(default_factory=list)
    choice_group_id:   Optional[str]          = None
    is_or_alternative: bool                   = False

_QuestionNode.model_rebuild()


class _ChoiceGroup(BaseModel):
    choice_group_id: str
    question_ids:    List[str]
    required_count:  int  = 1
    label:           Optional[str] = None


class _Section(BaseModel):
    section_name:       str
    required_count:     int
    marks_per_question: float
    question_ids:       List[str]


class _PaperSchema(BaseModel):
    metadata:      _Metadata
    question_tree: List[_QuestionNode] = Field(default_factory=list)
    sections:      List[_Section]      = Field(default_factory=list)
    choice_groups: List[_ChoiceGroup]  = Field(default_factory=list)


# ---------------------------------------------------------------------------
# System prompt
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT_PATH = Path("./instructions/ocr-q_system_prompt.txt")

_DEFAULT_SYSTEM_PROMPT = """
You are an expert OCR system for academic question papers.
Extract all questions from the PDF exactly as written, preserving mathematical
notation in LaTeX markdown.  Represent nested sub-questions as children in the
question_tree.  Return structured JSON matching the schema provided.
""".strip()


def _load_system_prompt() -> str:
    if _SYSTEM_PROMPT_PATH.exists():
        return _SYSTEM_PROMPT_PATH.read_text(encoding="utf-8")
    # return _DEFAULT_SYSTEM_PROMPT


# ---------------------------------------------------------------------------
# Conversion helpers
# ---------------------------------------------------------------------------

def _convert_node(n: _QuestionNode) -> QuestionNode:
    return QuestionNode(
        question_id=n.question_id,
        display_id=n.display_id or None,
        question_markdown=n.question_markdown,
        max_score=n.max_score,
        course_outcome=n.course_outcome or None,
        bloom_level=n.bloom_level or None,
        section_name=n.section_name or None,
        question_type=n.question_type or "descriptive",
        node_role=n.node_role or "question",
        options=n.options or None,
        children=[_convert_node(c) for c in n.children],
        choice_group_id=n.choice_group_id or None,
        is_or_alternative=n.is_or_alternative,
    )


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------

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
                response_json_schema=_PaperSchema.model_json_schema(),
            ),
            contents=[
                types.Part.from_bytes(
                    data=pdf_bytes,
                    mime_type="application/pdf",
                )
            ],
        )

        log_token_usage("OCR (questions)", self.model, response)
        parsed = _PaperSchema.model_validate_json(response.text)

        question_tree = [_convert_node(n) for n in parsed.question_tree]

        sections = [
            PaperSection(
                section_name=s.section_name,
                required_count=s.required_count,
                marks_per_question=s.marks_per_question,
                question_ids=s.question_ids,
            )
            for s in parsed.sections
        ]

        choice_groups = [
            ChoiceGroup(
                choice_group_id=cg.choice_group_id,
                question_ids=cg.question_ids,
                required_count=cg.required_count,
                label=cg.label,
            )
            for cg in parsed.choice_groups
        ]

        return ParsedPaper(
            metadata=PaperMetadata(**parsed.metadata.model_dump()),
            question_tree=question_tree,
            sections=sections,
            choice_groups=choice_groups,
        )