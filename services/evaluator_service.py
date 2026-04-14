import os
from pathlib import Path
from google import genai
from google.genai import types
from pydantic import BaseModel
from typing import List, Optional
from enum import Enum

from services.token_logger import log_token_usage
from models.rubric import Rubric, RubricResponse
from models.paper import ParsedPaper
from models.evaluation import (
    EvaluationReport,
    EvaluationSummary,
    QuestionEvaluation,
    ConceptEvaluation,
    ConceptVerdict,
    StudentInfo,
    build_evaluation_summary,
    _bloom_outcome,
)


# ---------------------------------------------------------------------------
# Internal schema for LLM structured output
# ---------------------------------------------------------------------------

class _EvaluationSummary(BaseModel):
    """Gemini only generates overall_feedback — totals are computed in Python."""
    overall_feedback: str


class _ConceptVerdict(str, Enum):
    correct   = "correct"
    partial   = "partial"
    incorrect = "incorrect"


class _ConceptEvaluation(BaseModel):
    """Gemini only judges the verdict — marks are computed in Python."""
    concept_name: str
    verdict: _ConceptVerdict
    reason: str


class _QuestionEvaluation(BaseModel):
    question_id: int
    maximum_marks: float
    concept_evaluations: List[_ConceptEvaluation]
    justification: str
    strengths: Optional[List[str]] = None
    areas_for_improvement: Optional[List[str]] = None


class _EvaluationReport(BaseModel):
    """student_info is omitted — already captured by OCR, not Gemini's responsibility."""
    evaluation_summary: _EvaluationSummary
    question_wise_evaluation: List[_QuestionEvaluation]


# ---------------------------------------------------------------------------

_SYSTEM_PROMPT_PATH = Path("./instructions/eval_system_prompt.txt")


def _load_system_prompt() -> str:
    if not _SYSTEM_PROMPT_PATH.exists():
        raise FileNotFoundError(
            f"Eval system prompt not found at {_SYSTEM_PROMPT_PATH}. "
            "Please ensure instructions/eval_system_prompt.txt exists."
        )
    return _SYSTEM_PROMPT_PATH.read_text(encoding="utf-8")


def _build_evaluation_prompt(
    parsed_paper: ParsedPaper,
    rubric: Rubric | RubricResponse,
    answers: list,
    student_info: StudentInfo,
) -> str:
    """
    Builds the markdown prompt combining questions, rubric, and student answers.
    """
    rubric_lookup = {q.question_id: q for q in rubric.questions}
    answer_lookup = {a.question_id: a.answer_markdown for a in answers}

    lines = ["# Student Evaluation Data\n"]
    lines.append(f"**Student Name:** {student_info.student_name}")
    lines.append(f"**Roll Number:** {student_info.roll_number or 'N/A'}\n")

    for q in parsed_paper.questions:
        q_id = q.question_id
        if q_id not in answer_lookup:
            continue

        rubric_q = rubric_lookup.get(q_id)
        lines.append(f"## Question ID: {q_id}")
        lines.append(f"**Max Score:** {q.max_score}\n")

        lines.append("### Question")
        lines.append(f"{q.question_markdown}\n")

        lines.append("### Student Answer")
        lines.append(f"{answer_lookup[q_id]}\n")

        lines.append("### Rubric")
        if rubric_q:
            lines.append(f"**Expected Depth:** {rubric_q.expected_depth}\n")
            lines.append("#### Concepts")
            for concept in rubric_q.concepts:
                lines.append(f"- **Concept:** {concept.concept_name}")
                lines.append(f"  - Description: {concept.description}")
                lines.append(f"  - Keywords: {', '.join(concept.keywords)}")
                lines.append(f"  - Mandatory: {concept.mandatory}")
        else:
            lines.append("*No rubric available for this question.*\n")

        lines.append("---\n")

    return "\n".join(lines)


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
        rubric: Rubric | RubricResponse,
        answers: list,
        student_info: StudentInfo,
        full_marks: float,
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

        # Build rubric lookups for deterministic mark computation
        rubric_q_lookup = {rq.question_id: rq for rq in rubric.questions}

        # Build course_outcome lookup from parsed paper questions
        co_lookup = {
            pq.question_id: getattr(pq, "course_outcome", None)
            for pq in parsed_paper.questions
        }

        def _concept_marks(
            verdict: _ConceptVerdict,
            marks_allocated: float,
            partial_pct: float,
        ) -> float:
            if verdict == _ConceptVerdict.correct:
                return marks_allocated
            elif verdict == _ConceptVerdict.partial:
                return round(marks_allocated * partial_pct, 2)
            else:
                return 0.0

        question_wise = []
        for qe in parsed.question_wise_evaluation:
            rubric_q    = rubric_q_lookup.get(qe.question_id)
            partial_pct = (
                rubric_q.partial_marking_rule.partial_explanation_percentage / 100
                if rubric_q else 0.5
            )
            concept_lookup = (
                {c.concept_name: c.marks_allocated for c in rubric_q.concepts}
                if rubric_q else {}
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
            bloom_depth = rubric_q.expected_depth.value if rubric_q else None
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

        # ── Best-N selection per section ────────────────────────────────────────
        # If the paper has sections with required_count < total questions offered,
        # a student may have answered more than required.
        # Mark excess answers as counted=False — only the best N (by marks) count.

        if parsed_paper.sections:
            qe_by_id = {qe.question_id: qe for qe in question_wise}

            for section in parsed_paper.sections:
                # Which of this section's questions did the student actually attempt?
                attempted_in_section = [
                    qe_by_id[qid]
                    for qid in section.question_ids
                    if qid in qe_by_id
                ]

                if len(attempted_in_section) <= section.required_count:
                    # Student answered at most the required number — all count
                    continue

                # Student answered more than required — pick best N by marks_awarded
                # (highest first; ties broken by question_id for determinism)
                ranked = sorted(
                    attempted_in_section,
                    key=lambda q: (-q.marks_awarded, q.question_id),
                )
                counted_ids = {q.question_id for q in ranked[: section.required_count]}

                # Mark excess questions
                for qe in attempted_in_section:
                    if qe.question_id not in counted_ids:
                        qe.counted = False

        return EvaluationReport(
            student_info=student_info,      # from OCR — not re-parsed from Gemini
            extracted_answers=[],           # populated by the router after OCR
            evaluation_summary=build_evaluation_summary(
                overall_feedback=parsed.evaluation_summary.overall_feedback,
                question_wise_evaluation=question_wise,
                full_marks=full_marks,
            ),
            question_wise_evaluation=question_wise,
        )