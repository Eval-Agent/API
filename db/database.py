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
            CREATE TABLE IF NOT EXISTS evaluations (
                eval_id       TEXT PRIMARY KEY,
                paper_id      TEXT NOT NULL REFERENCES papers(paper_id),
                answer_sha256 TEXT NOT NULL,
                student_info  TEXT NOT NULL,
                evaluation    TEXT NOT NULL,
                confirmed     INTEGER NOT NULL DEFAULT 0,
                created_at    TEXT NOT NULL DEFAULT (datetime('now'))
            )
        """)
        await db.commit()


async def get_db():
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        yield db