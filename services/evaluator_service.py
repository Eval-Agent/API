import os
from pathlib import Path
from google import genai
from google.genai import types
from pydantic import BaseModel
from typing import List, Optional
from enum import Enum

from models.schemas import (
    EvaluationReport,
    EvaluationSummary,
    QuestionEvaluation,
    ConceptEvaluation,
    ConceptVerdict,
    StudentInfo,
    Rubric,
    RubricResponse,
    ParsedPaper,
    build_evaluation_summary,
)


# ---------------------------------------------------------------------------
# Internal schema for LLM structured output
# ---------------------------------------------------------------------------

class _StudentInfo(BaseModel):
    student_name: str
    roll_number: Optional[str] = None


class _EvaluationSummary(BaseModel):
    """Gemini only generates the overall feedback — totals are computed in Python."""
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
    student_info: _StudentInfo
    evaluation_summary: _EvaluationSummary
    question_wise_evaluation: List[_QuestionEvaluation]


# ---------------------------------------------------------------------------

_SYSTEM_PROMPT_PATH = Path("./instructions/eval_system_prompt.txt")

_DEFAULT_SYSTEM_PROMPT = """
You are an expert university-level engineering examiner.
Evaluate each student answer strictly against the rubric concepts provided.

For every concept in each question:
  - verdict: "correct" if the concept is clearly and accurately addressed.
             "partial" if the concept is mentioned or partially addressed but lacks depth or accuracy.
             "incorrect" if the concept is missing, wrong, or not addressed.
  - If a concept is marked mandatory and is missing, verdict must be "incorrect".
  - reason: one or two sentences referencing specific phrases from the student's answer. Do NOT hallucinate content not written by the student.

For each question also provide:
  - justification: brief overall reasoning for the question.
  - strengths: list of positive aspects observed.
  - areas_for_improvement: list of gaps or weaknesses.

Finally provide:
  - overall_feedback: short holistic summary of the student's performance across all questions.

Do NOT produce any marks, scores, or totals — these are computed by the server.
Output ONLY valid JSON matching the schema. No markdown, no code fences, no commentary.
""".strip()


def _load_system_prompt() -> str:
    if _SYSTEM_PROMPT_PATH.exists():
        return _SYSTEM_PROMPT_PATH.read_text(encoding="utf-8")
    return _DEFAULT_SYSTEM_PROMPT


def _build_evaluation_prompt(
    parsed_paper: ParsedPaper,
    rubric: Rubric | RubricResponse,
    answers: list,
    student_info: _StudentInfo,
) -> str:
    """
    Builds the markdown prompt combining questions, rubric, and student answers —
    mirrors the build_markdown_prompt() approach from flow.py.
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
        student_info: _StudentInfo,
        full_marks: float,
    ) -> EvaluationReport:
        prompt = _build_evaluation_prompt(parsed_paper, rubric, answers, student_info)

        response = self.client.models.generate_content(
            model=self.model,
            config=types.GenerateContentConfig(
                system_instruction=self.system_prompt,
                # temperature=0,
                # top_p=0,
                # top_k=1,
                # seed=84,
                response_json_schema=_EvaluationReport.model_json_schema(),
            ),
            contents=prompt,
        )

        parsed = _EvaluationReport.model_validate_json(response.text)

        # Build rubric lookups for deterministic mark computation
        rubric_q_lookup = {rq.question_id: rq for rq in rubric.questions}

        def _concept_marks(verdict: _ConceptVerdict, marks_allocated: float, partial_pct: float) -> float:
            if verdict == _ConceptVerdict.correct:
                return marks_allocated
            elif verdict == _ConceptVerdict.partial:
                return round(marks_allocated * partial_pct, 2)
            else:
                return 0.0

        question_wise = []
        for qe in parsed.question_wise_evaluation:
            rubric_q   = rubric_q_lookup.get(qe.question_id)
            partial_pct = (
                rubric_q.partial_marking_rule.partial_explanation_percentage/100
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

            question_wise.append(
                QuestionEvaluation(
                    question_id=qe.question_id,
                    maximum_marks=qe.maximum_marks,
                    concept_evaluations=concept_evals,
                    marks_awarded=sum(c.marks_awarded for c in concept_evals),
                    justification=qe.justification,
                    strengths=qe.strengths,
                    areas_for_improvement=qe.areas_for_improvement,
                )
            )

        return EvaluationReport(
            student_info=StudentInfo(
                student_name=parsed.student_info.student_name,
                roll_number=parsed.student_info.roll_number,
            ),
            extracted_answers=[],   # populated by the router after OCR
            evaluation_summary=build_evaluation_summary(
                overall_feedback=parsed.evaluation_summary.overall_feedback,
                question_wise_evaluation=question_wise,
                full_marks=full_marks,
            ),
            question_wise_evaluation=question_wise,
        )