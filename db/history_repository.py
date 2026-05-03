"""
db/history_repository.py
------------------------
Handles all persistence for the rubric_history and evaluation_history tables.
"""

import json
from typing import List, Literal

import aiosqlite

from models.history import EvaluationHistoryRecord, RubricHistoryRecord


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _row_to_rubric_record(row: aiosqlite.Row) -> RubricHistoryRecord:
    return RubricHistoryRecord(
        paper_id=row["paper_id"],
        rubric_json=json.loads(row["rubric_json"]),
        parsed_paper_json=json.loads(row["parsed_paper_json"]),
        changed_at=row["changed_at"],
        action=row["action"],
    )


def _row_to_eval_record(row: aiosqlite.Row) -> EvaluationHistoryRecord:
    return EvaluationHistoryRecord(
        eval_id=row["eval_id"],
        evaluation_json=json.loads(row["evaluation_json"]),
        changed_at=row["changed_at"],
        action=row["action"],
    )


# ---------------------------------------------------------------------------
# Repository
# ---------------------------------------------------------------------------

class HistoryRepository:
    def __init__(self, db: aiosqlite.Connection) -> None:
        self.db = db

    # ------------------------------------------------------------------
    # Rubric history
    # ------------------------------------------------------------------

    async def save_rubric_snapshot(
        self,
        paper_id: str,
        rubric_json: str,           # raw JSON string (model_dump_json())
        parsed_paper_json: str,     # raw JSON string
        action: Literal["confirm", "edit"] = "confirm",
    ) -> None:
        """
        Persist the *current* rubric + parsed_paper state before it is
        overwritten by a confirm (or any other action).

        Call this BEFORE calling PaperRepository.confirm().
        """
        await self.db.execute(
            """
            INSERT INTO rubric_history (paper_id, rubric_json, parsed_paper_json, action)
            VALUES (?, ?, ?, ?)
            """,
            (paper_id, rubric_json, parsed_paper_json, action),
        )
        # NOTE: do NOT commit here — the caller's confirm() will commit once,
        # making the snapshot + update a single logical transaction.

    async def get_rubric_history(self, paper_id: str) -> List[RubricHistoryRecord]:
        """Return all history snapshots for a paper, newest first."""
        self.db.row_factory = aiosqlite.Row
        async with self.db.execute(
            """
            SELECT paper_id, rubric_json, parsed_paper_json,
                   changed_at, action
            FROM   rubric_history
            WHERE  paper_id = ?
            ORDER  BY changed_at DESC
            """,
            (paper_id,),
        ) as cursor:
            rows = await cursor.fetchall()
        return [_row_to_rubric_record(r) for r in rows]

    # ------------------------------------------------------------------
    # Evaluation history
    # ------------------------------------------------------------------

    async def save_evaluation_snapshot(
        self,
        eval_id: str,
        evaluation_json: str,       # raw JSON string (report.model_dump_json())
        action: Literal["confirm", "edit"] = "confirm",
    ) -> None:
        """
        Persist the *current* evaluation state before it is overwritten.

        Call this BEFORE calling EvaluationRepository.confirm().
        """
        await self.db.execute(
            """
            INSERT INTO evaluation_history (eval_id, evaluation_json, action)
            VALUES (?, ?, ?)
            """,
            (eval_id, evaluation_json, action),
        )

    async def get_evaluation_history(self, eval_id: str) -> List[EvaluationHistoryRecord]:
        """Return all history snapshots for an evaluation, newest first."""
        self.db.row_factory = aiosqlite.Row
        async with self.db.execute(
            """
            SELECT eval_id, evaluation_json, changed_at, action
            FROM   evaluation_history
            WHERE  eval_id = ?
            ORDER  BY changed_at DESC
            """,
            (eval_id,),
        ) as cursor:
            rows = await cursor.fetchall()
        return [_row_to_eval_record(r) for r in rows]
