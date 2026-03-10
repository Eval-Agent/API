from dotenv import load_dotenv
load_dotenv()  # Load .env before anything else reads os.getenv()

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager

from db.database import init_db
from routers import papers, evaluations


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    yield


app = FastAPI(
    title="Question Paper API",
    description="Upload, parse, and manage question papers and student evaluations with AI.",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(papers.router,      prefix="/api/v1/papers",      tags=["Question Papers"])
app.include_router(evaluations.router, prefix="/api/v1/evaluations",  tags=["Evaluations"])


@app.get("/health")
async def health_check():
    return {"status": "ok", "service": "Question Paper API"}