import aiosqlite
from pathlib import Path

DB_PATH = Path("./data/papers.db")


async def init_db():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("PRAGMA foreign_keys = ON")

        # ── Create tables (fresh installs) ────────────────────────────────────
        await db.execute("""
            CREATE TABLE IF NOT EXISTS papers (
                paper_id     TEXT PRIMARY KEY,
                user_id      TEXT NOT NULL,
                sha256_hash  TEXT UNIQUE NOT NULL,
                parsed_paper TEXT NOT NULL,
                rubric       TEXT,
                confirmed    INTEGER NOT NULL DEFAULT 0,
                created_at   TEXT NOT NULL DEFAULT (datetime('now'))
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS ocr_results (
                ocr_id            TEXT PRIMARY KEY,
                paper_id          TEXT NOT NULL REFERENCES papers(paper_id) ON DELETE CASCADE,
                answer_sha256     TEXT UNIQUE NOT NULL,
                student_info      TEXT NOT NULL,
                extracted_answers TEXT NOT NULL,
                created_at        TEXT NOT NULL DEFAULT (datetime('now'))
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS evaluations (
                eval_id       TEXT PRIMARY KEY,
                ocr_id        TEXT REFERENCES ocr_results(ocr_id) ON DELETE CASCADE,
                paper_id      TEXT NOT NULL REFERENCES papers(paper_id) ON DELETE CASCADE,
                answer_sha256 TEXT NOT NULL,
                student_info  TEXT NOT NULL,
                evaluation    TEXT NOT NULL,
                confirmed     INTEGER NOT NULL DEFAULT 0,
                created_at    TEXT NOT NULL DEFAULT (datetime('now'))
            )
        """)

        await db.execute("""
            CREATE TABLE IF NOT EXISTS rubric_history (
                paper_id           TEXT    NOT NULL REFERENCES papers(paper_id) ON DELETE CASCADE,
                rubric_json        TEXT    NOT NULL,
                parsed_paper_json  TEXT    NOT NULL,
                changed_at         TEXT    NOT NULL DEFAULT (datetime('now')),
                action             TEXT    NOT NULL CHECK(action IN ('confirm', 'edit')),
                PRIMARY KEY (paper_id, changed_at)
            )
        """)

        await db.execute("""
            CREATE TABLE IF NOT EXISTS evaluation_history (
                eval_id          TEXT    NOT NULL REFERENCES evaluations(eval_id) ON DELETE CASCADE,
                evaluation_json  TEXT    NOT NULL,
                changed_at       TEXT    NOT NULL DEFAULT (datetime('now')),
                action           TEXT    NOT NULL CHECK(action IN ('confirm', 'edit')),
                PRIMARY KEY (eval_id, changed_at)
            )
        """)

        # ── Migration: add user_id column ──────────────────────────────────────
        papers_cols = {
            row[1]: row[3]
            async for row in await db.execute("PRAGMA table_info(papers)")
        }
        if "user_id" not in papers_cols:
            await db.execute("ALTER TABLE papers ADD COLUMN user_id TEXT NOT NULL DEFAULT 'default'")

        # ── Migration: make rubric nullable (drop NOT NULL) ───────────────────
        papers_cols = {
            row[1]: row[3]
            async for row in await db.execute("PRAGMA table_info(papers)")
        }
        if papers_cols.get("rubric") == 1:   # 1 = NOT NULL present
            await db.execute("ALTER TABLE papers RENAME TO _papers_old")
            await db.execute("""
                CREATE TABLE papers (
                    paper_id     TEXT PRIMARY KEY,
                    sha256_hash  TEXT UNIQUE NOT NULL,
                    parsed_paper TEXT NOT NULL,
                    rubric       TEXT,
                    confirmed    INTEGER NOT NULL DEFAULT 0,
                    created_at   TEXT NOT NULL DEFAULT (datetime('now'))
                )
            """)
            await db.execute("""
                INSERT INTO papers (paper_id, sha256_hash, parsed_paper, rubric, confirmed, created_at)
                SELECT               paper_id, sha256_hash, parsed_paper, rubric, confirmed, created_at
                FROM _papers_old
            """)
            await db.execute("DROP TABLE _papers_old")

        # ── Migration: rebuild ocr_results with ON DELETE CASCADE ─────────────
        ocr_ddl_rows = await (
            await db.execute(
                "SELECT sql FROM sqlite_master WHERE type='table' AND name='ocr_results'"
            )
        ).fetchall()
        if ocr_ddl_rows and "ON DELETE CASCADE" not in (ocr_ddl_rows[0][0] or ""):
            await db.execute("ALTER TABLE ocr_results RENAME TO _ocr_results_old")
            await db.execute("""
                CREATE TABLE ocr_results (
                    ocr_id            TEXT PRIMARY KEY,
                    paper_id          TEXT NOT NULL REFERENCES papers(paper_id) ON DELETE CASCADE,
                    answer_sha256     TEXT UNIQUE NOT NULL,
                    student_info      TEXT NOT NULL,
                    extracted_answers TEXT NOT NULL,
                    created_at        TEXT NOT NULL DEFAULT (datetime('now'))
                )
            """)
            await db.execute("""
                INSERT INTO ocr_results
                SELECT ocr_id, paper_id, answer_sha256, student_info, extracted_answers, created_at
                FROM _ocr_results_old
            """)
            await db.execute("DROP TABLE _ocr_results_old")

        # ── Migration: rebuild evaluations with ON DELETE CASCADE ─────────────
        eval_ddl_rows = await (
            await db.execute(
                "SELECT sql FROM sqlite_master WHERE type='table' AND name='evaluations'"
            )
        ).fetchall()
        if eval_ddl_rows and "ON DELETE CASCADE" not in (eval_ddl_rows[0][0] or ""):
            await db.execute("ALTER TABLE evaluations RENAME TO _evaluations_old")
            await db.execute("""
                CREATE TABLE evaluations (
                    eval_id       TEXT PRIMARY KEY,
                    ocr_id        TEXT REFERENCES ocr_results(ocr_id) ON DELETE CASCADE,
                    paper_id      TEXT NOT NULL REFERENCES papers(paper_id) ON DELETE CASCADE,
                    answer_sha256 TEXT NOT NULL,
                    student_info  TEXT NOT NULL,
                    evaluation    TEXT NOT NULL,
                    confirmed     INTEGER NOT NULL DEFAULT 0,
                    created_at    TEXT NOT NULL DEFAULT (datetime('now'))
                )
            """)
            old_eval_cols = [
                row[1]
                async for row in await db.execute("PRAGMA table_info(_evaluations_old)")
            ]
            if "ocr_id" in old_eval_cols:
                await db.execute("""
                    INSERT INTO evaluations
                    SELECT eval_id, ocr_id, paper_id, answer_sha256, student_info,
                           evaluation, confirmed, created_at
                    FROM _evaluations_old
                """)
            else:
                await db.execute("""
                    INSERT INTO evaluations
                        (eval_id, ocr_id, paper_id, answer_sha256, student_info,
                         evaluation, confirmed, created_at)
                    SELECT eval_id, NULL, paper_id, answer_sha256, student_info,
                           evaluation, confirmed, created_at
                    FROM _evaluations_old
                """)
            await db.execute("DROP TABLE _evaluations_old")

        # ── Migration: drop history_id from history tables if exists ────────────
        # Check and migrate rubric_history
        rubric_cols = {
            row[1]: row[3]
            async for row in await db.execute("PRAGMA table_info(rubric_history)")
        }
        if "history_id" in rubric_cols:
            await db.execute("ALTER TABLE rubric_history RENAME TO _rubric_history_old")
            await db.execute("""
                CREATE TABLE rubric_history (
                    paper_id           TEXT    NOT NULL REFERENCES papers(paper_id) ON DELETE CASCADE,
                    rubric_json        TEXT    NOT NULL,
                    parsed_paper_json  TEXT    NOT NULL,
                    changed_at         TEXT    NOT NULL DEFAULT (datetime('now')),
                    action             TEXT    NOT NULL CHECK(action IN ('confirm', 'edit')),
                    PRIMARY KEY (paper_id, changed_at)
                )
            """)
            await db.execute("""
                INSERT INTO rubric_history (paper_id, rubric_json, parsed_paper_json, changed_at, action)
                SELECT paper_id, rubric_json, parsed_paper_json, changed_at, action
                FROM _rubric_history_old
            """)
            await db.execute("DROP TABLE _rubric_history_old")

        # Check and migrate evaluation_history
        eval_hist_cols = {
            row[1]: row[3]
            async for row in await db.execute("PRAGMA table_info(evaluation_history)")
        }
        if "history_id" in eval_hist_cols:
            await db.execute("ALTER TABLE evaluation_history RENAME TO _evaluation_history_old")
            await db.execute("""
                CREATE TABLE evaluation_history (
                    eval_id          TEXT    NOT NULL REFERENCES evaluations(eval_id) ON DELETE CASCADE,
                    evaluation_json  TEXT    NOT NULL,
                    changed_at       TEXT    NOT NULL DEFAULT (datetime('now')),
                    action           TEXT    NOT NULL CHECK(action IN ('confirm', 'edit')),
                    PRIMARY KEY (eval_id, changed_at)
                )
            """)
            await db.execute("""
                INSERT INTO evaluation_history (eval_id, evaluation_json, changed_at, action)
                SELECT eval_id, evaluation_json, changed_at, action
                FROM _evaluation_history_old
            """)
            await db.execute("DROP TABLE _evaluation_history_old")

        await db.commit()


async def get_db():
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        await db.execute("PRAGMA foreign_keys = ON")   # must be set per connection
        yield db