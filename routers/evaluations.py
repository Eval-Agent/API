"""
Evaluations router

  POST /submissions/{submission_id}/evaluation:generate
  POST /submissions/{submission_id}/evaluation:confirm
  GET  /papers/{paper_id}/evaluations
  GET  /evaluations/{eval_id}
  DELETE /evaluations/{eval_id}

Two mountable sub-routers so main.py can attach them at different prefixes
without path-parameter collisions.
"""

from fastapi import APIRouter, HTTPException, Depends
import aiosqlite
import uuid

from db.database import get_db
from db.repository import PaperRepository
from db.eval_repository import OcrRepository, EvaluationRepository
from services.evaluator_service import EvaluatorService
from models.schemas import (
    EvaluateRequest,
    EvaluationResponse,
    EvaluationSummaryResponse,
    EvaluationConfirmRequest,
    EvaluationConfirmResponse,
    EvaluationDeleteResponse,
    EvaluationReport,
    ExtractedAnswer,
    StudentInfo,
)

# submissions_router mounts under /api/v1/submissions
# papers_router     mounts under /api/v1/papers
# flat_router       mounts under /api/v1/evaluations
submissions_router = APIRouter()
papers_router      = APIRouter()
flat_router        = APIRouter()

_evaluator_svc = EvaluatorService()


# ---------------------------------------------------------------------------
# POST /submissions/{submission_id}/evaluation:generate
# Run AI evaluation against rubric
# ---------------------------------------------------------------------------

@submissions_router.post(
    "/{submission_id}/evaluation:generate",
    response_model=EvaluationResponse,
    summary="Evaluate a student submission against the rubric",
    description=(
        "Runs AI evaluation on the extracted answers from the given submission, "
        "scoring each answer against the paper rubric. "
        "Returns a full evaluation report for examiner review."
    ),
    tags=["Evaluations"],
)
async def generate_evaluation(
    submission_id: str,
    db: aiosqlite.Connection = Depends(get_db),
):
    ocr_repo  = OcrRepository(db)
    eval_repo = EvaluationRepository(db)

    # Load submission
    ocr_record = await ocr_repo.find_by_id(submission_id)
    if not ocr_record:
        raise HTTPException(status_code=404, detail="Submission not found.")

    paper_id      = ocr_record["paper_id"]
    answer_sha256 = ocr_record["answer_sha256"]
    student_info  = StudentInfo.model_validate_json(ocr_record["student_info"])

    import json
    extracted_answers = [
        ExtractedAnswer(**a) for a in json.loads(ocr_record["extracted_answers"])
    ]

    # Return existing evaluation if already done (idempotent)
    existing = await eval_repo.find_by_id_via_ocr(submission_id)
    if existing:
        existing.message = "Evaluation already exists for this submission. Returning existing result."
        return existing

    # Load confirmed paper + rubric
    paper_repo = PaperRepository(db)
    paper = await paper_repo.find_by_id(paper_id)
    if not paper:
        raise HTTPException(status_code=404, detail="Question paper not found.")
    if paper.rubric is None:
        raise HTTPException(status_code=409, detail="Paper has no rubric. Generate and confirm a rubric first.")

    try:
        full_marks = float(paper.parsed_paper.metadata.full_marks)
    except (ValueError, TypeError):
        raise HTTPException(status_code=500, detail="Invalid full_marks value in paper metadata.")

    # Run evaluation
    try:
        report = await _evaluator_svc.evaluate(
            parsed_paper=paper.parsed_paper,
            rubric=paper.rubric,
            answers=extracted_answers,
            student_info=student_info,
            full_marks=full_marks,
        )
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Evaluation failed: {str(exc)}")

    report.extracted_answers = extracted_answers

    # Persist
    eval_id = str(uuid.uuid4())
    await eval_repo.insert(
        eval_id=eval_id,
        ocr_id=submission_id,
        paper_id=paper_id,
        answer_sha256=answer_sha256,
        report=report,
    )

    return EvaluationResponse(
        eval_id=eval_id,
        paper_id=paper_id,
        submission_id=submission_id,
        answer_sha256=answer_sha256,
        is_duplicate=False,
        student_info=report.student_info,
        extracted_answers=report.extracted_answers,
        evaluation_summary=report.evaluation_summary,
        question_wise_evaluation=report.question_wise_evaluation,
        confirmed=False,
        message="Evaluation complete. Review and call evaluation:confirm when ready.",
    )


# ---------------------------------------------------------------------------
# POST /submissions/{submission_id}/evaluation:confirm
# Examiner confirms (possibly edited) evaluation
# ---------------------------------------------------------------------------

@submissions_router.post(
    "/{submission_id}/evaluation:confirm",
    response_model=EvaluationConfirmResponse,
    summary="Confirm an evaluation after examiner review",
    description=(
        "Called after the examiner reviews the AI evaluation and optionally "
        "corrects student info, marks, or feedback. Saves the final version as confirmed."
    ),
    tags=["Evaluations"],
)
async def confirm_evaluation(
    submission_id: str,
    body: EvaluationConfirmRequest,
    db: aiosqlite.Connection = Depends(get_db),
):
    eval_repo = EvaluationRepository(db)

    existing = await eval_repo.find_by_id_via_ocr(submission_id)
    if not existing:
        raise HTTPException(
            status_code=404,
            detail="No evaluation found for this submission. Run evaluation:generate first.",
        )
    if existing.confirmed:
        raise HTTPException(status_code=409, detail="Evaluation is already confirmed.")

    report = EvaluationReport(
        student_info=body.student_info,
        extracted_answers=body.extracted_answers,
        evaluation_summary=body.evaluation_summary,
        question_wise_evaluation=body.question_wise_evaluation,
    )
    await eval_repo.confirm(existing.eval_id, report)

    return EvaluationConfirmResponse(
        eval_id=existing.eval_id,
        message="Evaluation confirmed and saved successfully.",
    )


# ---------------------------------------------------------------------------
# GET /papers/{paper_id}/evaluations
# List all evaluations for a paper (class list view)
# ---------------------------------------------------------------------------

@papers_router.get(
    "/{paper_id}/evaluations",
    response_model=list[EvaluationSummaryResponse],
    summary="List all evaluations for a question paper",
    description="Returns one summary row per student evaluation for the given paper.",
    tags=["Evaluations"],
)
async def list_evaluations(
    paper_id: str,
    db: aiosqlite.Connection = Depends(get_db),
):
    paper_repo = PaperRepository(db)
    if not await paper_repo.find_by_id(paper_id):
        raise HTTPException(status_code=404, detail="Question paper not found.")

    eval_repo = EvaluationRepository(db)
    return await eval_repo.list_by_paper(paper_id)


# ---------------------------------------------------------------------------
# GET /evaluations/{eval_id}
# Full detail of a single evaluation
# ---------------------------------------------------------------------------

@flat_router.get(
    "/{eval_id}",
    response_model=EvaluationResponse,
    summary="Get full detail of a single evaluation",
    tags=["Evaluations"],
)
async def get_evaluation(
    eval_id: str,
    db: aiosqlite.Connection = Depends(get_db),
):
    eval_repo = EvaluationRepository(db)
    evaluation = await eval_repo.find_by_id(eval_id)
    if not evaluation:
        raise HTTPException(status_code=404, detail="Evaluation not found.")
    return evaluation


# ---------------------------------------------------------------------------
# DELETE /evaluations/{eval_id}
# ---------------------------------------------------------------------------

@flat_router.delete(
    "/{eval_id}",
    response_model=EvaluationDeleteResponse,
    summary="Delete a student evaluation",
    description="Permanently removes an evaluation. This action is irreversible.",
    tags=["Evaluations"],
)
async def delete_evaluation(
    eval_id: str,
    db: aiosqlite.Connection = Depends(get_db),
):
    eval_repo = EvaluationRepository(db)
    existing = await eval_repo.find_by_id(eval_id)
    if not existing:
        raise HTTPException(status_code=404, detail="Evaluation not found.")

    await eval_repo.delete(eval_id)
    return EvaluationDeleteResponse(
        eval_id=eval_id,
        message="Evaluation deleted successfully.",
    )