import json
import aiosqlite
from typing import Optional

from models.schemas import ParsedPaper, Rubric, PaperSummary, PaperDetailResponse, build_rubric_response
from db.history_repository import HistoryRepository


class PaperRepository:
    def __init__(self, db: aiosqlite.Connection):
        self.db = db

    async def find_by_hash(self, sha256_hash: str) -> Optional[PaperDetailResponse]:
        async with self.db.execute(
            "SELECT * FROM papers WHERE sha256_hash = ?", (sha256_hash,)
        ) as cursor:
            row = await cursor.fetchone()
            if not row:
                return None
            return self._row_to_detail(row)

    async def find_by_id(self, paper_id: str) -> Optional[PaperDetailResponse]:
        async with self.db.execute(
            "SELECT * FROM papers WHERE paper_id = ?", (paper_id,)
        ) as cursor:
            row = await cursor.fetchone()
            if not row:
                return None
            return self._row_to_detail(row)

    async def insert(
        self,
        paper_id: str,
        sha256_hash: str,
        parsed_paper: ParsedPaper,
        rubric: Optional[Rubric] = None,
    ) -> None:
        await self.db.execute(
            """
            INSERT INTO papers (paper_id, user_id, sha256_hash, parsed_paper, rubric, confirmed)
            VALUES (?, ?, ?, ?, ?, 0)
            """,
            (
                paper_id,
                "default",  # TODO: get from auth context
                sha256_hash,
                parsed_paper.model_dump_json(),
                rubric.model_dump_json() if rubric else None,
            ),
        )
        await self.db.commit()

    async def update_rubric(self, paper_id: str, rubric: Rubric) -> None:
        await self.db.execute(
            "UPDATE papers SET rubric = ? WHERE paper_id = ?",
            (rubric.model_dump_json(), paper_id),
        )
        await self.db.commit()

    async def confirm(
        self,
        paper_id: str,
        parsed_paper,   # ParsedPaper
        rubric,         # Rubric
    ) -> None:
        """
        1. Snapshot current DB state into rubric_history.
        2. Overwrite with the new (confirmed) values.
        Both writes share one commit → atomic.
        """
        # -- Step 1: fetch the current row so we snapshot what is in the DB,
        #            not what the client just sent.
        self.db.row_factory = aiosqlite.Row
        async with self.db.execute(
            "SELECT rubric, parsed_paper FROM papers WHERE paper_id = ?",
            (paper_id,),
        ) as cur:
            row = await cur.fetchone()

        if row and row["rubric"] is not None:
            # Only snapshot when there is already data worth preserving.
            history_repo = HistoryRepository(self.db)
            await history_repo.save_rubric_snapshot(
                paper_id=paper_id,
                rubric_json=row["rubric"],
                parsed_paper_json=row["parsed_paper"],
                action="confirm",
            )

        # -- Step 2: write the new confirmed state.
        await self.db.execute(
            """
            UPDATE papers
            SET parsed_paper = ?,
                rubric       = ?,
                confirmed    = 1
            WHERE paper_id = ?
            """,
            (
                parsed_paper.model_dump_json(),
                rubric.model_dump_json(),
                paper_id,
            ),
        )
        await self.db.commit()   # single commit covers both writes

    async def list_all(self) -> list[PaperSummary]:
        async with self.db.execute(
            "SELECT paper_id, sha256_hash, parsed_paper, rubric, confirmed FROM papers ORDER BY created_at DESC"
        ) as cursor:
            rows = await cursor.fetchall()
            summaries = []
            for row in rows:
                paper = ParsedPaper.model_validate_json(row["parsed_paper"])
                summaries.append(
                    PaperSummary(
                        paper_id=row["paper_id"],
                        sha256_hash=row["sha256_hash"],
                        subject_name=paper.metadata.subject_name,
                        subject_code=paper.metadata.subject_code,
                        exam_type=paper.metadata.exam_type,
                        confirmed=bool(row["confirmed"]),
                        has_rubric=row["rubric"] is not None,
                    )
                )
            return summaries

    async def delete(self, paper_id: str) -> dict:
        """Delete a paper and cascade to ocr_results and evaluations.
        Returns counts of deleted rows for each table."""
        # Count children before deletion for the response
        async with self.db.execute(
            "SELECT COUNT(*) FROM evaluations WHERE paper_id = ?", (paper_id,)
        ) as cur:
            eval_count = (await cur.fetchone())[0]

        async with self.db.execute(
            "SELECT COUNT(*) FROM ocr_results WHERE paper_id = ?", (paper_id,)
        ) as cur:
            ocr_count = (await cur.fetchone())[0]

        await self.db.execute("DELETE FROM papers WHERE paper_id = ?", (paper_id,))
        await self.db.commit()

        return {"ocr_results_deleted": ocr_count, "evaluations_deleted": eval_count}

    # ------------------------------------------------------------------
    def _row_to_detail(self, row) -> PaperDetailResponse:
        rubric_json = row["rubric"]
        rubric_response = None
        if rubric_json:
            rubric = Rubric.model_validate_json(rubric_json)
            rubric_response = build_rubric_response(rubric)
        return PaperDetailResponse(
            paper_id=row["paper_id"],
            sha256_hash=row["sha256_hash"],
            confirmed=bool(row["confirmed"]),
            parsed_paper=ParsedPaper.model_validate_json(row["parsed_paper"]),
            rubric=rubric_response,
        )