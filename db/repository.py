import json
import aiosqlite
from typing import Optional

from models.schemas import ParsedPaper, Rubric, PaperSummary, PaperDetailResponse, build_rubric_response


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
            INSERT INTO papers (paper_id, sha256_hash, parsed_paper, rubric, confirmed)
            VALUES (?, ?, ?, ?, 0)
            """,
            (
                paper_id,
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
        parsed_paper: ParsedPaper,
        rubric: Rubric,
    ) -> None:
        """Upsert the (possibly edited) paper and mark it confirmed."""
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
        await self.db.commit()

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

    async def delete(self, paper_id: str) -> bool:
        """Delete a paper by ID. Returns True if a row was deleted, False if not found."""
        async with self.db.execute(
            "DELETE FROM papers WHERE paper_id = ?", (paper_id,)
        ) as cursor:
            await self.db.commit()
            return cursor.rowcount > 0

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