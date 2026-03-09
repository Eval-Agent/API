# Question Paper API

A professional FastAPI service that accepts question paper PDFs, runs AI-powered OCR and rubric generation, supports duplicate detection, and saves confirmed papers to a local SQLite database.

---

## Architecture

```
Client / UI
   │
   │  POST /api/v1/papers/upload  (PDF)
   ▼
API Server
   ├── 1. Read PDF bytes
   ├── 2. Compute SHA-256 hash
   ├── 3. Check DB for duplicate hash
   │
   ├── Duplicate → return existing paper immediately
   │
   └── New →
         ├── OCR Service  (Gemini Flash Lite — fast + cheap)
         │       └── Extracts metadata + questions as structured JSON
         │
         └── Rubric Service  (Gemini Flash — smarter reasoning)
                 └── Generates per-question rubrics with concepts & partial marking rules
                 │
                 └── Save draft to DB (unconfirmed)
                         │
                         └── Return to UI for review
                                 │
                                 │  POST /api/v1/papers/confirm
                                 ▼
                         Save final (confirmed) paper + rubric to DB
```

---

## Project Structure

```
question_paper_api/
├── main.py                        # FastAPI app + lifespan
├── requirements.txt
├── .env.example
│
├── models/
│   └── schemas.py                 # All Pydantic models
│
├── db/
│   ├── database.py                # SQLite init & connection
│   └── repository.py             # All DB queries
│
├── services/
│   ├── ocr_service.py            # PDF → structured questions (Gemini)
│   ├── rubric_service.py         # Questions → rubric (Gemini)
│   └── paper_processor.py        # Orchestrates OCR + rubric pipeline
│
├── routers/
│   └── papers.py                 # All /papers endpoints
│
└── instructions/                 # Optional system prompt overrides
    ├── ocr-q_system_prompt.txt
    └── rubric_system_prompt.txt
```

---

## Setup

### 1. Install dependencies
```bash
pip install -r requirements.txt
```

### 2. Configure environment
```bash
cp .env.example .env
# Edit .env and add your GEMINI_API_KEY
```

### 3. Run the server
```bash
uvicorn main:app --reload --port 8000
```

### 4. Open interactive docs
```
http://localhost:8000/docs
```

---

## API Endpoints

### `POST /api/v1/papers/upload`
Upload a question paper PDF.

**Request:** `multipart/form-data` with field `file` (PDF)

**Response:**
```json
{
  "paper_id": "uuid",
  "sha256_hash": "...",
  "is_duplicate": false,
  "parsed_paper": { "metadata": {...}, "questions": [...] },
  "rubric": { "total_questions": 5, "questions": [...] },
  "message": "Paper processed successfully. Please review and confirm."
}
```

---

### `POST /api/v1/papers/confirm`
After the user reviews/edits the AI output, confirm and save permanently.

**Request body:**
```json
{
  "paper_id": "uuid",
  "parsed_paper": { ... },
  "rubric": { ... }
}
```

---

### `GET /api/v1/papers/`
List all uploaded papers (summary view).

---

### `GET /api/v1/papers/{paper_id}`
Get full detail of a specific paper including parsed questions and rubric.

---

## Custom System Prompts

Place your own prompt files in the `instructions/` directory:

| File | Purpose |
|------|---------|
| `ocr-q_system_prompt.txt` | Controls how the LLM extracts questions from the PDF |
| `rubric_system_prompt.txt` | Controls how the LLM generates rubrics |

If a file is missing, sensible defaults are used automatically.

---

## Models

| Model | Default | Used for |
|-------|---------|---------|
| `OCR_MODEL` | `gemini-2.0-flash-lite` | Fast, cheap PDF parsing |
| `RUBRIC_MODEL` | `gemini-2.0-flash` | Smarter rubric reasoning |

Override via `.env` or environment variables.
