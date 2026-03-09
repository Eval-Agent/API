from fastapi import APIRouter, UploadFile, File, HTTPException, Depends
from fastapi.responses import JSONResponse
import aiosqlite

from db.database import get_db
from db.repository import PaperRepository
from services.paper_processor import PaperProcessor, compute_sha256, generate_paper_id
from models.schemas import (
    PaperUploadResponse,
    PaperConfirmRequest,
    PaperConfirmResponse,
    PaperDeleteResponse,
    PaperSummary,
    PaperDetailResponse,
    build_rubric_response,
)

router = APIRouter()
processor = PaperProcessor()


# ---------------------------------------------------------------------------
# POST /upload
# ---------------------------------------------------------------------------

@router.post(
    "/upload",
    response_model=PaperUploadResponse,
    summary="Upload a question paper PDF",
    description=(
        "Accepts a question paper PDF. Computes its SHA-256 hash and checks for duplicates. "
        "If new, runs OCR and rubric generation. Returns parsed paper + rubric for review. "
        "Call /confirm after the user reviews."
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
        return PaperUploadResponse(
            paper_id=existing.paper_id,
            sha256_hash=sha256_hash,
            is_duplicate=True,
            parsed_paper=existing.parsed_paper,
            rubric=build_rubric_response(existing.rubric),
            message="Duplicate detected. Returning existing paper.",
        )
    # ── New paper: OCR → Rubric ──────────────────────────────────────────────
    try:
        parsed_paper, rubric = await processor.process(pdf_bytes)
    except Exception as exc:
        raise HTTPException(
            status_code=502,
            detail=f"AI processing failed: {str(exc)}",
        )

    paper_id = generate_paper_id()
    await repo.insert(paper_id, sha256_hash, parsed_paper, rubric)

    return PaperUploadResponse(
        paper_id=paper_id,
        sha256_hash=sha256_hash,
        is_duplicate=False,
        parsed_paper=parsed_paper,
        rubric=build_rubric_response(rubric),
        message="Paper processed successfully. Please review and confirm.",
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