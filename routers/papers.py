from fastapi import APIRouter, UploadFile, File, HTTPException, Depends, Query
from fastapi.responses import StreamingResponse
import csv
import io
import aiosqlite

from db.database import get_db
from db.repository import PaperRepository
from db.eval_repository import EvaluationRepository
from services.ocr_service import OCRService
from services.rubric_service import RubricService
from services.paper_processor import compute_sha256, generate_paper_id
from models.schemas import (
    PaperOcrResponse,
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
# POST /papers   — Step 1: upload PDF, run OCR, return parsed paper
# ---------------------------------------------------------------------------

@router.post(
    "",
    response_model=PaperOcrResponse,
    summary="Upload a question paper PDF",
    description=(
        "Accepts a question paper PDF and runs OCR to extract questions and "
        "metadata. No rubric is generated yet. Returns paper_id and parsed_paper. "
        "Call /papers/{paper_id}/rubric:generate next with the desired strictness."
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

    existing = await repo.find_by_hash(sha256_hash)
    if existing:
        return PaperOcrResponse(
            paper_id=existing.paper_id,
            sha256_hash=sha256_hash,
            is_duplicate=True,
            parsed_paper=existing.parsed_paper,
            message=(
                "This paper was already uploaded. "
                "You may call /papers/{paper_id}/rubric:generate again with a "
                "different strictness, or proceed to confirm."
            ),
        )

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
        message=(
            "OCR complete. Call /papers/{paper_id}/rubric:generate with a "
            "strictness level to generate the marking rubric."
        ),
    )


# ---------------------------------------------------------------------------
# POST /papers/{paper_id}/rubric:generate   — Step 2: generate rubric
# ---------------------------------------------------------------------------

@router.post(
    "/{paper_id}/rubric:generate",
    response_model=RubricGenerateResponse,
    summary="Generate a marking rubric for a paper",
    description=(
        "Generates a marking rubric for an OCR'd paper. "
        "Select a strictness level: easy, medium, hard, or extreme. "
        "Can be called multiple times to regenerate with a different strictness. "
        "Call /papers/{paper_id}:confirm after reviewing."
    ),
)
async def generate_rubric(
    paper_id: str,
    body: RubricGenerateRequest,
    db: aiosqlite.Connection = Depends(get_db),
):
    repo = PaperRepository(db)
    paper = await repo.find_by_id(paper_id)
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

    await repo.update_rubric(paper_id, rubric)

    return RubricGenerateResponse(
        paper_id=paper_id,
        strictness=body.strictness,
        rubric=build_rubric_response(rubric),
        message=f"Rubric generated with '{body.strictness}' strictness. Review and confirm when ready.",
    )


# ---------------------------------------------------------------------------
# POST /papers/{paper_id}:confirm   — Step 3: confirm paper + rubric
# ---------------------------------------------------------------------------

@router.post(
    "/{paper_id}:confirm",
    response_model=PaperConfirmResponse,
    summary="Confirm the parsed paper and rubric",
    description=(
        "Finalises a paper after the examiner reviews and optionally edits "
        "the parsed questions and rubric. Marks the paper as confirmed. "
        "A rubric must have been generated before confirming."
    ),
)
async def confirm_paper(
    paper_id: str,
    body: PaperConfirmRequest,
    db: aiosqlite.Connection = Depends(get_db),
):
    repo = PaperRepository(db)
    existing = await repo.find_by_id(paper_id)
    if not existing:
        raise HTTPException(status_code=404, detail="Paper not found.")
    if existing.confirmed:
        raise HTTPException(status_code=409, detail="Paper is already confirmed.")
    if existing.rubric is None:
        raise HTTPException(
            status_code=400,
            detail="No rubric found. Call /papers/{paper_id}/rubric:generate before confirming.",
        )

    await repo.confirm(paper_id, body.parsed_paper, body.rubric)

    return PaperConfirmResponse(
        paper_id=paper_id,
        message="Paper confirmed and saved successfully.",
    )


# ---------------------------------------------------------------------------
# GET /papers
# ---------------------------------------------------------------------------

@router.get(
    "",
    response_model=list[PaperSummary],
    summary="List all uploaded papers",
)
async def list_papers(db: aiosqlite.Connection = Depends(get_db)):
    repo = PaperRepository(db)
    return await repo.list_all()


# ---------------------------------------------------------------------------
# GET /papers/{paper_id}
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
# DELETE /papers/{paper_id}
# ---------------------------------------------------------------------------

@router.delete(
    "/{paper_id}",
    response_model=PaperDeleteResponse,
    summary="Delete a paper and all linked data",
    description=(
        "Permanently removes a paper, its rubric, all linked submissions, "
        "and all evaluations. This action is irreversible."
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

    counts = await repo.delete(paper_id)

    deleted_parts = []
    if counts["ocr_results_deleted"]:
        deleted_parts.append(f"{counts['ocr_results_deleted']} submission(s)")
    if counts["evaluations_deleted"]:
        deleted_parts.append(f"{counts['evaluations_deleted']} evaluation(s)")

    message = "Paper deleted successfully."
    if deleted_parts:
        message += f" Also removed: {', '.join(deleted_parts)}."

    return PaperDeleteResponse(
        paper_id=paper_id,
        message=message,
        ocr_results_deleted=counts["ocr_results_deleted"],
        evaluations_deleted=counts["evaluations_deleted"],
    )

# ---------------------------------------------------------------------------
# GET /papers/{paper_id}/evaluations/export.csv
# Export all student evaluations for a paper as a CSV file
# ---------------------------------------------------------------------------

@router.get(
    "/{paper_id}/evaluations/export.csv",
    summary="Export all student evaluations as CSV",
    description=(
        "Downloads a CSV file containing one row per student with full evaluation "
        "detail — summary columns followed by per-question marks and Bloom's outcome. "
        "By default only confirmed evaluations are included. "
        "Pass ?include_unconfirmed=true to include unconfirmed evaluations as well."
    ),
    response_class=StreamingResponse,
    tags=["Evaluations"],
)
async def export_evaluations_csv(
    paper_id: str,
    include_unconfirmed: bool = Query(
        default=False,
        description="Include unconfirmed evaluations in the export.",
    ),
    db: aiosqlite.Connection = Depends(get_db),
):
    # Verify paper exists
    paper_repo = PaperRepository(db)
    paper = await paper_repo.find_by_id(paper_id)
    if not paper:
        raise HTTPException(status_code=404, detail="Paper not found.")

    eval_repo = EvaluationRepository(db)
    rows = await eval_repo.list_full_by_paper(
        paper_id=paper_id,
        confirmed_only=not include_unconfirmed,
    )

    if not rows:
        raise HTTPException(
            status_code=404,
            detail=(
                "No evaluations found for this paper."
                if include_unconfirmed
                else "No confirmed evaluations found. Pass ?include_unconfirmed=true to include unconfirmed."
            ),
        )

    # ── Collect all question IDs that appear across all evaluations ───────────
    # Sort so columns are always in question order.
    all_question_ids: list[int] = sorted({
        qe.question_id
        for row in rows
        for qe in row["report"].question_wise_evaluation
    })

    # ── Build CSV ─────────────────────────────────────────────────────────────
    output = io.StringIO()
    writer = csv.writer(output)

    # Header row
    # Fixed summary columns
    header = [
        "eval_id",
        "student_name",
        "roll_number",
        "confirmed",
        "full_marks",
        "total_attempted",
        "total_marks_awarded",
        "percentage",
        "overall_feedback",
    ]

    # Bloom breakdown columns — one per level present in any evaluation
    bloom_levels_present: list[str] = sorted({
        level
        for row in rows
        for level in row["report"].evaluation_summary.bloom_breakdown.keys()
    })
    for level in bloom_levels_present:
        header.append(f"bloom_{level}_awarded")
        header.append(f"bloom_{level}_total")
        header.append(f"bloom_{level}_pct")

    # Per-question columns: marks_awarded, max_marks, bloom_depth, bloom_outcome
    for qid in all_question_ids:
        header.append(f"q{qid}_marks_awarded")
        header.append(f"q{qid}_max_marks")
        header.append(f"q{qid}_bloom_depth")
        header.append(f"q{qid}_bloom_outcome")

    writer.writerow(header)

    # Data rows — one per student evaluation
    for row in rows:
        report  = row["report"]
        summary = report.evaluation_summary

        # Build per-question lookup keyed by question_id
        qe_lookup = {qe.question_id: qe for qe in report.question_wise_evaluation}

        data = [
            row["eval_id"],
            report.student_info.student_name,
            report.student_info.roll_number or "",
            "yes" if row["confirmed"] else "no",
            summary.full_marks,
            summary.total_attempted,
            summary.total_marks_awarded,
            summary.percentage,
            summary.overall_feedback.replace("\n", " "),
        ]

        # Bloom breakdown columns
        for level in bloom_levels_present:
            stat = summary.bloom_breakdown.get(level)
            if stat:
                data.append(stat.awarded_marks)
                data.append(stat.total_marks)
                data.append(stat.percentage)
            else:
                data.extend(["", "", ""])

        # Per-question columns
        for qid in all_question_ids:
            qe = qe_lookup.get(qid)
            if qe:
                data.append(qe.marks_awarded)
                data.append(qe.maximum_marks)
                data.append(qe.bloom_depth or "")
                data.append(qe.bloom_outcome or "")
            else:
                data.extend(["", "", "", ""])

        writer.writerow(data)

    # ── Stream response ───────────────────────────────────────────────────────
    output.seek(0)
    subject_slug = (
        paper.parsed_paper.metadata.subject_code.replace(" ", "_")
        if paper.parsed_paper.metadata.subject_code
        else paper_id[:8]
    )
    filename = f"evaluations_{subject_slug}.csv"

    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )