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
    tags=["Question Papers"],
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
    tags=["Question Papers"],
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
    tags=["Question Papers"],
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
    tags=["Question Papers"],
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
    tags=["Question Papers"],
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
    tags=["Question Papers"],
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

    # ── Bloom level → BT number mapping ─────────────────────────────────────
    _BLOOM_TO_BT = {
        "remember":   "BT1",
        "understand": "BT2",
        "apply":      "BT3",
        "analyze":    "BT4",
        "analyse":    "BT4",
        "evaluate":   "BT5",
        "create":     "BT6",
    }

    # Build question metadata lookup from the paper (ordered by question_id)
    paper_q_lookup = {
        pq.question_id: pq
        for pq in paper.parsed_paper.questions
    }

    # ── Collect all question IDs in paper order ────────────────────────────────
    all_question_ids: list[int] = sorted(paper_q_lookup.keys())

    # Pull paper-level metadata for the fixed columns
    meta = paper.parsed_paper.metadata
    dept   = meta.stream or ""          # e.g. "CSE/CSE(DS)"
    degree = meta.degree or ""          # e.g. "B.Tech"
    subject_class = meta.subject_name or ""   # e.g. "Artificial Intelligence & Machine Learning"

    # ── Build CSV ─────────────────────────────────────────────────────────────
    output = io.StringIO()
    writer = csv.writer(output)

    # ── Row 1: Column headers ─────────────────────────────────────────────────
    # Fixed student-info columns + one column per question
    header = [
        "dept",
        "year",
        "enrollment no.",
        "Name",
        "Class",
        "roll no",
    ]
    for qid in all_question_ids:
        header.append(f"q{qid}")

    # Extra summary columns after questions
    header += ["total_marks_awarded", "full_marks", "percentage", "confirmed", "overall_feedback"]

    writer.writerow(header)

    # ── Row 2: Bloom's Taxonomy labels (fixed per paper, same for every student)
    # Fixed columns get blank cells; question columns get BTx label
    bloom_row = ["", "", "", "", "", ""]   # blanks for the 6 student-info columns
    for qid in all_question_ids:
        pq = paper_q_lookup.get(qid)
        if pq and pq.bloom_level:
            # bloom_level may be already normalised ("remember") or raw ("Remember", "L3", "BTL3")
            bl = pq.bloom_level.strip().lower()
            bt = _BLOOM_TO_BT.get(bl, "")
            if not bt:
                # Handle L1-L6 / BTL1-BTL6 notation
                if bl.startswith("btl") and bl[3:].isdigit():
                    bt = f"BT{bl[3:]}"
                elif bl.startswith("l") and bl[1:].isdigit():
                    bt = f"BT{bl[1:]}"
                else:
                    bt = pq.bloom_level  # keep as-is if unrecognised
        else:
            bt = ""
        bloom_row.append(bt)

    bloom_row += ["", "", "", "", ""]   # blanks for summary columns
    writer.writerow(bloom_row)

    # ── Row 3+: One student per row ───────────────────────────────────────────
    for row in rows:
        report  = row["report"]
        summary = report.evaluation_summary

        # Build per-question lookup keyed by question_id
        qe_lookup = {qe.question_id: qe for qe in report.question_wise_evaluation}

        data = [
            dept,
            degree,
            report.student_info.roll_number or "",   # enrollment no. (best proxy)
            report.student_info.student_name,
            subject_class,
            report.student_info.roll_number or "",
        ]

        # Marks per question — in question order
        for qid in all_question_ids:
            qe = qe_lookup.get(qid)
            if qe:
                # Show marks only for counted questions; uncounted shown as "(x)" to flag it
                if qe.counted:
                    data.append(qe.marks_awarded)
                else:
                    data.append(f"({qe.marks_awarded})")
            else:
                data.append("")   # question not attempted

        # Summary columns
        data += [
            summary.total_marks_awarded,
            summary.full_marks,
            summary.percentage,
            "yes" if row["confirmed"] else "no",
            summary.overall_feedback.replace("\n", " "),
        ]

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