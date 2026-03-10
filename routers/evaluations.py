from fastapi import APIRouter, UploadFile, File, Form, HTTPException, Depends
import aiosqlite
import uuid
import hashlib

from db.database import get_db
from db.repository import PaperRepository
from db.eval_repository import EvaluationRepository
from services.ocr_answer_service import OCRAnswerService
from services.evaluator_service import EvaluatorService
from models.schemas import (
    EvaluationResponse,
    EvaluationSummaryResponse,
    EvaluationConfirmRequest,
    EvaluationConfirmResponse,
    EvaluationDeleteResponse,
    EvaluationReport,
    ExtractedAnswer,
    StudentInfo,
)

router = APIRouter()
ocr_answer_svc = OCRAnswerService()
evaluator_svc  = EvaluatorService()


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


# ---------------------------------------------------------------------------
# POST /evaluate
# ---------------------------------------------------------------------------

@router.post(
    "/evaluate",
    response_model=EvaluationResponse,
    summary="Evaluate a student answer PDF against a confirmed question paper",
    description=(
        "Upload a student answer PDF and specify which confirmed paper to evaluate against. "
        "The server OCR-extracts answers and student info, then runs the evaluator LLM. "
        "Returns a full evaluation report for review before confirming."
    ),
)
async def evaluate(
    file: UploadFile = File(..., description="Student answer sheet PDF"),
    paper_id: str = Form(..., description="paper_id of the confirmed question paper to evaluate against"),
    db: aiosqlite.Connection = Depends(get_db),
):
    if file.content_type not in ("application/pdf", "application/octet-stream"):
        raise HTTPException(status_code=400, detail="Only PDF files are accepted.")

    pdf_bytes = await file.read()
    if not pdf_bytes:
        raise HTTPException(status_code=400, detail="Uploaded file is empty.")

    # ── Verify the question paper exists and is confirmed ────────────────────
    paper_repo = PaperRepository(db)
    paper = await paper_repo.find_by_id(paper_id)
    if not paper:
        raise HTTPException(status_code=404, detail="Question paper not found.")
    if not paper.confirmed:
        raise HTTPException(
            status_code=409,
            detail="Question paper is not yet confirmed. Please confirm it before evaluating.",
        )

    # ── Duplicate check on answer PDF ────────────────────────────────────────
    answer_sha256 = _sha256(pdf_bytes)
    eval_repo = EvaluationRepository(db)

    existing = await eval_repo.find_by_answer_hash(answer_sha256)
    if existing:
        existing.message = "Duplicate answer sheet detected. Returning existing evaluation."
        return existing

    # ── OCR: extract answers + student info ──────────────────────────────────
    try:
        ocr_result = await ocr_answer_svc.extract_answers(pdf_bytes)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Answer OCR failed: {str(exc)}")

    # ── Evaluate ─────────────────────────────────────────────────────────────
    try:
        full_marks = float(paper.parsed_paper.metadata.full_marks)
    except (ValueError, TypeError):
        raise HTTPException(status_code=500, detail="Invalid full_marks value in paper metadata.")

    try:
        report = await evaluator_svc.evaluate(
            parsed_paper=paper.parsed_paper,
            rubric=paper.rubric,
            answers=ocr_result.answers,
            student_info=ocr_result.student_info,
            full_marks=full_marks,
        )
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Evaluation failed: {str(exc)}")

    # ── Persist (unconfirmed — examiner reviews first) ───────────────────────
    eval_id = str(uuid.uuid4())

    # Attach the raw OCR answers to the report so they are stored in the DB
    report.extracted_answers = [
        ExtractedAnswer(question_id=a.question_id, answer_markdown=a.answer_markdown)
        for a in ocr_result.answers
    ]

    await eval_repo.insert(eval_id, paper_id, answer_sha256, report)

    return EvaluationResponse(
        eval_id=eval_id,
        paper_id=paper_id,
        answer_sha256=answer_sha256,
        is_duplicate=False,
        student_info=report.student_info,
        extracted_answers=report.extracted_answers,
        evaluation_summary=report.evaluation_summary,
        question_wise_evaluation=report.question_wise_evaluation,
        confirmed=False,
        message="Evaluation complete. Please review and confirm.",
    )


# ---------------------------------------------------------------------------
# POST /confirm
# ---------------------------------------------------------------------------

@router.post(
    "/confirm",
    response_model=EvaluationConfirmResponse,
    summary="Confirm an evaluation after examiner review",
    description=(
        "Called after the examiner reviews the evaluation and optionally corrects "
        "student info or marks. Saves the final version as confirmed."
    ),
)
async def confirm_evaluation(
    body: EvaluationConfirmRequest,
    db: aiosqlite.Connection = Depends(get_db),
):
    eval_repo = EvaluationRepository(db)
    existing = await eval_repo.find_by_id(body.eval_id)
    if not existing:
        raise HTTPException(status_code=404, detail="Evaluation not found.")
    if existing.confirmed:
        raise HTTPException(status_code=409, detail="Evaluation is already confirmed.")

    # Rebuild EvaluationReport from the (possibly edited) confirm body
    report = EvaluationReport(
        student_info=body.student_info,
        extracted_answers=body.extracted_answers,
        evaluation_summary=body.evaluation_summary,
        question_wise_evaluation=body.question_wise_evaluation,
    )
    await eval_repo.confirm(body.eval_id, report)

    return EvaluationConfirmResponse(
        eval_id=body.eval_id,
        message="Evaluation confirmed and saved successfully.",
    )


# ---------------------------------------------------------------------------
# GET /{paper_id}   — all evaluations for a paper (class list)
# ---------------------------------------------------------------------------

@router.get(
    "/{paper_id}",
    response_model=list[EvaluationSummaryResponse],
    summary="List all student evaluations for a question paper",
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
# GET /{paper_id}/{eval_id}   — single evaluation detail
# ---------------------------------------------------------------------------

@router.get(
    "/{paper_id}/{eval_id}",
    response_model=EvaluationResponse,
    summary="Get full detail of a single student evaluation",
)
async def get_evaluation(
    paper_id: str,
    eval_id: str,
    db: aiosqlite.Connection = Depends(get_db),
):
    eval_repo = EvaluationRepository(db)
    evaluation = await eval_repo.find_by_id(eval_id)
    if not evaluation or evaluation.paper_id != paper_id:
        raise HTTPException(status_code=404, detail="Evaluation not found.")
    return evaluation


# ---------------------------------------------------------------------------
# DELETE /{eval_id}
# ---------------------------------------------------------------------------

@router.delete(
    "/{eval_id}",
    response_model=EvaluationDeleteResponse,
    summary="Delete a student evaluation",
    description="Permanently removes an evaluation. This action is irreversible.",
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