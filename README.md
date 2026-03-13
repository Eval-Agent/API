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


Endpoint old to new maping with explaination:
# Endpoint Migration Guide — v1 → v2

> **Key renames**
> - `ocr_id` → `submission_id` in all API responses (DB column unchanged)
> - "OCR result" concept renamed to **Submission** across the entire API surface
> - Verb-in-path actions (`/upload`, `/confirm`, `/evaluate`) replaced with
>   resource-oriented URLs and custom action suffixes (`:generate`, `:confirm`)

---

## Papers

| Method | Old endpoint (v1) | Method | New endpoint (v2) | Description |
|--------|-------------------|--------|-------------------|-------------|
| `POST` | `/api/v1/papers/upload` | `POST` | `/api/v1/papers` | Upload a question paper PDF. Runs OCR to extract questions and metadata. Returns `paper_id` and `parsed_paper`. No rubric is generated yet. |
| `POST` | `/api/v1/papers/generate-rubric` | `POST` | `/api/v1/papers/{paper_id}/rubric:generate` | Generate a marking rubric for an OCR'd paper. Accepts a `strictness` level (`easy` / `medium` / `hard` / `extreme`). Can be called multiple times before confirming to regenerate with a different strictness. `paper_id` moves from the request body to the URL path. |
| `POST` | `/api/v1/papers/confirm` | `POST` | `/api/v1/papers/{paper_id}:confirm` | Confirm the reviewed (and optionally edited) paper and rubric. Marks the paper as confirmed and locks it for evaluation. `paper_id` moves from the request body to the URL path. |
| `GET` | `/api/v1/papers/` | `GET` | `/api/v1/papers` | List all uploaded papers with summary info (`confirmed`, `has_rubric`). Trailing slash removed. |
| `GET` | `/api/v1/papers/{paper_id}` | `GET` | `/api/v1/papers/{paper_id}` | Get full detail of a specific paper including parsed questions and rubric. **Unchanged.** |
| `DELETE` | `/api/v1/papers/{paper_id}` | `DELETE` | `/api/v1/papers/{paper_id}` | Permanently delete a paper, its rubric, all linked submissions, and all evaluations. **Unchanged.** |

---

## Submissions *(formerly "OCR results")*

| Method | Old endpoint (v1) | Method | New endpoint (v2) | Description |
|--------|-------------------|--------|-------------------|-------------|
| `POST` | `/api/v1/evaluations/ocr` | `POST` | `/api/v1/papers/{paper_id}/submissions` | Upload a student answer PDF for a confirmed paper. Runs OCR to extract student name, roll number, and all answers. `paper_id` moves from a form field to the URL path. Returns `submission_id` (previously `ocr_id`). |
| `GET` | `/api/v1/evaluations/ocr/{paper_id}` | `GET` | `/api/v1/papers/{paper_id}/submissions` | List all submitted answer sheets for a given paper. Each row includes `has_evaluation` flag. Same URL as `POST` — standard resource collection pattern. |
| `GET` | `/api/v1/evaluations/ocr/detail/{ocr_id}` | `GET` | `/api/v1/submissions/{submission_id}` | Get the full OCR record for a single submission including student info and all extracted answers. The `/detail/` prefix and `/evaluations/ocr/` nesting are removed. |
| `PATCH` | `/api/v1/evaluations/ocr/detail/{ocr_id}/student-info` | `POST` | `/api/v1/submissions/{submission_id}:update-student-info` | Correct the student name and/or roll number that OCR extracted. Method changed from `PATCH` to `POST` with an action suffix for consistency with other action endpoints. |
| `DELETE` | `/api/v1/evaluations/ocr/{ocr_id}` | `DELETE` | `/api/v1/submissions/{submission_id}` | Permanently delete a submission. Only allowed if no evaluation has been run against it yet (returns `409` otherwise). |

---

## Evaluations

| Method | Old endpoint (v1) | Method | New endpoint (v2) | Description |
|--------|-------------------|--------|-------------------|-------------|
| `POST` | `/api/v1/evaluations/evaluate` | `POST` | `/api/v1/submissions/{submission_id}/evaluation:generate` | Run AI evaluation on the extracted answers from the given submission, scoring each answer against the paper rubric. Body changes from `{ ocr_id }` to empty `{}` — the submission is identified by the URL path. Idempotent: returns the existing evaluation if already evaluated. |
| `POST` | `/api/v1/evaluations/confirm` | `POST` | `/api/v1/submissions/{submission_id}/evaluation:confirm` | Confirm the reviewed (and optionally corrected) evaluation. `eval_id` moves from the request body to being resolved via the URL `submission_id`. The examiner can adjust marks, student info, and feedback before confirming. |
| `GET` | `/api/v1/evaluations/{paper_id}` | `GET` | `/api/v1/papers/{paper_id}/evaluations` | List all student evaluations for a given paper (class results view). Moved under `/papers/{paper_id}/` to make the parent-child relationship explicit. Each row now includes `submission_id`. |
| `GET` | `/api/v1/evaluations/{paper_id}/{eval_id}` | `GET` | `/api/v1/evaluations/{eval_id}` | Get full detail of a single evaluation. `paper_id` removed from the path — `eval_id` alone is sufficient to identify the record. Response now includes `submission_id`. |
| `DELETE` | `/api/v1/evaluations/{eval_id}` | `DELETE` | `/api/v1/evaluations/{eval_id}` | Permanently delete an evaluation. After deletion, the linked submission can be deleted. **Unchanged.** |

---

## Response field changes

| Field | v1 name | v2 name | Affected responses |
|-------|---------|---------|-------------------|
| Submission identifier | `ocr_id` | `submission_id` | `SubmissionResponse`, `SubmissionSummaryResponse`, `EvaluationResponse`, `EvaluationSummaryResponse` |
| Evaluation summary — max marks | `total_max_marks` | `full_marks` | `EvaluationSummary` |
| Evaluation list row | *(no submission ref)* | `submission_id` | `EvaluationSummaryResponse` |
| Confirm request identifier | `eval_id` in body | *(in URL path)* | `EvaluationConfirmRequest` — `eval_id` field removed from body |

---

## What did not change

- All `paper_id` values and the papers DB table are identical.
- The `eval_id` values and evaluations DB table are identical.
- The `ocr_results` DB table column is still named `ocr_id` internally — only the API surface uses `submission_id`.
- Cascade-delete behaviour is unchanged: deleting a paper removes all its submissions and evaluations.
- The `/health` endpoint is unchanged.
- Error status codes (`400`, `404`, `409`, `502`) are unchanged for all equivalent operations.