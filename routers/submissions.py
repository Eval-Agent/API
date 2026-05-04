"""
routers/submissions.py
-----------------------
Submissions router  (/api/v1/papers/{paper_id}/submissions  +  /api/v1/submissions)

A "submission" is a student answer PDF that has been OCR'd.
question_id is now a string throughout.
"""

from fastapi import APIRouter, UploadFile, File, HTTPException, Depends
import aiosqlite
import uuid
import hashlib
import json

from db.database import get_db
from db.repository import PaperRepository
from db.eval_repository import OcrRepository, EvaluationRepository
from services.ocr_answer_service import OCRAnswerService
from models.schemas import (
    SubmissionResponse,
    SubmissionSummaryResponse,
    SubmissionStudentInfoUpdateRequest,
    SubmissionDeleteResponse,
    ExtractedAnswer,
    StudentInfo,
)

papers_router = APIRouter()
flat_router   = APIRouter()

_ocr_svc = OCRAnswerService()


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _build_submission_response(record: dict, is_duplicate: bool, message: str) -> SubmissionResponse:
    return SubmissionResponse(
        submission_id=record["ocr_id"],
        paper_id=record["paper_id"],
        answer_sha256=record["answer_sha256"],
        is_duplicate=is_duplicate,
        student_info=StudentInfo.model_validate_json(record["student_info"]),
        extracted_answers=[
            ExtractedAnswer(**a) for a in json.loads(record["extracted_answers"])
        ],
        message=message,
    )


# ---------------------------------------------------------------------------
# POST /papers/{paper_id}/submissions
# ---------------------------------------------------------------------------

@papers_router.post(
    "/{paper_id}/submissions",
    response_model=SubmissionResponse,
    summary="Upload a student answer PDF and extract answers via OCR",
    description=(
        "Accepts a student answer PDF for a confirmed question paper. "
        "Runs OCR to extract student info and all answers. "
        "Returns a submission_id to use in the evaluate step."
    ),
    tags=["Submissions"],
)
async def create_submission(
    paper_id: str,
    file: UploadFile = File(..., description="Student answer sheet PDF"),
    db: aiosqlite.Connection = Depends(get_db),
):
    if file.content_type not in ("application/pdf", "application/octet-stream"):
        raise HTTPException(status_code=400, detail="Only PDF files are accepted.")

    pdf_bytes = await file.read()
    if not pdf_bytes:
        raise HTTPException(status_code=400, detail="Uploaded file is empty.")

    paper_repo = PaperRepository(db)
    paper = await paper_repo.find_by_id(paper_id)
    if not paper:
        raise HTTPException(status_code=404, detail="Question paper not found.")
    if not paper.confirmed:
        raise HTTPException(
            status_code=409,
            detail="Question paper is not yet confirmed. Confirm it before uploading submissions.",
        )

    answer_sha256 = _sha256(pdf_bytes)
    ocr_repo = OcrRepository(db)
    existing = await ocr_repo.find_by_answer_hash(answer_sha256)
    if existing:
        return _build_submission_response(
            existing,
            is_duplicate=True,
            message="This answer sheet was already uploaded. Showing existing submission.",
        )

    try:
        ocr_result = await _ocr_svc.extract_answers(pdf_bytes)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Answer OCR failed: {str(exc)}")

    extracted_answers = [
        ExtractedAnswer(
            question_id=a.question_id,       # already a string
            answer_markdown=a.answer_markdown,
        )
        for a in ocr_result.answers
    ]
    student_info = StudentInfo(
        student_name=ocr_result.student_info.student_name,
        roll_number=ocr_result.student_info.roll_number,
    )

    submission_id = str(uuid.uuid4())
    await ocr_repo.insert(
        ocr_id=submission_id,
        paper_id=paper_id,
        answer_sha256=answer_sha256,
        student_info=student_info,
        extracted_answers=extracted_answers,
    )

    return SubmissionResponse(
        submission_id=submission_id,
        paper_id=paper_id,
        answer_sha256=answer_sha256,
        is_duplicate=False,
        student_info=student_info,
        extracted_answers=extracted_answers,
        message="OCR complete. Call /submissions/{submission_id}/evaluation:generate to evaluate.",
    )


# ---------------------------------------------------------------------------
# GET /papers/{paper_id}/submissions
# ---------------------------------------------------------------------------

@papers_router.get(
    "/{paper_id}/submissions",
    response_model=list[SubmissionSummaryResponse],
    summary="List all submissions for a question paper",
    tags=["Submissions"],
)
async def list_submissions(
    paper_id: str,
    db: aiosqlite.Connection = Depends(get_db),
):
    paper_repo = PaperRepository(db)
    if not await paper_repo.find_by_id(paper_id):
        raise HTTPException(status_code=404, detail="Question paper not found.")

    ocr_repo = OcrRepository(db)
    return await ocr_repo.list_by_paper(paper_id)


# ---------------------------------------------------------------------------
# GET /submissions/{submission_id}
# ---------------------------------------------------------------------------

@flat_router.get(
    "/{submission_id}",
    response_model=SubmissionResponse,
    summary="Get full detail of a single submission",
    tags=["Submissions"],
)
async def get_submission(
    submission_id: str,
    db: aiosqlite.Connection = Depends(get_db),
):
    ocr_repo = OcrRepository(db)
    record = await ocr_repo.find_by_id(submission_id)
    if not record:
        raise HTTPException(status_code=404, detail="Submission not found.")

    return _build_submission_response(
        record,
        is_duplicate=False,
        message="Submission retrieved successfully.",
    )


# ---------------------------------------------------------------------------
# POST /submissions/{submission_id}:update-student-info
# ---------------------------------------------------------------------------

@flat_router.post(
    "/{submission_id}:update-student-info",
    response_model=SubmissionResponse,
    summary="Correct student info on a submission",
    tags=["Submissions"],
)
async def update_submission_student_info(
    submission_id: str,
    body: SubmissionStudentInfoUpdateRequest,
    db: aiosqlite.Connection = Depends(get_db),
):
    ocr_repo = OcrRepository(db)
    record = await ocr_repo.find_by_id(submission_id)
    if not record:
        raise HTTPException(status_code=404, detail="Submission not found.")

    updated_info = StudentInfo(
        student_name=body.student_name,
        roll_number=body.roll_number,
    )
    await ocr_repo.update_student_info(submission_id, updated_info)

    record["student_info"] = updated_info.model_dump_json()
    return _build_submission_response(
        record,
        is_duplicate=False,
        message="Student info updated successfully.",
    )


# ---------------------------------------------------------------------------
# DELETE /submissions/{submission_id}
# ---------------------------------------------------------------------------

@flat_router.delete(
    "/{submission_id}",
    response_model=SubmissionDeleteResponse,
    summary="Delete a submission",
    tags=["Submissions"],
)
async def delete_submission(
    submission_id: str,
    db: aiosqlite.Connection = Depends(get_db),
):
    ocr_repo  = OcrRepository(db)
    eval_repo = EvaluationRepository(db)

    record = await ocr_repo.find_by_id(submission_id)
    if not record:
        raise HTTPException(status_code=404, detail="Submission not found.")

    if await eval_repo.find_by_id_via_ocr(submission_id):
        raise HTTPException(
            status_code=409,
            detail=(
                "Cannot delete submission — an evaluation already exists for it. "
                "Delete the evaluation first."
            ),
        )

    await ocr_repo.delete(submission_id)
    return SubmissionDeleteResponse(
        submission_id=submission_id,
        message="Submission deleted successfully.",
    )