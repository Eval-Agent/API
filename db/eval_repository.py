import aiosqlite
from typing import Optional

from models.schemas import (
    EvaluationReport,
    EvaluationResponse,
    EvaluationSummaryResponse,
)


class EvaluationRepository:
    def __init__(self, db: aiosqlite.Connection):
        self.db = db

    async def find_by_answer_hash(self, answer_sha256: str) -> Optional[EvaluationResponse]:
        async with self.db.execute(
            "SELECT * FROM evaluations WHERE answer_sha256 = ?", (answer_sha256,)
        ) as cursor:
            row = await cursor.fetchone()
            if not row:
                return None
            return self._row_to_response(row, is_duplicate=True)

    async def find_by_id(self, eval_id: str) -> Optional[EvaluationResponse]:
        async with self.db.execute(
            "SELECT * FROM evaluations WHERE eval_id = ?", (eval_id,)
        ) as cursor:
            row = await cursor.fetchone()
            if not row:
                return None
            return self._row_to_response(row)

    async def list_by_paper(self, paper_id: str) -> list[EvaluationSummaryResponse]:
        async with self.db.execute(
            """
            SELECT eval_id, paper_id, student_info, evaluation, confirmed
            FROM evaluations
            WHERE paper_id = ?
            ORDER BY created_at DESC
            """,
            (paper_id,),
        ) as cursor:
            rows = await cursor.fetchall()
            summaries = []
            for row in rows:
                report = EvaluationReport.model_validate_json(row["evaluation"])
                summaries.append(
                    EvaluationSummaryResponse(
                        eval_id=row["eval_id"],
                        paper_id=row["paper_id"],
                        student_name=report.student_info.student_name,
                        roll_number=report.student_info.roll_number,
                        confirmed=bool(row["confirmed"]),
                    )
                )
            return summaries

    async def insert(
        self,
        eval_id: str,
        paper_id: str,
        answer_sha256: str,
        report: EvaluationReport,
    ) -> None:
        await self.db.execute(
            """
            INSERT INTO evaluations
                (eval_id, paper_id, answer_sha256, student_info, evaluation, confirmed)
            VALUES (?, ?, ?, ?, ?, 0)
            """,
            (
                eval_id,
                paper_id,
                answer_sha256,
                report.student_info.model_dump_json(),
                report.model_dump_json(),
            ),
        )
        await self.db.commit()

    async def confirm(
        self,
        eval_id: str,
        report: EvaluationReport,
    ) -> None:
        """Save examiner-corrected student info + evaluation and mark confirmed."""
        await self.db.execute(
            """
            UPDATE evaluations
            SET student_info = ?,
                evaluation   = ?,
                confirmed    = 1
            WHERE eval_id = ?
            """,
            (
                report.student_info.model_dump_json(),
                report.model_dump_json(),
                eval_id,
            ),
        )
        await self.db.commit()

    async def delete(self, eval_id: str) -> bool:
        async with self.db.execute(
            "DELETE FROM evaluations WHERE eval_id = ?", (eval_id,)
        ) as cursor:
            await self.db.commit()
            return cursor.rowcount > 0

    # ------------------------------------------------------------------

    def _row_to_response(self, row, is_duplicate: bool = False) -> EvaluationResponse:
        report = EvaluationReport.model_validate_json(row["evaluation"])
        return EvaluationResponse(
            eval_id=row["eval_id"],
            paper_id=row["paper_id"],
            answer_sha256=row["answer_sha256"],
            is_duplicate=is_duplicate,
            student_info=report.student_info,
            extracted_answers=report.extracted_answers,
            evaluation_summary=report.evaluation_summary,
            question_wise_evaluation=report.question_wise_evaluation,
            confirmed=bool(row["confirmed"]),
            message="Evaluation loaded successfully.",
        )