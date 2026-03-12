from fastapi import APIRouter, UploadFile, File, Form, HTTPException, Depends
import aiosqlite
import uuid
import hashlib
import json

from db.database import get_db
from db.repository import PaperRepository
from db.eval_repository import EvaluationRepository, OcrRepository
from services.ocr_answer_service import OCRAnswerService
from services.evaluator_service import EvaluatorService
from models.schemas import (
    OcrResponse,
    OcrDeleteResponse,
    OcrSummaryResponse,
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

router = APIRouter()
ocr_answer_svc = OCRAnswerService()
evaluator_svc  = EvaluatorService()


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


# ---------------------------------------------------------------------------
# POST /ocr   — upload answer PDF, run OCR, save result
# ---------------------------------------------------------------------------

@router.post(
    "/ocr",
    response_model=OcrResponse,
    summary="Upload a student answer PDF and extract answers via OCR",
    description=(
        "Accepts a student answer PDF and a paper_id. Runs OCR to extract "
        "student info and answers. Saves the OCR result and returns an ocr_id "
        "to be used in the evaluate step."
    ),
)
async def ocr_answer(
    file: UploadFile = File(..., description="Student answer sheet PDF"),
    paper_id: str = Form(..., description="paper_id of the confirmed question paper"),
    db: aiosqlite.Connection = Depends(get_db),
):
    if file.content_type not in ("application/pdf", "application/octet-stream"):
        raise HTTPException(status_code=400, detail="Only PDF files are accepted.")

    pdf_bytes = await file.read()
    if not pdf_bytes:
        raise HTTPException(status_code=400, detail="Uploaded file is empty.")

    # ── Verify paper exists and is confirmed ─────────────────────────────────
    paper_repo = PaperRepository(db)
    paper = await paper_repo.find_by_id(paper_id)
    if not paper:
        raise HTTPException(status_code=404, detail="Question paper not found.")
    if not paper.confirmed:
        raise HTTPException(
            status_code=409,
            detail="Question paper is not yet confirmed. Please confirm it before evaluating.",
        )

    # ── Duplicate check ───────────────────────────────────────────────────────
    answer_sha256 = _sha256(pdf_bytes)
    ocr_repo = OcrRepository(db)

    existing = await ocr_repo.find_by_answer_hash(answer_sha256)
    if existing:
        return OcrResponse(
            ocr_id=existing["ocr_id"],
            paper_id=existing["paper_id"],
            answer_sha256=existing["answer_sha256"],
            is_duplicate=True,
            student_info=StudentInfo.model_validate_json(existing["student_info"]),
            extracted_answers=[
                ExtractedAnswer(**a)
                for a in json.loads(existing["extracted_answers"])
            ],
            message="Duplicate answer sheet detected. Returning existing OCR result.",
        )

    # ── Run OCR ───────────────────────────────────────────────────────────────
    try:
        ocr_result = await ocr_answer_svc.extract_answers(pdf_bytes)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Answer OCR failed: {str(exc)}")

    extracted_answers = [
        ExtractedAnswer(question_id=a.question_id, answer_markdown=a.answer_markdown)
        for a in ocr_result.answers
    ]

    # Convert internal _StudentInfo to public StudentInfo schema
    student_info = StudentInfo(
        student_name=ocr_result.student_info.student_name,
        roll_number=ocr_result.student_info.roll_number,
    )

    # ── Persist OCR result ────────────────────────────────────────────────────
    ocr_id = str(uuid.uuid4())
    await ocr_repo.insert(
        ocr_id=ocr_id,
        paper_id=paper_id,
        answer_sha256=answer_sha256,
        student_info=student_info,
        extracted_answers=extracted_answers,
    )

    return OcrResponse(
        ocr_id=ocr_id,
        paper_id=paper_id,
        answer_sha256=answer_sha256,
        is_duplicate=False,
        student_info=student_info,
        extracted_answers=extracted_answers,
        message="OCR complete. Call /evaluate with the ocr_id to run evaluation.",
    )


# ---------------------------------------------------------------------------
# POST /evaluate   — run evaluation from a saved OCR result
# ---------------------------------------------------------------------------

@router.post(
    "/evaluate",
    response_model=EvaluationResponse,
    summary="Evaluate a student answer using a saved OCR result",
    description=(
        "Takes an ocr_id from a previous OCR step and evaluates the extracted "
        "answers against the paper rubric. Returns a full evaluation report."
    ),
)
async def evaluate(
    body: EvaluateRequest,
    db: aiosqlite.Connection = Depends(get_db),
):
    ocr_repo  = OcrRepository(db)
    eval_repo = EvaluationRepository(db)

    # ── Load OCR result ───────────────────────────────────────────────────────
    ocr_record = await ocr_repo.find_by_id(body.ocr_id)
    if not ocr_record:
        raise HTTPException(status_code=404, detail="OCR result not found.")

    paper_id      = ocr_record["paper_id"]
    answer_sha256 = ocr_record["answer_sha256"]
    student_info  = StudentInfo.model_validate_json(ocr_record["student_info"])
    extracted_answers = [
        ExtractedAnswer(**a)
        for a in json.loads(ocr_record["extracted_answers"])
    ]

    # ── Duplicate check — return existing evaluation if already evaluated ─────
    existing = await eval_repo.find_by_id_via_ocr(body.ocr_id)
    if existing:
        existing.message = "Evaluation already exists for this OCR result. Returning existing."
        return existing

    # ── Load paper ────────────────────────────────────────────────────────────
    paper_repo = PaperRepository(db)
    paper = await paper_repo.find_by_id(paper_id)
    if not paper:
        raise HTTPException(status_code=404, detail="Question paper not found.")

    try:
        full_marks = float(paper.parsed_paper.metadata.full_marks)
    except (ValueError, TypeError):
        raise HTTPException(status_code=500, detail="Invalid full_marks value in paper metadata.")

    # ── Run evaluation ────────────────────────────────────────────────────────
    try:
        report = await evaluator_svc.evaluate(
            parsed_paper=paper.parsed_paper,
            rubric=paper.rubric,
            answers=extracted_answers,
            student_info=student_info,
            full_marks=full_marks,
        )
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Evaluation failed: {str(exc)}")

    report.extracted_answers = extracted_answers

    # ── Persist evaluation ────────────────────────────────────────────────────
    eval_id = str(uuid.uuid4())
    await eval_repo.insert(
        eval_id=eval_id,
        ocr_id=body.ocr_id,
        paper_id=paper_id,
        answer_sha256=answer_sha256,
        report=report,
    )

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
# GET /ocr/{paper_id}   — list all OCR results for a paper
# IMPORTANT: must be registered BEFORE GET /{paper_id} so FastAPI does not
# swallow the literal segment "ocr" as a paper_id path parameter.
# ---------------------------------------------------------------------------

@router.get(
    "/ocr/{paper_id}",
    response_model=list[OcrSummaryResponse],
    summary="List all OCR results for a question paper",
    description=(
        "Returns all uploaded answer sheets for a given paper. "
        "Each entry includes a has_evaluation flag so the UI can show "
        "which sheets are pending evaluation and which are done."
    ),
)
async def list_ocr_results(
    paper_id: str,
    db: aiosqlite.Connection = Depends(get_db),
):
    paper_repo = PaperRepository(db)
    if not await paper_repo.find_by_id(paper_id):
        raise HTTPException(status_code=404, detail="Question paper not found.")

    ocr_repo = OcrRepository(db)
    return await ocr_repo.list_by_paper(paper_id)


# ---------------------------------------------------------------------------
# GET /ocr/detail/{ocr_id}   — full OCR result for a single answer sheet
# IMPORTANT: uses the /ocr/detail/ prefix to avoid clashing with
# GET /ocr/{paper_id} — both would otherwise match the same pattern.
# ---------------------------------------------------------------------------

@router.get(
    "/ocr/detail/{ocr_id}",
    response_model=OcrResponse,
    summary="Get full OCR result for a single answer sheet",
    description=(
        "Returns the complete OCR record for a given ocr_id, including "
        "student info and all extracted answers."
    ),
)
async def get_ocr_result(
    ocr_id: str,
    db: aiosqlite.Connection = Depends(get_db),
):
    ocr_repo = OcrRepository(db)
    record = await ocr_repo.find_by_id(ocr_id)
    if not record:
        raise HTTPException(status_code=404, detail="OCR result not found.")

    student_info = StudentInfo.model_validate_json(record["student_info"])
    extracted_answers = [
        ExtractedAnswer(**a)
        for a in json.loads(record["extracted_answers"])
    ]

    return OcrResponse(
        ocr_id=record["ocr_id"],
        paper_id=record["paper_id"],
        answer_sha256=record["answer_sha256"],
        is_duplicate=False,
        student_info=student_info,
        extracted_answers=extracted_answers,
        message="OCR result retrieved successfully.",
    )


# ---------------------------------------------------------------------------
# DELETE /ocr/{ocr_id}   — delete an OCR result before evaluation
# IMPORTANT: must be registered BEFORE DELETE /{eval_id} for the same reason.
# ---------------------------------------------------------------------------

@router.delete(
    "/ocr/{ocr_id}",
    response_model=OcrDeleteResponse,
    summary="Delete an OCR result",
    description=(
        "Permanently removes an OCR result. Only allowed if no evaluation "
        "has been run against it yet. This action is irreversible."
    ),
)
async def delete_ocr(
    ocr_id: str,
    db: aiosqlite.Connection = Depends(get_db),
):
    ocr_repo  = OcrRepository(db)
    eval_repo = EvaluationRepository(db)

    existing = await ocr_repo.find_by_id(ocr_id)
    if not existing:
        raise HTTPException(status_code=404, detail="OCR result not found.")

    evaluation = await eval_repo.find_by_id_via_ocr(ocr_id)
    if evaluation:
        raise HTTPException(
            status_code=409,
            detail="Cannot delete OCR result — an evaluation already exists for it. Delete the evaluation first.",
        )

    await ocr_repo.delete(ocr_id)
    return OcrDeleteResponse(
        ocr_id=ocr_id,
        message="OCR result deleted successfully.",
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