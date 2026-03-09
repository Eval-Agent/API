import aiosqlite
import json
from pathlib import Path

DB_PATH = Path("./data/papers.db")


async def init_db():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS papers (
                paper_id    TEXT PRIMARY KEY,
                sha256_hash TEXT UNIQUE NOT NULL,
                parsed_paper TEXT NOT NULL,   -- JSON
                rubric       TEXT NOT NULL,   -- JSON
                confirmed    INTEGER NOT NULL DEFAULT 0,
                created_at   TEXT NOT NULL DEFAULT (datetime('now'))
            )
        """)
        await db.commit()


async def get_db():
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        yield db
