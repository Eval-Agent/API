import aiosqlite
from typing import Optional

from models.schemas import (
    EvaluationReport,
    EvaluationResponse,
    EvaluationSummaryResponse,
    ExtractedAnswer,
    StudentInfo,
    OcrSummaryResponse,
)


# ---------------------------------------------------------------------------
# OCR Repository — ocr_results table
# ---------------------------------------------------------------------------

class OcrRepository:
    def __init__(self, db: aiosqlite.Connection):
        self.db = db

    async def find_by_answer_hash(self, answer_sha256: str) -> Optional[dict]:
        async with self.db.execute(
            "SELECT * FROM ocr_results WHERE answer_sha256 = ?", (answer_sha256,)
        ) as cursor:
            row = await cursor.fetchone()
            if not row:
                return None
            return dict(row)

    async def find_by_id(self, ocr_id: str) -> Optional[dict]:
        async with self.db.execute(
            "SELECT * FROM ocr_results WHERE ocr_id = ?", (ocr_id,)
        ) as cursor:
            row = await cursor.fetchone()
            if not row:
                return None
            return dict(row)

    async def insert(
        self,
        ocr_id: str,
        paper_id: str,
        answer_sha256: str,
        student_info: StudentInfo,
        extracted_answers: list[ExtractedAnswer],
    ) -> None:
        import json
        await self.db.execute(
            """
            INSERT INTO ocr_results
                (ocr_id, paper_id, answer_sha256, student_info, extracted_answers)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                ocr_id,
                paper_id,
                answer_sha256,
                student_info.model_dump_json(),
                json.dumps([a.model_dump() for a in extracted_answers]),
            ),
        )
        await self.db.commit()

    async def delete(self, ocr_id: str) -> bool:
        async with self.db.execute(
            "DELETE FROM ocr_results WHERE ocr_id = ?", (ocr_id,)
        ) as cursor:
            await self.db.commit()
            return cursor.rowcount > 0

    async def update_student_info(self, ocr_id: str, student_info: StudentInfo) -> bool:
        async with self.db.execute(
            "UPDATE ocr_results SET student_info = ? WHERE ocr_id = ?",
            (student_info.model_dump_json(), ocr_id),
        ) as cursor:
            await self.db.commit()
            return cursor.rowcount > 0

    async def list_by_paper(self, paper_id: str) -> list[OcrSummaryResponse]:
        """List all OCR results for a paper, flagging which ones already have an evaluation."""
        async with self.db.execute(
            """
            SELECT
                o.ocr_id, o.paper_id, o.answer_sha256, o.student_info, o.created_at,
                CASE WHEN e.eval_id IS NOT NULL THEN 1 ELSE 0 END AS has_evaluation
            FROM ocr_results o
            LEFT JOIN evaluations e ON e.ocr_id = o.ocr_id
            WHERE o.paper_id = ?
            ORDER BY o.created_at DESC
            """,
            (paper_id,),
        ) as cursor:
            rows = await cursor.fetchall()
            results = []
            for row in rows:
                info = StudentInfo.model_validate_json(row["student_info"])
                results.append(
                    OcrSummaryResponse(
                        ocr_id=row["ocr_id"],
                        paper_id=row["paper_id"],
                        answer_sha256=row["answer_sha256"],
                        student_name=info.student_name,
                        roll_number=info.roll_number,
                        has_evaluation=bool(row["has_evaluation"]),
                        created_at=row["created_at"],
                    )
                )
            return results


# ---------------------------------------------------------------------------
# Evaluation Repository — evaluations table
# ---------------------------------------------------------------------------

class EvaluationRepository:
    def __init__(self, db: aiosqlite.Connection):
        self.db = db

    async def find_by_id(self, eval_id: str) -> Optional[EvaluationResponse]:
        async with self.db.execute(
            "SELECT * FROM evaluations WHERE eval_id = ?", (eval_id,)
        ) as cursor:
            row = await cursor.fetchone()
            if not row:
                return None
            return self._row_to_response(row)

    async def find_by_id_via_ocr(self, ocr_id: str) -> Optional[EvaluationResponse]:
        async with self.db.execute(
            "SELECT * FROM evaluations WHERE ocr_id = ?", (ocr_id,)
        ) as cursor:
            row = await cursor.fetchone()
            if not row:
                return None
            return self._row_to_response(row, is_duplicate=True)

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
        ocr_id: str,
        paper_id: str,
        answer_sha256: str,
        report: EvaluationReport,
    ) -> None:
        await self.db.execute(
            """
            INSERT INTO evaluations
                (eval_id, ocr_id, paper_id, answer_sha256, student_info, evaluation, confirmed)
            VALUES (?, ?, ?, ?, ?, ?, 0)
            """,
            (
                eval_id,
                ocr_id,
                paper_id,
                answer_sha256,
                report.student_info.model_dump_json(),
                report.model_dump_json(),
            ),
        )
        await self.db.commit()

    async def confirm(self, eval_id: str, report: EvaluationReport) -> None:
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