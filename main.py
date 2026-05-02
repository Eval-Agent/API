import os

os.environ["PROTOCOL_BUFFERS_PYTHON_IMPLEMENTATION"] = "python"
os.environ["TRANSFORMERS_NO_TF"] = "1"
os.environ["USE_TF"] = "0"
os.environ["USE_TORCH"] = "1"

from dotenv import load_dotenv

load_dotenv()

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager

from db.database import init_db
from routers import papers
from routers.submissions import (
    papers_router as submissions_papers_router,
    flat_router as submissions_flat_router,
)
from routers.evaluations import (
    submissions_router as evaluations_submissions_router,
    papers_router as evaluations_papers_router,
    flat_router as evaluations_flat_router,
)
from routers.history import papers_history_router, eval_history_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    yield


app = FastAPI(
    title="Question Paper API",
    description="Upload, parse, and manage question papers and student evaluations with AI.",
    version="2.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── /api/v1/papers  ────────────────────────────────────────────────────────
# Handles: POST /papers, GET /papers, GET /papers/{id}, DELETE /papers/{id}
#          POST /papers/{id}/rubric:generate, POST /papers/{id}:confirm
#          POST /papers/{id}/submissions, GET /papers/{id}/submissions
#          GET  /papers/{id}/evaluations
app.include_router(papers.router, prefix="/api/v1/papers")
app.include_router(submissions_papers_router, prefix="/api/v1/papers")
app.include_router(evaluations_papers_router, prefix="/api/v1/papers")
app.include_router(papers_history_router, prefix="/api/v1/papers")

# ── /api/v1/submissions  ───────────────────────────────────────────────────
# Handles: GET /submissions/{id}, POST /submissions/{id}:update-student-info
#          DELETE /submissions/{id}
#          POST /submissions/{id}/evaluation:generate
#          POST /submissions/{id}/evaluation:confirm
app.include_router(submissions_flat_router, prefix="/api/v1/submissions")
app.include_router(evaluations_submissions_router, prefix="/api/v1/submissions")
app.include_router(eval_history_router, prefix="/api/v1/submissions")

# ── /api/v1/evaluations  ──────────────────────────────────────────────────
# Handles: GET /evaluations/{eval_id}, DELETE /evaluations/{eval_id}
app.include_router(evaluations_flat_router, prefix="/api/v1/evaluations")


@app.get("/health", tags=["Health"])
async def health_check():
    return {"status": "ok", "service": "Question Paper API", "version": "2.0.0"}
