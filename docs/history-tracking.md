# History Tracking

The history tracking feature creates an audit trail of all changes made to
question papers and evaluations. It captures snapshots of the complete state
before each confirm or edit operation, allowing you to review, compare, and
restore previous versions at any time.

This document covers how the history feature works, the database schema, API
endpoints, and practical usage examples.

---

## Overview

The history tracking system provides version control for two critical
resources:

- **Rubric history** — tracks changes to the marking rubric and parsed paper
  questions. Each snapshot captures the complete rubric and parsed paper state
  immediately before a confirm or edit operation.
- **Evaluation history** — tracks changes to student evaluation reports. Each
  snapshot captures the complete evaluation report immediately before a
  confirm operation.

The system stores these snapshots in dedicated history tables, making it
possible to view the complete evolution of any paper or evaluation.

---

## How It Works

The history tracking follows a two-step process that ensures every change
is captured before it becomes permanent.

### Step 1: Create Snapshot Before Confirm

Before any confirm or edit operation proceeds, the system automatically
creates a snapshot of the current state. This snapshot includes:

- For rubric changes: the complete rubric JSON and parsed paper JSON
- For evaluation changes: the complete evaluation report JSON

The snapshot is stored in the appropriate history table with a timestamp
and the action type (`confirm`).

### Step 2: Apply the Changes

After the snapshot is safely stored, the system proceeds with the actual
update operation. This means every modification has a corresponding
"before" snapshot that you can retrieve later.

This approach provides a complete audit trail without preventing or slowing
down the confirm process. You can always look back at what the data looked
like before any change.

---

## Database Schema

The history feature uses two new database tables to store audit snapshots.

### rubric_history table

Stores snapshots of rubric and parsed paper state before confirm or edit
operations.

| Column | Type | Description |
|--------|------|-------------|
| `paper_id` | TEXT NOT NULL | Foreign key to the paper (part of composite primary key) |
| `rubric_json` | TEXT NOT NULL | Serialized rubric JSON at snapshot time |
| `parsed_paper_json` | TEXT NOT NULL | Serialized parsed paper JSON at snapshot time |
| `changed_at` | TEXT NOT NULL | ISO-8601 timestamp when snapshot was created (part of composite primary key) |
| `action` | TEXT NOT NULL | Type of operation that triggered the snapshot (`confirm`) |

Primary key: `(paper_id, changed_at)` — composite key ensures uniqueness per paper.

The `paper_id` column has a foreign key constraint with cascade delete,
so deleting a paper also removes all its rubric history records.

### evaluation_history table

Stores snapshots of evaluation reports before confirm or edit operations.

| Column | Type | Description |
|--------|------|-------------|
| `eval_id` | TEXT NOT NULL | Foreign key to the evaluation (part of composite primary key) |
| `evaluation_json` | TEXT NOT NULL | Serialized evaluation report JSON at snapshot time |
| `changed_at` | TEXT NOT NULL | ISO-8601 timestamp when snapshot was created (part of composite primary key) |
| `action` | TEXT NOT NULL | Type of operation that triggered the snapshot (`confirm`) |

Primary key: `(eval_id, changed_at)` — composite key ensures uniqueness per evaluation.

The `eval_id` column has a foreign key constraint with cascade delete,
so deleting an evaluation also removes all its history records.

---

## API Endpoints

The history tracking feature exposes two GET endpoints for retrieving historical
snapshots.  

### GET /api/v1/papers/{paper_id}/history

Returns all rubric history snapshots for a specific paper, ordered from most
recent to oldest.

**Path parameter:**

| Parameter | Type | Description |
|-----------|------|-------------|
| `paper_id` | string | The unique identifier of the paper |

**Response:**

```json
{
  "paper_id": "uuid-string",
  "history": [
    {
      "paper_id": "uuid-string",
      "rubric_json": { ... },
      "parsed_paper_json": { ... },
      "changed_at": "2026-05-02T10:30:00",
      "action": "confirm"
    },
    {
      "paper_id": "uuid-string",
      "rubric_json": { ... },
      "parsed_paper_json": { ... },
      "changed_at": "2026-05-01T14:20:00",
      "action": "confirm"
    }
  ]
}
```

**Response fields:**

