"""
services/evaluator_service.py
-----------------------------
Evaluates student answers against a rubric using Gemini.

Key changes from the flat-list implementation
----------------------------------------------
* question_id is a **string** throughout.
* Either-or choice groups: only the branch the student actually answered
  is evaluated; the unchosen branch is skipped entirely.
* Best-N section selection works on string IDs.
* MCQ deterministic scoring unchanged except for string IDs.
* Prompt builder uses ParsedPaper.questions (leaf DFS) so all question
  formats (nested, alphanumeric IDs) are handled transparently.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Dict, List, Optional, Set
from enum import Enum

from google import genai
from google.genai import types
from pydantic import BaseModel

from services.token_logger import log_token_usage
from models.paper import ParsedPaper
from models.rubric import Rubric, RubricResponse
from models.evaluation import (
    ConceptEvaluation,
    ConceptVerdict,
    EvaluationReport,
    ExtractedAnswer,
    QuestionEvaluation,
    StudentInfo,
    _bloom_outcome,
    build_evaluation_summary,
)


# ---------------------------------------------------------------------------
# Internal LLM schema
# ---------------------------------------------------------------------------

class _EvaluationSummary(BaseModel):
    overall_feedback: str


class _ConceptVerdict(str, Enum):
    correct   = "correct"
    partial   = "partial"
    incorrect = "incorrect"


class _ConceptEvaluation(BaseModel):
    concept_name: str
    verdict:      _ConceptVerdict
    reason:       str


class _QuestionEvaluation(BaseModel):
    question_id:            str     # ← string
    maximum_marks:          float
    concept_evaluations:    List[_ConceptEvaluation]
    justification:          str
    strengths:              Optional[List[str]] = None
    areas_for_improvement:  Optional[List[str]] = None


class _EvaluationReport(BaseModel):
    evaluation_summary:       _EvaluationSummary
    question_wise_evaluation: List[_QuestionEvaluation]


# ---------------------------------------------------------------------------
# System prompt
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT_PATH = Path("./instructions/eval_system_prompt.txt")


def _load_system_prompt() -> str:
    if not _SYSTEM_PROMPT_PATH.exists():
        raise FileNotFoundError(
            f"Eval system prompt not found at {_SYSTEM_PROMPT_PATH}."
        )
    return _SYSTEM_PROMPT_PATH.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# Prompt builder
# ---------------------------------------------------------------------------

def _build_evaluation_prompt(
    parsed_paper: ParsedPaper,
    rubric:       Rubric | RubricResponse,
    answers:      List[ExtractedAnswer],
    student_info: StudentInfo,
) -> str:
    """
    Build the Gemini evaluation prompt.

    Only questions that the student actually answered (present in `answers`)
    are included.  Group/parent nodes never appear because parsed_paper.questions
    returns only leaves.
    """
    rubric_lookup  = {q.question_id: q for q in rubric.questions}
    answer_lookup  = {a.question_id: a.answer_markdown for a in answers}

    lines = ["# Student Evaluation Data\n"]
    lines.append(f"**Student Name:** {student_info.student_name}")
    lines.append(f"**Roll Number:** {student_info.roll_number or 'N/A'}\n")

    for leaf in parsed_paper.questions:    # DFS leaf order
        q_id = leaf.question_id
        if q_id not in answer_lookup:
            continue

        rubric_q = rubric_lookup.get(q_id)
        lines.append(f"## Question ID: {q_id}")
        if leaf.display_id:
            lines.append(f"**Display ID:** {leaf.display_id}")
        lines.append(f"**Max Score:** {leaf.max_score}\n")

        lines.append("### Question")
        lines.append(f"{leaf.question_markdown}\n")

        lines.append("### Student Answer")
        lines.append(f"{answer_lookup[q_id]}\n")

        lines.append("### Rubric")
        if rubric_q and rubric_q.question_type != "mcq":
            lines.append(f"**Expected Depth:** {rubric_q.expected_depth}\n")
            lines.append("#### Concepts")
            for concept in (rubric_q.concepts or []):
                lines.append(f"- **Concept:** {concept.concept_name}")
                lines.append(f"  - Description: {concept.description}")
                lines.append(f"  - Keywords: {', '.join(concept.keywords)}")
                lines.append(f"  - Mandatory: {concept.mandatory}")
        elif rubric_q and rubric_q.question_type == "mcq":
            lines.append("*MCQ — scored deterministically, not by this prompt.*\n")
        else:
            lines.append("*No rubric available for this question.*\n")

        lines.append("---\n")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------

class EvaluatorService:
    def __init__(self):
        api_key = os.getenv("GEMINI_API_KEY") or os.getenv("api_key")
        if not api_key:
            raise EnvironmentError("GEMINI_API_KEY environment variable not set.")
        self.client = genai.Client(api_key=api_key)
        self.model = os.getenv("EVAL_MODEL", "gemini-2.0-flash")
        self.system_prompt = _load_system_prompt()

    async def evaluate(
        self,
        parsed_paper: ParsedPaper,
        rubric:       Rubric | RubricResponse,
        answers:      List[ExtractedAnswer],
        student_info: StudentInfo,
        full_marks:   float,
    ) -> EvaluationReport:

        prompt = _build_evaluation_prompt(parsed_paper, rubric, answers, student_info)

        response = self.client.models.generate_content(
            model=self.model,
            config=types.GenerateContentConfig(
                system_instruction=self.system_prompt,
                temperature=0,
                top_p=0,
                top_k=1,
                seed=42,
                response_json_schema=_EvaluationReport.model_json_schema(),
            ),
            contents=prompt,
        )

        log_token_usage("Evaluation", self.model, response)
        parsed = _EvaluationReport.model_validate_json(response.text)

        # ------------------------------------------------------------------
        # Build lookups
        # ------------------------------------------------------------------
        rubric_q_lookup: Dict[str, object] = {rq.question_id: rq for rq in rubric.questions}

        # course_outcome from parsed paper leaves
        co_lookup: Dict[str, Optional[str]] = {
            leaf.question_id: leaf.course_outcome
            for leaf in parsed_paper.questions
        }

        answer_lookup: Dict[str, str] = {
            a.question_id: a.answer_markdown.strip() for a in answers
        }

        # IDs of MCQ questions (scored in Python, not by Gemini)
        mcq_ids: Set[str] = {
            rq.question_id
            for rq in rubric.questions
            if rq.question_type == "mcq"
        }

        # ------------------------------------------------------------------
        # Determine which OR-alternative branches the student actually answered.
        # For each choice_group, only evaluate the branch(es) that have an
        # answer; the rest are silently skipped.
        # ------------------------------------------------------------------
        answered_ids: Set[str] = set(answer_lookup.keys())

        # Set of leaf question_ids that should be skipped (unanswered OR branch)
        skip_ids: Set[str] = set()
        if parsed_paper.choice_groups:
            for cg in parsed_paper.choice_groups:
                answered_in_group = [qid for qid in cg.question_ids if qid in answered_ids]
                unanswered_in_group = [qid for qid in cg.question_ids if qid not in answered_ids]
                # Skip unanswered branches entirely
                skip_ids.update(unanswered_in_group)

        # ------------------------------------------------------------------
        # Helper: concept-level mark computation
        # ------------------------------------------------------------------
        def _concept_marks(
            verdict:         _ConceptVerdict,
            marks_allocated: float,
            partial_pct:     float,
        ) -> float:
            if verdict == _ConceptVerdict.correct:
                return marks_allocated
            elif verdict == _ConceptVerdict.partial:
                return round(marks_allocated * partial_pct, 2)
            else:
                return 0.0

        question_wise: List[QuestionEvaluation] = []

        # ------------------------------------------------------------------
        # MCQ scoring — pure Python
        # ------------------------------------------------------------------
        for rq in rubric.questions:
            if rq.question_type != "mcq":
                continue
            if rq.question_id in skip_ids:
                continue

            correct_options = rq.correct_options or []

            def _label(s: str) -> str:
                s = s.strip()
                if s and s[0].isalpha() and len(s) > 1 and s[1] in (".", ")"):
                    return s[0].upper()
                return s.upper()

            correct_labels = {_label(c) for c in correct_options}

            student_answer = next(
                (a for a in answers if a.question_id == rq.question_id), None
            )
            raw_labels = getattr(student_answer, "selected_option_labels", None) if student_answer else None
            if raw_labels:
                student_labels = {_label(l) for l in raw_labels}
            elif student_answer:
                student_labels = {_label(student_answer.answer_markdown.strip())}
            else:
                student_labels = set()

            is_correct    = student_labels == correct_labels and len(student_labels) > 0
            marks_awarded = rq.total_marks if is_correct else 0.0
            verdict_str   = "correct" if is_correct else "incorrect"

            student_display = ", ".join(sorted(student_labels)) if student_labels else "(no answer)"
            correct_display = ", ".join(sorted(correct_labels))
            multi_note      = " (multi-select)" if rq.is_multi_select else ""

            mcq_eval = ConceptEvaluation(
                concept_name=f"MCQ Answer{multi_note}",
                marks_allocated=rq.total_marks,
                marks_awarded=marks_awarded,
                verdict=ConceptVerdict(verdict_str),
                reason=(
                    f"Student selected: '{student_display}'. "
                    f"Correct answer: '{correct_display}'. "
                    + ("Correct." if is_correct else "Incorrect — full marks require exact match.")
                ),
            )
            question_wise.append(
                QuestionEvaluation(
                    question_id=rq.question_id,
                    maximum_marks=rq.total_marks,
                    concept_evaluations=[mcq_eval],
                    marks_awarded=marks_awarded,
                    justification=(
                        f"MCQ{multi_note}: student selected '{student_display}', "
                        f"correct answer is '{correct_display}'."
                    ),
                    strengths=["Correct option selected."] if is_correct else [],
                    areas_for_improvement=[] if is_correct else [
                        f"Incorrect. The correct answer is '{correct_display}'."
                    ],
                    bloom_depth="mcq",
                    bloom_outcome=_bloom_outcome(marks_awarded, rq.total_marks),
                    course_outcome=co_lookup.get(rq.question_id),
                )
            )

        # ------------------------------------------------------------------
        # Descriptive scoring — via Gemini
        # ------------------------------------------------------------------
        for qe in parsed.question_wise_evaluation:
            if qe.question_id in mcq_ids:
                continue
            if qe.question_id in skip_ids:
                continue

            rubric_q    = rubric_q_lookup.get(qe.question_id)
            partial_pct = (
                rubric_q.partial_marking_rule.partial_explanation_percentage / 100
                if rubric_q and rubric_q.partial_marking_rule else 0.5
            )
            concept_lookup = (
                {c.concept_name: c.marks_allocated for c in rubric_q.concepts}
                if rubric_q and rubric_q.concepts else {}
            )

            concept_evals = [
                ConceptEvaluation(
                    concept_name=c.concept_name,
                    marks_allocated=concept_lookup.get(c.concept_name, 0.0),
                    verdict=ConceptVerdict(c.verdict),
                    reason=c.reason,
                    marks_awarded=_concept_marks(
                        c.verdict,
                        concept_lookup.get(c.concept_name, 0.0),
                        partial_pct,
                    ),
                )
                for c in qe.concept_evaluations
            ]

            q_marks_awarded = sum(c.marks_awarded for c in concept_evals)
            bloom_depth     = rubric_q.expected_depth.value if rubric_q and rubric_q.expected_depth else None

            question_wise.append(
                QuestionEvaluation(
                    question_id=qe.question_id,
                    maximum_marks=qe.maximum_marks,
                    concept_evaluations=concept_evals,
                    marks_awarded=q_marks_awarded,
                    justification=qe.justification,
                    strengths=qe.strengths,
                    areas_for_improvement=qe.areas_for_improvement,
                    bloom_depth=bloom_depth,
                    bloom_outcome=_bloom_outcome(q_marks_awarded, qe.maximum_marks),
                    course_outcome=co_lookup.get(qe.question_id),
                )
            )

        # ------------------------------------------------------------------
        # Best-N selection per section (string IDs)
        # ------------------------------------------------------------------
        if parsed_paper.sections:
            qe_by_id: Dict[str, QuestionEvaluation] = {
                qe.question_id: qe for qe in question_wise
            }

            for section in parsed_paper.sections:
                attempted_in_section = [
                    qe_by_id[qid]
                    for qid in section.question_ids
                    if qid in qe_by_id
                ]
                if len(attempted_in_section) <= section.required_count:
                    continue

                ranked = sorted(
                    attempted_in_section,
                    key=lambda q: (-q.marks_awarded, q.question_id),
                )
                counted_ids = {q.question_id for q in ranked[: section.required_count]}
                for qe in attempted_in_section:
                    if qe.question_id not in counted_ids:
                        qe.counted = False

        return EvaluationReport(
            student_info=student_info,
            extracted_answers=[],           # populated by the router after OCR
            evaluation_summary=build_evaluation_summary(
                overall_feedback=parsed.evaluation_summary.overall_feedback,
                question_wise_evaluation=question_wise,
                full_marks=full_marks,
            ),
            question_wise_evaluation=question_wise,
        )