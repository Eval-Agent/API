"""
routers/history.py
------------------
Provides read-only history endpoints:

    GET /papers/{paper_id}/history
    GET /evaluations/{eval_id}/history

Mount both routers in main.py (see bottom of this file for instructions).
"""

import aiosqlite
from fastapi import APIRouter, Depends, HTTPException

from db.database import get_db
from db.eval_repository import EvaluationRepository
from db.history_repository import HistoryRepository
from db.repository import PaperRepository
from models.history import EvaluationHistoryResponse, RubricHistoryResponse

# ---------------------------------------------------------------------------
# Rubric history router  →  prefix="/papers"
# ---------------------------------------------------------------------------

papers_history_router = APIRouter(prefix="/papers", tags=["History"])


@papers_history_router.get(
    "/{paper_id}/history",
    response_model=RubricHistoryResponse,
    summary="Get rubric change history for a paper",
)
async def get_rubric_history(
    paper_id: str,
    db: aiosqlite.Connection = Depends(get_db),
):
    """
    Returns all historical snapshots of the rubric and parsed-paper for
    `paper_id`, ordered from most-recent to oldest.

    Each snapshot was captured immediately *before* a confirm (or edit)
    operation, so it reflects the state that was replaced.
    """
    paper_repo = PaperRepository(db)
    paper = await paper_repo.find_by_id(paper_id)
    if not paper:
        raise HTTPException(status_code=404, detail="Paper not found.")

    history_repo = HistoryRepository(db)
    records = await history_repo.get_rubric_history(paper_id)

    return RubricHistoryResponse(paper_id=paper_id, history=records)


# ---------------------------------------------------------------------------
# Evaluation history router  →  prefix="/submissions"
# ---------------------------------------------------------------------------

eval_history_router = APIRouter(prefix="/submissions", tags=["History"])


@eval_history_router.get(
    "/{submission_id}/evaluation/history",
    response_model=EvaluationHistoryResponse,
    summary="Get evaluation change history for a submission",
)
async def get_evaluation_history(
    submission_id: str,
    db: aiosqlite.Connection = Depends(get_db),
):
    """
    Returns all historical snapshots of the evaluation report for the
    submission identified by `submission_id` (looked up via its OCR id),
    ordered from most-recent to oldest.
    """
    eval_repo = EvaluationRepository(db)
    existing = await eval_repo.find_by_id_via_ocr(submission_id)
    if not existing:
        raise HTTPException(
            status_code=404,
            detail="No evaluation found for this submission.",
        )

    history_repo = HistoryRepository(db)
    records = await history_repo.get_evaluation_history(existing.eval_id)

    return EvaluationHistoryResponse(eval_id=existing.eval_id, history=records)


# ---------------------------------------------------------------------------
# main.py registration instructions
# ---------------------------------------------------------------------------
# Add the following two lines in your main.py where other routers are mounted:
#
#   from routers.history import papers_history_router, eval_history_router
#
#   app.include_router(papers_history_router)
#   app.include_router(eval_history_router)