| Field | Type | Description |
|-------|------|-------------|
| `paper_id` | string | The paper identifier (echoed from request) |
| `history` | array | Array of historical snapshots, ordered newest first |
| `history[].paper_id` | string | Paper identifier (echoed from request) |
| `history[].rubric_json` | object | Complete rubric state at snapshot time |
| `history[].parsed_paper_json` | object | Complete parsed paper state at snapshot time |
| `history[].changed_at` | string | ISO-8601 timestamp of the snapshot |
| `history[].action` | string | Operation type that triggered the snapshot |

**Error responses:**

- `404 Not Found` — Paper not found

### GET /api/v1/submissions/{submission_id}/evaluation/history

Returns all evaluation history snapshots for a submission, ordered from most
recent to oldest.

**Path parameter:**

| Parameter | Type | Description |
|-----------|------|-------------|
| `submission_id` | string | The unique identifier of the submission (OCR id) |

**Response:**

```json
{
  "eval_id": "uuid-string",
  "history": [
    {
      "eval_id": "uuid-string",
      "evaluation_json": { ... },
      "changed_at": "2026-05-02T11:00:00",
      "action": "confirm"
    }
  ]
}
```

**Response fields:**

| Field | Type | Description |
|-------|------|-------------|
| `eval_id` | string | The evaluation identifier |
| `history` | array | Array of historical snapshots, ordered newest first |
| `history[].eval_id` | string | Evaluation identifier (echoed from request) |
| `history[].evaluation_json` | object | Complete evaluation report at snapshot time |
| `history[].changed_at` | string | ISO-8601 timestamp of the snapshot |
| `history[].action` | string | Operation type that triggered the snapshot |

**Error responses:**

- `404 Not Found` — No evaluation found for this submission

---

## Usage Examples

These examples show how to use the history endpoints with curl.

### Retrieve rubric history for a paper

```bash
curl -X GET "http://localhost:8000/api/v1/papers/550e8400-e29b-41d4-a716-446655440000/history" \
  -H "Content-Type: application/json"
```

Expected response:

```json
{
  "paper_id": "550e8400-e29b-41d4-a716-446655440000",
  "history": [
    {
      "paper_id": "550e8400-e29b-41d4-a716-446655440000",
      "rubric_json": {
        "total_questions": 5,
        "questions": [...]
      },
      "parsed_paper_json": {
        "metadata": {...},
        "questions": [...]
      },
      "changed_at": "2026-05-02T10:30:00",
      "action": "confirm"
    }
  ]
}
```

### Retrieve evaluation history for a submission

```bash
curl -X GET "http://localhost:8000/api/v1/submissions/660e8400-e29b-41d4-a716-446655440001/evaluation/history" \
  -H "Content-Type: application/json"
```

Expected response:

```json
{
  "eval_id": "770e8400-e29b-41d4-a716-446655440002",
  "history": [
    {
      "eval_id": "770e8400-e29b-41d4-a716-446655440002",
      "evaluation_json": {
        "total_score": 75,
        "full_marks": 100,
        "answers": [...]
      },
      "changed_at": "2026-05-02T11:00:00",
      "action": "confirm"
    }
  ]
}
```

---

## Integration Details

The history snapshots are created automatically by the service layer when
confirm or edit operations are performed. You do not need to call any
additional endpoints to create snapshots.

### Automatic snapshot creation

Snapshots are created automatically when you call confirm operations. The
history **GET endpoints only retrieve** snapshots — they do not create them.

The following operations trigger automatic snapshot creation:

- `POST /api/v1/papers/{paper_id}:confirm` — Creates a rubric history
  snapshot before confirming the paper
- `POST /api/v1/submissions/{submission_id}/evaluation:confirm` — Creates
  an evaluation history snapshot before confirming the evaluation

### Snapshot contents

Each snapshot contains a complete copy of the data at the time it was saved.
This means you can restore any previous state by manually reconstructing
the JSON from the history record.

The snapshots include the full JSON payloads, not just the differences,
making them self-contained and easy to work with.

### Ordering

History records are returned in reverse chronological order (most recent
first), making it easy to see the latest changes without having to sort
through older records.

---

## Next steps

Now that you have implemented history tracking, consider these enhancements:

- Add a restore endpoint to revert to a previous snapshot
- Implement diff comparison between two history records
- Add visualization of the change history over time