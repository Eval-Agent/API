"""
services/rubric_service.py
--------------------------
Generates marking rubrics from OCR'd question papers using Gemini.

Key changes from the flat-list implementation
----------------------------------------------
* question_id is a **string** throughout.
* The rubric is generated for **leaf questions only** (nodes that students
  actually answer).  Group/parent nodes are not rubricised.
* Either-or alternatives (choice_group_id set) each get a full rubric entry
  because we don't know in advance which branch a student will choose.
* Bloom's level is normalised from the printed bloom_level on the leaf node.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Dict, List, Optional
from enum import Enum

from google import genai
from google.genai import types
from pydantic import BaseModel

from services.token_logger import log_token_usage
from models.paper import ParsedPaper, QuestionNode
from models.paper import Strictness
from models.rubric import (
    Concept,
    ExpectedDepth,
    PartialMarkingRule,
    Rubric,
    RubricQuestion,
)


# ---------------------------------------------------------------------------
# Internal LLM schema
# ---------------------------------------------------------------------------

class _ExpectedDepth(str, Enum):
    remember   = "remember"
    understand = "understand"
    apply      = "apply"
    analyze    = "analyze"
    evaluate   = "evaluate"
    create     = "create"


class _Concept(BaseModel):
    concept_name:    str
    description:     str
    keywords:        List[str]
    marks_allocated: float
    mandatory:       bool


class _PartialMarkingRule(BaseModel):
    keyword_only_percentage:       float
    partial_explanation_percentage: float


class _RubricQuestion(BaseModel):
    question_id:          str
    question_text:        str
    total_marks:          float
    question_type:        str                         = "descriptive"
    expected_depth:       Optional[_ExpectedDepth]    = None
    concepts:             Optional[List[_Concept]]    = None
    partial_marking_rule: Optional[_PartialMarkingRule] = None
    correct_options:      Optional[List[str]]         = None
    is_multi_select:      bool                        = False


class _RubricSchema(BaseModel):
    questions: List[_RubricQuestion]


# ---------------------------------------------------------------------------
# System prompt
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT_PATH = Path("./instructions/rubric_system_prompt.txt")


def _load_system_prompt() -> str:
    if not _SYSTEM_PROMPT_PATH.exists():
        raise FileNotFoundError(
            f"Rubric system prompt not found at {_SYSTEM_PROMPT_PATH}."
        )
    return _SYSTEM_PROMPT_PATH.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# Strictness instructions
# ---------------------------------------------------------------------------

_STRICTNESS_INSTRUCTIONS: Dict[Strictness, str] = {
    Strictness.easy: (
        "STRICTNESS: EASY — Be lenient. Award marks generously. "
        "Partial credit should be given for any reasonable attempt. "
        "Set keyword_only_percentage to 75 and partial_explanation_percentage to 90. "
        "Mark few concepts as mandatory. Accept informal or incomplete explanations."
    ),
    Strictness.medium: (
        "STRICTNESS: MEDIUM — Apply balanced marking. "
        "Award full marks for complete correct answers, partial marks for partially correct ones. "
        "Set keyword_only_percentage to 50 and partial_explanation_percentage to 75. "
        "Core concepts should be mandatory, supporting ones optional."
    ),
    Strictness.hard: (
        "STRICTNESS: HARD — Apply strict marking. "
        "Require precise terminology and thorough explanations for full marks. "
        "Set keyword_only_percentage to 30 and partial_explanation_percentage to 60. "
        "Most concepts should be mandatory. Vague or imprecise answers should score low."
    ),
    Strictness.extreme: (
        "STRICTNESS: EXTREME — Apply the most rigorous marking possible. "
        "Only award full marks for technically precise, complete, and well-structured answers. "
        "Set keyword_only_percentage to 10 and partial_explanation_percentage to 40. "
        "All key concepts must be mandatory. Any missing detail should result in significant deduction."
    ),
}


# ---------------------------------------------------------------------------
# Bloom's level normaliser
# ---------------------------------------------------------------------------

_LEVEL_NUM_MAP: Dict[str, str] = {
    "1": "remember",
    "2": "understand",
    "3": "apply",
    "4": "analyze",
    "5": "evaluate",
    "6": "create",
}

_BLOOM_TEXT_MAP: Dict[str, str] = {
    "remember":      "remember",
    "recall":        "remember",
    "knowledge":     "remember",
    "understand":    "understand",
    "understanding": "understand",
    "comprehension": "understand",
    "describe":      "understand",
    "apply":         "apply",
    "application":   "apply",
    "analyse":       "analyze",
    "analyze":       "analyze",
    "analysis":      "analyze",
    "evaluate":      "evaluate",
    "evaluation":    "evaluate",
    "create":        "create",
    "synthesis":     "create",
    "design":        "create",
}


def _normalize_bloom_level(raw: Optional[str]) -> Optional[str]:
    if not raw:
        return None
    v = raw.strip().lower()
    if v.startswith("l") and v[1:] in _LEVEL_NUM_MAP:
        return _LEVEL_NUM_MAP[v[1:]]
    if v.startswith("btl") and v[3:] in _LEVEL_NUM_MAP:
        return _LEVEL_NUM_MAP[v[3:]]
    return _BLOOM_TEXT_MAP.get(v, None)


# ---------------------------------------------------------------------------
# Prompt builder — flat list of leaf questions for Gemini
# ---------------------------------------------------------------------------

def _build_rubric_input(parsed_paper: ParsedPaper) -> str:
    """
    Serialise only the leaf questions that need a rubric entry.
    Group/parent nodes are excluded; either-or alternatives are included
    (we rubricise all branches).
    """
    import json

    leaf_questions = []
    for leaf in parsed_paper.questions:   # .questions = all leaves DFS
        leaf_questions.append({
            "question_id":       leaf.question_id,
            "question_markdown": leaf.question_markdown,
            "max_score":         leaf.max_score,
            "course_outcome":    leaf.course_outcome,
            "bloom_level":       leaf.bloom_level,
            "section_name":      leaf.section_name,
            "question_type":     leaf.question_type,
            "options":           leaf.options,
            "is_or_alternative": leaf.is_or_alternative,
            "choice_group_id":   leaf.choice_group_id,
        })

    return json.dumps({
        "metadata": parsed_paper.metadata.model_dump(),
        "questions": leaf_questions,
    }, ensure_ascii=False, indent=2)


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------

class RubricService:
    def __init__(self):
        api_key = os.getenv("GEMINI_API_KEY") or os.getenv("api_key")
        if not api_key:
            raise EnvironmentError("GEMINI_API_KEY environment variable not set.")
        self.client = genai.Client(api_key=api_key)
        self.model = os.getenv("RUBRIC_MODEL", "gemini-2.0-flash")
        self.base_system_prompt = _load_system_prompt()

    def _build_system_prompt(self, strictness: Strictness) -> str:
        return self.base_system_prompt + "\n\n" + _STRICTNESS_INSTRUCTIONS[strictness]

    async def generate_rubric(
        self,
        parsed_paper: ParsedPaper,
        strictness: Strictness = Strictness.medium,
    ) -> Rubric:
        system_prompt = self._build_system_prompt(strictness)

        # Build Bloom's override map: question_id → canonical depth
        bloom_override: Dict[str, str] = {}
        for leaf in parsed_paper.questions:
            canonical = _normalize_bloom_level(leaf.bloom_level)
            if canonical:
                bloom_override[leaf.question_id] = canonical

        # Build leaf lookup for question_type + options
        leaf_lookup: Dict[str, QuestionNode] = {
            leaf.question_id: leaf for leaf in parsed_paper.questions
        }

        rubric_input = _build_rubric_input(parsed_paper)

        response = self.client.models.generate_content(
            model=self.model,
            config=types.GenerateContentConfig(
                thinking_config=types.ThinkingConfig(thinking_level="medium"),
                system_instruction=system_prompt,
                response_json_schema=_RubricSchema.model_json_schema(),
            ),
            contents=rubric_input,
        )

        log_token_usage("Rubric generation", self.model, response)
        parsed = _RubricSchema.model_validate_json(response.text)

        rubric_questions: List[RubricQuestion] = []
        for q in parsed.questions:
            leaf = leaf_lookup.get(q.question_id)
            q_type = (leaf.question_type if leaf else None) or q.question_type or "descriptive"

            if q_type == "mcq":
                rubric_questions.append(
                    RubricQuestion(
                        question_id=q.question_id,
                        question_text=q.question_text,
                        total_marks=q.total_marks,
                        question_type="mcq",
                        correct_options=q.correct_options or [],
                        is_multi_select=q.is_multi_select,
                        options=leaf.options if leaf else None,
                        expected_depth=None,
                        concepts=None,
                        partial_marking_rule=None,
                    )
                )
            else:
                # Resolve expected_depth: paper-printed bloom > Gemini's choice
                raw_depth = q.expected_depth.value if q.expected_depth else None
                resolved_depth = bloom_override.get(q.question_id, raw_depth) or "remember"

                rubric_questions.append(
                    RubricQuestion(
                        question_id=q.question_id,
                        question_text=q.question_text,
                        total_marks=q.total_marks,
                        question_type="descriptive",
                        expected_depth=ExpectedDepth(resolved_depth),
                        concepts=(
                            [Concept(**c.model_dump()) for c in q.concepts]
                            if q.concepts else []
                        ),
                        partial_marking_rule=(
                            PartialMarkingRule(**q.partial_marking_rule.model_dump())
                            if q.partial_marking_rule
                            else PartialMarkingRule(
                                keyword_only_percentage=0.5,
                                partial_explanation_percentage=0.75,
                            )
                        ),
                        correct_options=None,
                    )
                )

        return Rubric(questions=rubric_questions)