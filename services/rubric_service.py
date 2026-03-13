import os
from pathlib import Path
from google import genai
from google.genai import types
from pydantic import BaseModel
from typing import List
from enum import Enum

from models.schemas import (
    ParsedPaper,
    Rubric,
    RubricQuestion,
    Concept,
    PartialMarkingRule,
    ExpectedDepth,
    Strictness,
)


# ---------------------------------------------------------------------------
# Internal schema for LLM structured output
# ---------------------------------------------------------------------------

class _ExpectedDepth(str, Enum):
    definition = "definition"
    short_explanation = "short_explanation"
    detailed_explanation = "detailed_explanation"
    analytical = "analytical"


class _Concept(BaseModel):
    concept_name: str
    description: str
    keywords: List[str]
    marks_allocated: float
    mandatory: bool


class _PartialMarkingRule(BaseModel):
    keyword_only_percentage: float
    partial_explanation_percentage: float


class _RubricQuestion(BaseModel):
    question_id: int
    question_text: str
    total_marks: float
    expected_depth: _ExpectedDepth
    concepts: List[_Concept]
    partial_marking_rule: _PartialMarkingRule


class _RubricSchema(BaseModel):
    questions: List[_RubricQuestion]


# ---------------------------------------------------------------------------

_SYSTEM_PROMPT_PATH = Path("./instructions/rubric_system_prompt.txt")

_DEFAULT_SYSTEM_PROMPT = """
You are an expert academic examiner.
Given a parsed question paper in JSON format, generate a detailed marking rubric for each question.
For every question, identify key concepts, mandatory keywords, expected answer depth, marks per concept, and partial marking rules.
Return structured JSON matching the schema provided.
""".strip()

_STRICTNESS_INSTRUCTIONS = {
    Strictness.easy: (
        "STRICTNESS: EASY — Be lenient. Award marks generously. "
        "Partial credit should be given for any reasonable attempt. "
        "Set keyword_only_percentage to 0.75 and partial_explanation_percentage to 0.90. "
        "Mark few concepts as mandatory. Accept informal or incomplete explanations."
    ),
    Strictness.medium: (
        "STRICTNESS: MEDIUM — Apply balanced marking. "
        "Award full marks for complete correct answers, partial marks for partially correct ones. "
        "Set keyword_only_percentage to 0.50 and partial_explanation_percentage to 0.75. "
        "Core concepts should be mandatory, supporting ones optional."
    ),
    Strictness.hard: (
        "STRICTNESS: HARD — Apply strict marking. "
        "Require precise terminology and thorough explanations for full marks. "
        "Set keyword_only_percentage to 0.30 and partial_explanation_percentage to 0.60. "
        "Most concepts should be mandatory. Vague or imprecise answers should score low."
    ),
    Strictness.extreme: (
        "STRICTNESS: EXTREME — Apply the most rigorous marking possible. "
        "Only award full marks for technically precise, complete, and well-structured answers. "
        "Set keyword_only_percentage to 0.10 and partial_explanation_percentage to 0.40. "
        "All key concepts must be mandatory. Any missing detail should result in significant deduction."
    ),
}


def _load_system_prompt() -> str:
    if _SYSTEM_PROMPT_PATH.exists():
        return _SYSTEM_PROMPT_PATH.read_text(encoding="utf-8")
    return _DEFAULT_SYSTEM_PROMPT


class RubricService:
    def __init__(self):
        api_key = os.getenv("GEMINI_API_KEY") or os.getenv("api_key")
        if not api_key:
            raise EnvironmentError("GEMINI_API_KEY environment variable not set.")
        self.client = genai.Client(api_key=api_key)
        self.model = os.getenv("RUBRIC_MODEL", "gemini-2.0-flash")
        self.base_system_prompt = _load_system_prompt()

    def _build_prompt(self, strictness: Strictness) -> str:
        return self.base_system_prompt + "\n\n" + _STRICTNESS_INSTRUCTIONS[strictness]

    async def generate_rubric(
        self,
        parsed_paper: ParsedPaper,
        strictness: Strictness = Strictness.medium,
    ) -> Rubric:
        system_prompt = self._build_prompt(strictness)

        response = self.client.models.generate_content(
            model=self.model,
            config=types.GenerateContentConfig(
                thinking_config=types.ThinkingConfig(thinking_level="medium"),
                system_instruction=system_prompt,
                response_json_schema=_RubricSchema.model_json_schema(),
            ),
            contents=parsed_paper.model_dump_json(),
        )

        parsed = _RubricSchema.model_validate_json(response.text)

        return Rubric(
            questions=[
                RubricQuestion(
                    question_id=q.question_id,
                    question_text=q.question_text,
                    total_marks=q.total_marks,
                    expected_depth=ExpectedDepth(q.expected_depth.value),
                    concepts=[Concept(**c.model_dump()) for c in q.concepts],
                    partial_marking_rule=PartialMarkingRule(
                        **q.partial_marking_rule.model_dump()
                    ),
                )
                for q in parsed.questions
            ],
        )