import os
from pathlib import Path
from google import genai
from google.genai import types
from pydantic import BaseModel
from typing import List, Optional
from enum import Enum

from services.token_logger import log_token_usage
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
    remember   = "remember"
    understand = "understand"
    apply      = "apply"
    analyze    = "analyze"
    evaluate   = "evaluate"
    create     = "create"


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


def _load_system_prompt() -> str:
    if not _SYSTEM_PROMPT_PATH.exists():
        raise FileNotFoundError(
            f"Rubric system prompt not found at {_SYSTEM_PROMPT_PATH}. "
            "Please ensure instructions/rubric_system_prompt.txt exists."
        )
    return _SYSTEM_PROMPT_PATH.read_text(encoding="utf-8")


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


# ---------------------------------------------------------------------------
# Bloom's level normaliser
# Maps any printed form from the question paper to a canonical ExpectedDepth.
# Returns None if the value cannot be mapped — Gemini's choice is used instead.
# ---------------------------------------------------------------------------

# Abbreviated level maps: L1-L6 and BTL1-BTL6 follow Bloom's order
_LEVEL_NUM_MAP: dict = {
    "1": "remember",
    "2": "understand",
    "3": "apply",
    "4": "analyze",
    "5": "evaluate",
    "6": "create",
}

# Full / common variant spellings → canonical value
_BLOOM_TEXT_MAP: dict = {
    "remember":    "remember",
    "recall":      "remember",
    "knowledge":   "remember",
    "understand":  "understand",
    "understanding": "understand",
    "comprehension": "understand",
    "describe":    "understand",
    "apply":       "apply",
    "application": "apply",
    "analyse":     "analyze",
    "analyze":     "analyze",
    "analysis":    "analyze",
    "evaluate":    "evaluate",
    "evaluation":  "evaluate",
    "create":      "create",
    "synthesis":   "create",
    "design":      "create",
}


def _normalize_bloom_level(raw: Optional[str]) -> Optional[str]:
    """
    Convert any printed Bloom's level string to a canonical ExpectedDepth value.

    Handles:
      Full words  : "Remember", "Analyse", "Understand"
      L-notation  : "L1", "L3", "l6"
      BTL-notation: "BTL1", "BTL4", "btl2"
      Returns None if unrecognised — Gemini's output is used as fallback.
    """
    if not raw:
        return None
    v = raw.strip().lower()

    # L1–L6
    if v.startswith("l") and v[1:] in _LEVEL_NUM_MAP:
        return _LEVEL_NUM_MAP[v[1:]]

    # BTL1–BTL6
    if v.startswith("btl") and v[3:] in _LEVEL_NUM_MAP:
        return _LEVEL_NUM_MAP[v[3:]]

    # Full word / variant
    return _BLOOM_TEXT_MAP.get(v, None)


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

        # Build a lookup of question_id → canonical depth from bloom_level printed
        # on the question paper. Gemini's output is overridden where this is present.
        bloom_override: dict = {}
        for pq in parsed_paper.questions:
            canonical = _normalize_bloom_level(getattr(pq, "bloom_level", None))
            if canonical:
                bloom_override[pq.question_id] = canonical

        response = self.client.models.generate_content(
            model=self.model,
            config=types.GenerateContentConfig(
                thinking_config=types.ThinkingConfig(thinking_level="medium"),
                system_instruction=system_prompt,
                response_json_schema=_RubricSchema.model_json_schema(),
            ),
            contents=parsed_paper.model_dump_json(),
        )

        log_token_usage("Rubric generation", self.model, response)
        parsed = _RubricSchema.model_validate_json(response.text)

        return Rubric(
            questions=[
                RubricQuestion(
                    question_id=q.question_id,
                    question_text=q.question_text,
                    total_marks=q.total_marks,
                    # Use printed bloom_level if available, otherwise trust Gemini
                    expected_depth=ExpectedDepth(
                        bloom_override.get(q.question_id, q.expected_depth.value)
                    ),
                    concepts=[Concept(**c.model_dump()) for c in q.concepts],
                    partial_marking_rule=PartialMarkingRule(
                        **q.partial_marking_rule.model_dump()
                    ),
                )
                for q in parsed.questions
            ],
        )