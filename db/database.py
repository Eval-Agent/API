import aiosqlite
from pathlib import Path

DB_PATH = Path("./data/papers.db")


async def init_db():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS papers (
                paper_id     TEXT PRIMARY KEY,
                sha256_hash  TEXT UNIQUE NOT NULL,
                parsed_paper TEXT NOT NULL,
                rubric       TEXT NOT NULL,
                confirmed    INTEGER NOT NULL DEFAULT 0,
                created_at   TEXT NOT NULL DEFAULT (datetime('now'))
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS ocr_results (
                ocr_id            TEXT PRIMARY KEY,
                paper_id          TEXT NOT NULL REFERENCES papers(paper_id),
                answer_sha256     TEXT UNIQUE NOT NULL,
                student_info      TEXT NOT NULL,
                extracted_answers TEXT NOT NULL,
                created_at        TEXT NOT NULL DEFAULT (datetime('now'))
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS evaluations (
                eval_id       TEXT PRIMARY KEY,
                ocr_id        TEXT REFERENCES ocr_results(ocr_id),
                paper_id      TEXT NOT NULL REFERENCES papers(paper_id),
                answer_sha256 TEXT NOT NULL,
                student_info  TEXT NOT NULL,
                evaluation    TEXT NOT NULL,
                confirmed     INTEGER NOT NULL DEFAULT 0,
                created_at    TEXT NOT NULL DEFAULT (datetime('now'))
            )
        """)

        # ── Migration: add ocr_id column to existing evaluations table ───────
        existing_cols = [
            row[1]
            async for row in await db.execute("PRAGMA table_info(evaluations)")
        ]
        if "ocr_id" not in existing_cols:
            await db.execute(
                "ALTER TABLE evaluations ADD COLUMN ocr_id TEXT REFERENCES ocr_results(ocr_id)"
            )

        await db.commit()


async def get_db():
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        yield db