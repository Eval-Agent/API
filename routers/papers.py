from fastapi import APIRouter, UploadFile, File, HTTPException, Depends
from fastapi.responses import JSONResponse
import aiosqlite

from db.database import get_db
from db.repository import PaperRepository
from services.ocr_service import OCRService
from services.rubric_service import RubricService
from services.paper_processor import compute_sha256, generate_paper_id
from models.schemas import (
    PaperOcrResponse,
    PaperUploadResponse,
    RubricGenerateRequest,
    RubricGenerateResponse,
    PaperConfirmRequest,
    PaperConfirmResponse,
    PaperDeleteResponse,
    PaperSummary,
    PaperDetailResponse,
    build_rubric_response,
)

router = APIRouter()
_ocr_svc    = OCRService()
_rubric_svc = RubricService()


# ---------------------------------------------------------------------------
# POST /upload  — Step 1: OCR only
# ---------------------------------------------------------------------------

@router.post(
    "/upload",
    response_model=PaperOcrResponse,
    summary="Upload a question paper PDF (OCR only)",
    description=(
        "Accepts a question paper PDF, runs OCR to extract questions and metadata. "
        "No rubric is generated yet. Returns paper_id and parsed_paper. "
        "Call /generate-rubric next with the desired strictness level."
    ),
)
async def upload_paper(
    file: UploadFile = File(..., description="Question paper PDF"),
    db: aiosqlite.Connection = Depends(get_db),
):
    if file.content_type not in ("application/pdf", "application/octet-stream"):
        raise HTTPException(status_code=400, detail="Only PDF files are accepted.")

    pdf_bytes = await file.read()
    if not pdf_bytes:
        raise HTTPException(status_code=400, detail="Uploaded file is empty.")

    sha256_hash = compute_sha256(pdf_bytes)
    repo = PaperRepository(db)

    # ── Duplicate check ──────────────────────────────────────────────────────
    existing = await repo.find_by_hash(sha256_hash)
    if existing:
        return PaperOcrResponse(
            paper_id=existing.paper_id,
            sha256_hash=sha256_hash,
            is_duplicate=True,
            parsed_paper=existing.parsed_paper,
            message=(
                "This paper was already uploaded. "
                "You may call /generate-rubric again with a different strictness, or proceed to confirm."
            ),
        )

    # ── New paper: OCR only ──────────────────────────────────────────────────
    try:
        parsed_paper = await _ocr_svc.extract_questions(pdf_bytes)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"OCR failed: {str(exc)}")

    paper_id = generate_paper_id()
    await repo.insert(paper_id, sha256_hash, parsed_paper, rubric=None)

    return PaperOcrResponse(
        paper_id=paper_id,
        sha256_hash=sha256_hash,
        is_duplicate=False,
        parsed_paper=parsed_paper,
        message="OCR complete. Call /generate-rubric with strictness to generate the marking rubric.",
    )


# ---------------------------------------------------------------------------
# POST /generate-rubric  — Step 2: Rubric generation with strictness
# ---------------------------------------------------------------------------

@router.post(
    "/generate-rubric",
    response_model=RubricGenerateResponse,
    summary="Generate rubric for an OCR'd paper",
    description=(
        "Generates a marking rubric for a paper that has already been OCR'd. "
        "Select a strictness level: easy, medium, hard, or extreme. "
        "Can be called multiple times to regenerate with a different strictness. "
        "Call /confirm after reviewing the rubric."
    ),
)
async def generate_rubric(
    body: RubricGenerateRequest,
    db: aiosqlite.Connection = Depends(get_db),
):
    repo = PaperRepository(db)
    paper = await repo.find_by_id(body.paper_id)
    if not paper:
        raise HTTPException(status_code=404, detail="Paper not found.")
    if paper.confirmed:
        raise HTTPException(
            status_code=409,
            detail="Paper is already confirmed. Cannot regenerate rubric.",
        )

    try:
        rubric = await _rubric_svc.generate_rubric(
            parsed_paper=paper.parsed_paper,
            strictness=body.strictness,
        )
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Rubric generation failed: {str(exc)}")

    await repo.update_rubric(body.paper_id, rubric)

    return RubricGenerateResponse(
        paper_id=body.paper_id,
        strictness=body.strictness,
        rubric=build_rubric_response(rubric),
        message=f"Rubric generated with '{body.strictness}' strictness. Review and confirm when ready.",
    )


# ---------------------------------------------------------------------------
# POST /confirm
# ---------------------------------------------------------------------------

@router.post(
    "/confirm",
    response_model=PaperConfirmResponse,
    summary="Confirm (and optionally edit) the parsed paper + rubric",
    description=(
        "After the user reviews the AI output, send the final (possibly edited) "
        "paper and rubric here to persist them as confirmed."
    ),
)
async def confirm_paper(
    body: PaperConfirmRequest,
    db: aiosqlite.Connection = Depends(get_db),
):
    repo = PaperRepository(db)
    existing = await repo.find_by_id(body.paper_id)
    if not existing:
        raise HTTPException(status_code=404, detail="Paper not found.")
    if existing.confirmed:
        raise HTTPException(status_code=409, detail="Paper is already confirmed.")
    if existing.rubric is None:
        raise HTTPException(
            status_code=400,
            detail="No rubric found for this paper. Call /generate-rubric before confirming.",
        )

    await repo.confirm(body.paper_id, body.parsed_paper, body.rubric)

    return PaperConfirmResponse(
        paper_id=body.paper_id,
        message="Paper confirmed and saved successfully.",
    )


# ---------------------------------------------------------------------------
# GET /
# ---------------------------------------------------------------------------

@router.get(
    "/",
    response_model=list[PaperSummary],
    summary="List all uploaded papers",
)
async def list_papers(db: aiosqlite.Connection = Depends(get_db)):
    repo = PaperRepository(db)
    return await repo.list_all()


# ---------------------------------------------------------------------------
# GET /{paper_id}
# ---------------------------------------------------------------------------

@router.get(
    "/{paper_id}",
    response_model=PaperDetailResponse,
    summary="Get full detail of a specific paper",
)
async def get_paper(
    paper_id: str,
    db: aiosqlite.Connection = Depends(get_db),
):
    repo = PaperRepository(db)
    paper = await repo.find_by_id(paper_id)
    if not paper:
        raise HTTPException(status_code=404, detail="Paper not found.")
    return paper


# ---------------------------------------------------------------------------
# DELETE /{paper_id}
# ---------------------------------------------------------------------------

@router.delete(
    "/{paper_id}",
    response_model=PaperDeleteResponse,
    summary="Delete a paper from the database",
    description=(
        "Permanently removes a paper and its rubric from the database. "
        "Both confirmed and unconfirmed papers can be deleted. "
        "This action is irreversible."
    ),
)
async def delete_paper(
    paper_id: str,
    db: aiosqlite.Connection = Depends(get_db),
):
    repo = PaperRepository(db)
    existing = await repo.find_by_id(paper_id)
    if not existing:
        raise HTTPException(status_code=404, detail="Paper not found.")

    await repo.delete(paper_id)

    return PaperDeleteResponse(
        paper_id=paper_id,
        message="Paper deleted successfully.",
    )