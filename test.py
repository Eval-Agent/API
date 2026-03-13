#!/usr/bin/env python3
"""
Question Paper API — End-to-End Test Script
============================================
Tests every endpoint in order, passing IDs between steps automatically.

Usage:
    python test_api.py                          # default: localhost:8000
    python test_api.py --base http://localhost:8000
    python test_api.py --base https://abc123.ngrok.io
    python test_api.py --paper sample_paper.pdf --answer sample_answer.pdf

    # Skip slow AI steps (uses stored IDs from a previous run):
    python test_api.py --paper-id <uuid> --submission-id <uuid>

Dependencies (stdlib only — no extra installs needed):
    Python 3.8+
"""

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path
from typing import Any, Optional

# ── colour helpers ────────────────────────────────────────────────────────────

RESET  = "\033[0m"
BOLD   = "\033[1m"
GREEN  = "\033[92m"
RED    = "\033[91m"
YELLOW = "\033[93m"
CYAN   = "\033[96m"
DIM    = "\033[2m"


def _c(color: str, text: str) -> str:
    return f"{color}{text}{RESET}"


def section(title: str) -> None:
    print(f"\n{BOLD}{CYAN}{'─' * 60}{RESET}")
    print(f"{BOLD}{CYAN}  {title}{RESET}")
    print(f"{BOLD}{CYAN}{'─' * 60}{RESET}")


def ok(label: str, detail: str = "") -> None:
    suffix = f"  {DIM}{detail}{RESET}" if detail else ""
    print(f"  {_c(GREEN, '✓')} {label}{suffix}")


def fail(label: str, detail: str = "") -> None:
    suffix = f"\n      {_c(RED, detail)}" if detail else ""
    print(f"  {_c(RED, '✗')} {label}{suffix}")


def info(label: str, value: Any = "") -> None:
    v = f"  →  {_c(YELLOW, str(value))}" if value != "" else ""
    print(f"  {DIM}•{RESET} {label}{v}")


def skip(label: str, reason: str = "") -> None:
    suffix = f"  {DIM}({reason}){RESET}" if reason else ""
    print(f"  {_c(YELLOW, '○')} SKIP  {label}{suffix}")


# ── HTTP helpers ──────────────────────────────────────────────────────────────

class APIError(Exception):
    def __init__(self, status: int, body: str):
        self.status = status
        self.body   = body
        super().__init__(f"HTTP {status}: {body}")


def _request(
    method: str,
    url: str,
    *,
    json_body: Optional[dict] = None,
    multipart: Optional[dict] = None,   # {"field": (filename, bytes, content_type)} or {"field": "value"}
    expected: int = 200,
    label: str = "",
    allow_status: tuple = (),
) -> dict:
    """
    Tiny HTTP client using only stdlib.
    Supports application/json and multipart/form-data bodies.
    """
    headers: dict = {}
    data: Optional[bytes] = None

    if json_body is not None:
        data    = json.dumps(json_body).encode()
        headers["Content-Type"] = "application/json"

    elif multipart is not None:
        boundary = uuid.uuid4().hex
        parts = []
        for key, value in multipart.items():
            if isinstance(value, tuple):
                filename, file_bytes, ct = value
                parts.append(
                    f'--{boundary}\r\n'
                    f'Content-Disposition: form-data; name="{key}"; filename="{filename}"\r\n'
                    f'Content-Type: {ct}\r\n\r\n'.encode()
                    + file_bytes
                    + b'\r\n'
                )
            else:
                parts.append(
                    f'--{boundary}\r\n'
                    f'Content-Disposition: form-data; name="{key}"\r\n\r\n'
                    f'{value}\r\n'.encode()
                )
        parts.append(f'--{boundary}--\r\n'.encode())
        data    = b''.join(parts)
        headers["Content-Type"] = f"multipart/form-data; boundary={boundary}"

    req = urllib.request.Request(url, data=data, headers=headers, method=method)

    start = time.time()
    try:
        with urllib.request.urlopen(req, timeout=300) as resp:
            elapsed = time.time() - start
            body    = resp.read().decode()
            status  = resp.status
    except urllib.error.HTTPError as exc:
        elapsed = time.time() - start
        body    = exc.read().decode()
        status  = exc.code

    parsed: dict = {}
    try:
        parsed = json.loads(body)
    except Exception:
        parsed = {"_raw": body}

    tag = label or f"{method} {url}"
    elapsed_str = f"{elapsed:.1f}s"

    if status == expected or status in allow_status:
        ok(tag, f"HTTP {status}  {elapsed_str}")
    else:
        fail(tag, f"Expected {expected}, got {status}  {elapsed_str}")
        detail = parsed.get("detail", body[:300])
        info("detail", detail)
        raise APIError(status, str(detail))

    return parsed


# ── tiny minimal PDFs (valid PDF structure, no real content) ──────────────────

_MINIMAL_PDF = (
    b"%PDF-1.4\n"
    b"1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n"
    b"2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj\n"
    b"3 0 obj<</Type/Page/MediaBox[0 0 612 792]/Parent 2 0 R"
    b"/Resources<</Font<</F1 4 0 R>>>>>>endobj\n"
    b"4 0 obj<</Type/Font/Subtype/Type1/BaseFont/Helvetica>>endobj\n"
    b"xref\n0 5\n"
    b"0000000000 65535 f \n"
    b"0000000009 00000 n \n"
    b"0000000058 00000 n \n"
    b"0000000115 00000 n \n"
    b"0000000274 00000 n \n"
    b"trailer<</Size 5/Root 1 0 R>>\n"
    b"startxref\n356\n%%EOF\n"
)


def load_pdf(path: Optional[str], label: str) -> tuple:
    """Return (filename, bytes, content_type). Falls back to minimal stub."""
    if path and Path(path).exists():
        data = Path(path).read_bytes()
        info(f"Using real {label}", path)
        return (Path(path).name, data, "application/pdf")
    else:
        if path:
            info(f"{label} not found, using minimal stub PDF", path)
        else:
            info(f"No {label} provided, using minimal stub PDF")
        return ("stub.pdf", _MINIMAL_PDF, "application/pdf")


# ── test runner ───────────────────────────────────────────────────────────────

class Runner:
    def __init__(self, base: str, paper_pdf: Optional[str], answer_pdf: Optional[str],
                 seed_paper_id: Optional[str], seed_submission_id: Optional[str],
                 strictness: str = "medium"):
        self.base             = base.rstrip("/")
        self.paper_pdf        = paper_pdf
        self.answer_pdf       = answer_pdf
        self.seed_paper_id    = seed_paper_id
        self.seed_sub_id      = seed_submission_id
        self.strictness       = strictness

        # state passed between tests
        self.paper_id:        Optional[str] = None
        self.submission_id:   Optional[str] = None
        self.eval_id:         Optional[str] = None
        self.parsed_paper:    Optional[dict] = None
        self.rubric:          Optional[dict] = None

        self.passed = 0
        self.failed = 0
        self.skipped = 0

    def url(self, path: str) -> str:
        return f"{self.base}{path}"

    def _pass(self):  self.passed  += 1
    def _fail(self):  self.failed  += 1
    def _skip(self):  self.skipped += 1

    # ── convenience wrappers ─────────────────────────────────────────────────

    def GET(self, path, *, label="", expected=200, allow_status=()) -> dict:
        r = _request("GET", self.url(path), label=label or f"GET {path}",
                     expected=expected, allow_status=allow_status)
        self._pass(); return r

    def POST_json(self, path, body, *, label="", expected=200, allow_status=()) -> dict:
        r = _request("POST", self.url(path), json_body=body,
                     label=label or f"POST {path}", expected=expected, allow_status=allow_status)
        self._pass(); return r

    def POST_form(self, path, fields, *, label="", expected=200, allow_status=()) -> dict:
        r = _request("POST", self.url(path), multipart=fields,
                     label=label or f"POST {path} (multipart)", expected=expected, allow_status=allow_status)
        self._pass(); return r

    def DELETE(self, path, *, label="", expected=200, allow_status=()) -> dict:
        r = _request("DELETE", self.url(path), label=label or f"DELETE {path}",
                     expected=expected, allow_status=allow_status)
        self._pass(); return r

    def expect_error(self, method, path, body_or_fields, expected_status: int, label: str) -> None:
        fn = {"GET": self.GET, "DELETE": self.DELETE}.get(method)
        try:
            if method == "POST" and isinstance(body_or_fields, dict) and any(
                isinstance(v, tuple) for v in body_or_fields.values()
            ):
                _request("POST", self.url(path), multipart=body_or_fields,
                         expected=expected_status, label=label)
            elif method == "POST":
                _request("POST", self.url(path), json_body=body_or_fields,
                         expected=expected_status, label=label)
            else:
                _request(method, self.url(path), expected=expected_status, label=label)
            self._pass()
        except APIError as exc:
            if exc.status == expected_status:
                ok(label, f"correctly got HTTP {expected_status}")
                self._pass()
            else:
                fail(label, f"expected {expected_status}, got {exc.status}")
                self._fail()

    # ── individual test groups ───────────────────────────────────────────────

    def test_health(self):
        section("Health check")
        r = self.GET("/health", label="GET /health")
        info("status", r.get("status"))

    def test_papers_upload(self):
        section("Papers — Step 1: upload PDF (OCR)")

        if self.seed_paper_id:
            skip("POST /api/v1/papers", "using --paper-id from CLI")
            self.paper_id = self.seed_paper_id
            self._skip()
            return

        pdf_file = load_pdf(self.paper_pdf, "question paper PDF")
        r = self.POST_form(
            "/api/v1/papers",
            {"file": pdf_file},
            label="POST /api/v1/papers",
        )
        self.paper_id  = r["paper_id"]
        self.parsed_paper = r.get("parsed_paper")
        info("paper_id",     self.paper_id)
        info("is_duplicate", r.get("is_duplicate"))
        info("subject",      r.get("parsed_paper", {}).get("metadata", {}).get("subject_name", "—"))
        info("questions",    len(r.get("parsed_paper", {}).get("questions", [])))

    def test_papers_upload_duplicate(self):
        section("Papers — duplicate upload")
        if not self.paper_id or self.seed_paper_id:
            skip("duplicate upload test", "no real upload was done")
            self._skip(); return

        pdf_file = load_pdf(self.paper_pdf, "question paper PDF")
        r = self.POST_form(
            "/api/v1/papers",
            {"file": pdf_file},
            label="POST /api/v1/papers (duplicate)",
        )
        assert r.get("is_duplicate") is True, "Expected is_duplicate=true"
        info("is_duplicate", r.get("is_duplicate"))

    def test_papers_errors(self):
        section("Papers — upload error cases")

        # 400: empty body (no file field at all — send empty multipart)
        self.expect_error(
            "POST", "/api/v1/papers",
            {"file": ("empty.pdf", b"", "application/pdf")},
            400,
            "POST /api/v1/papers — empty file → 400",
        )

        # 400: not a PDF
        self.expect_error(
            "POST", "/api/v1/papers",
            {"file": ("doc.txt", b"hello world", "text/plain")},
            400,
            "POST /api/v1/papers — not a PDF → 400",
        )

    def test_generate_rubric(self):
        section("Papers — Step 2: generate rubric")
        if not self.paper_id:
            skip("rubric generation", "no paper_id"); self._skip(); return

        # Only test one strictness level — 4 sequential Gemini calls would time out.
        # Use --strictness easy/hard/extreme to test a specific level.
        r = self.POST_json(
            f"/api/v1/papers/{self.paper_id}/rubric:generate",
            {"strictness": self.strictness},
            label=f"POST /papers/{{id}}/rubric:generate  strictness={self.strictness}",
        )
        self.rubric = r.get("rubric")
        info("strictness",      r.get("strictness"))
        info("total_questions", r.get("rubric", {}).get("total_questions"))
        info("total_marks",     r.get("rubric", {}).get("total_marks"))

    def test_generate_rubric_errors(self):
        section("Papers — rubric error cases")
        # Non-existent paper
        fake_id = str(uuid.uuid4())
        self.expect_error(
            "POST", f"/api/v1/papers/{fake_id}/rubric:generate",
            {"strictness": "medium"},
            404,
            "POST /papers/{bad_id}/rubric:generate → 404",
        )

    def test_papers_list(self):
        section("Papers — list all")
        r = self.GET("/api/v1/papers", label="GET /api/v1/papers")
        info("total papers", len(r))
        if r:
            info("first subject", r[0].get("subject_name", "—"))
            info("confirmed",     r[0].get("confirmed"))
            info("has_rubric",    r[0].get("has_rubric"))

    def test_papers_get(self):
        section("Papers — get by ID")
        if not self.paper_id:
            skip("GET /papers/{id}", "no paper_id"); self._skip(); return

        r = self.GET(f"/api/v1/papers/{self.paper_id}", label="GET /api/v1/papers/{id}")
        info("confirmed", r.get("confirmed"))
        info("has_rubric", r.get("rubric") is not None)

        # 404 for unknown
        self.expect_error("GET", f"/api/v1/papers/{uuid.uuid4()}", None, 404,
                          "GET /papers/{bad_id} → 404")

    def test_confirm_paper(self):
        section("Papers — Step 3: confirm")
        if not self.paper_id:
            skip("POST /papers/{id}:confirm", "no paper_id"); self._skip(); return
        if not self.parsed_paper or not self.rubric:
            # Fetch from API to get current state
            detail = _request("GET", self.url(f"/api/v1/papers/{self.paper_id}"),
                               label="fetch paper for confirm", expected=200)
            self._pass()
            self.parsed_paper = detail.get("parsed_paper")
            # rubric from API has total_questions/total_marks; confirm only wants {questions:[...]}
            rubric_full = detail.get("rubric", {})
            self.rubric = {"questions": rubric_full.get("questions", [])}

        # Ensure rubric is storage shape (no computed fields)
        rubric_body = self.rubric
        if "total_questions" in rubric_body:
            rubric_body = {"questions": rubric_body["questions"]}

        r = self.POST_json(
            f"/api/v1/papers/{self.paper_id}:confirm",
            {
                "parsed_paper": self.parsed_paper,
                "rubric":       rubric_body,
            },  # paper_id is in the URL path, not the body
            label="POST /api/v1/papers/{id}:confirm",
        )
        info("message", r.get("message"))

    def test_confirm_paper_errors(self):
        section("Papers — confirm error cases")
        if not self.paper_id:
            skip("confirm error tests", "no paper_id"); self._skip(); return

        # 409: already confirmed
        rubric_body = self.rubric or {"questions": []}
        if "total_questions" in rubric_body:
            rubric_body = {"questions": rubric_body.get("questions", [])}
        self.expect_error(
            "POST", f"/api/v1/papers/{self.paper_id}:confirm",
            {"parsed_paper": self.parsed_paper or {"metadata": {}, "questions": []}, "rubric": rubric_body},
            409,
            "POST /papers/{id}:confirm (already confirmed) → 409",
        )

        # 404: unknown paper
        self.expect_error(
            "POST", f"/api/v1/papers/{uuid.uuid4()}:confirm",
            {"parsed_paper": {"metadata": {}, "questions": []}, "rubric": {"questions": []}},
            404,
            "POST /papers/{bad_id}:confirm → 404",
        )

    def test_submissions_create(self):
        section("Submissions — Step 1: upload answer PDF")
        if not self.paper_id:
            skip("POST /papers/{id}/submissions", "no paper_id"); self._skip(); return
        if self.seed_sub_id:
            skip("POST /papers/{id}/submissions", "using --submission-id from CLI")
            self.submission_id = self.seed_sub_id
            self._skip(); return

        pdf_file = load_pdf(self.answer_pdf, "student answer PDF")
        r = self.POST_form(
            f"/api/v1/papers/{self.paper_id}/submissions",
            {"file": pdf_file},
            label="POST /api/v1/papers/{id}/submissions",
        )
        self.submission_id = r["submission_id"]
        info("submission_id", self.submission_id)
        info("is_duplicate",  r.get("is_duplicate"))
        info("student_name",  r.get("student_info", {}).get("student_name", "—"))
        info("answers found", len(r.get("extracted_answers", [])))

    def test_submissions_duplicate(self):
        section("Submissions — duplicate upload")
        if not self.paper_id or self.seed_sub_id:
            skip("duplicate submission test", "no upload was done"); self._skip(); return

        pdf_file = load_pdf(self.answer_pdf, "student answer PDF")
        r = self.POST_form(
            f"/api/v1/papers/{self.paper_id}/submissions",
            {"file": pdf_file},
            label="POST /papers/{id}/submissions (duplicate)",
        )
        assert r.get("is_duplicate") is True, "Expected is_duplicate=true"
        info("is_duplicate", r.get("is_duplicate"))

    def test_submissions_errors(self):
        section("Submissions — error cases")
        if not self.paper_id:
            skip("submission error tests", "no paper_id"); self._skip(); return

        # 404: non-existent paper
        self.expect_error(
            "POST", f"/api/v1/papers/{uuid.uuid4()}/submissions",
            {"file": ("stub.pdf", _MINIMAL_PDF, "application/pdf")},
            404,
            "POST /papers/{bad_id}/submissions → 404",
        )

        # 400: empty file
        self.expect_error(
            "POST", f"/api/v1/papers/{self.paper_id}/submissions",
            {"file": ("empty.pdf", b"", "application/pdf")},
            400,
            "POST /papers/{id}/submissions — empty file → 400",
        )

    def test_submissions_list(self):
        section("Submissions — list by paper")
        if not self.paper_id:
            skip("GET /papers/{id}/submissions", "no paper_id"); self._skip(); return

        r = self.GET(
            f"/api/v1/papers/{self.paper_id}/submissions",
            label="GET /api/v1/papers/{id}/submissions",
        )
        info("total submissions", len(r))
        if r:
            info("first student",  r[0].get("student_name", "—"))
            info("has_evaluation", r[0].get("has_evaluation"))

    def test_submissions_get(self):
        section("Submissions — get by ID")
        if not self.submission_id:
            skip("GET /submissions/{id}", "no submission_id"); self._skip(); return

        r = self.GET(
            f"/api/v1/submissions/{self.submission_id}",
            label="GET /api/v1/submissions/{id}",
        )
        info("student_name", r.get("student_info", {}).get("student_name", "—"))
        info("answers",      len(r.get("extracted_answers", [])))

        # 404
        self.expect_error("GET", f"/api/v1/submissions/{uuid.uuid4()}", None, 404,
                          "GET /submissions/{bad_id} → 404")

    def test_submissions_update_student_info(self):
        section("Submissions — update student info")
        if not self.submission_id:
            skip("POST /submissions/{id}:update-student-info", "no submission_id"); self._skip(); return

        r = self.POST_json(
            f"/api/v1/submissions/{self.submission_id}:update-student-info",
            {"student_name": "Test Student (corrected)", "roll_number": "TEST2024001"},
            label="POST /submissions/{id}:update-student-info",
        )
        info("updated name",   r.get("student_info", {}).get("student_name"))
        info("updated roll_no", r.get("student_info", {}).get("roll_number"))

        # 404
        self.expect_error(
            "POST", f"/api/v1/submissions/{uuid.uuid4()}:update-student-info",
            {"student_name": "Nobody"},
            404,
            "POST /submissions/{bad_id}:update-student-info → 404",
        )

    def test_evaluation_generate(self):
        section("Evaluations — Step 1: generate")
        if not self.submission_id:
            skip("POST /submissions/{id}/evaluation:generate", "no submission_id"); self._skip(); return

        r = self.POST_json(
            f"/api/v1/submissions/{self.submission_id}/evaluation:generate",
            {},
            label="POST /submissions/{id}/evaluation:generate",
        )
        self.eval_id = r["eval_id"]
        info("eval_id",           self.eval_id)
        info("total_marks_awarded", r.get("evaluation_summary", {}).get("total_marks_awarded"))
        info("percentage",          r.get("evaluation_summary", {}).get("percentage"))
        info("confirmed",           r.get("confirmed"))
        info("questions evaluated", len(r.get("question_wise_evaluation", [])))

    def test_evaluation_generate_idempotent(self):
        section("Evaluations — generate is idempotent (already evaluated)")
        if not self.submission_id or not self.eval_id:
            skip("idempotent check", "no submission/eval"); self._skip(); return

        r = self.POST_json(
            f"/api/v1/submissions/{self.submission_id}/evaluation:generate",
            {},
            label="POST /submissions/{id}/evaluation:generate (2nd call)",
        )
        assert r["eval_id"] == self.eval_id, "Should return same eval_id"
        info("same eval_id returned", r["eval_id"])

    def test_evaluation_generate_errors(self):
        section("Evaluations — generate error cases")
        # 404: unknown submission
        self.expect_error(
            "POST", f"/api/v1/submissions/{uuid.uuid4()}/evaluation:generate",
            {},
            404,
            "POST /submissions/{bad_id}/evaluation:generate → 404",
        )

    def test_evaluations_list(self):
        section("Evaluations — list by paper")
        if not self.paper_id:
            skip("GET /papers/{id}/evaluations", "no paper_id"); self._skip(); return

        r = self.GET(
            f"/api/v1/papers/{self.paper_id}/evaluations",
            label="GET /api/v1/papers/{id}/evaluations",
        )
        info("total evaluations", len(r))
        if r:
            info("first student",   r[0].get("student_name", "—"))
            info("confirmed",       r[0].get("confirmed"))
            info("submission_id",   r[0].get("submission_id", "—"))

    def test_evaluations_get(self):
        section("Evaluations — get by ID")
        if not self.eval_id:
            skip("GET /evaluations/{id}", "no eval_id"); self._skip(); return

        r = self.GET(
            f"/api/v1/evaluations/{self.eval_id}",
            label="GET /api/v1/evaluations/{id}",
        )
        info("student",    r.get("student_info", {}).get("student_name", "—"))
        info("percentage", r.get("evaluation_summary", {}).get("percentage"))
        info("confirmed",  r.get("confirmed"))

        # 404
        self.expect_error("GET", f"/api/v1/evaluations/{uuid.uuid4()}", None, 404,
                          "GET /evaluations/{bad_id} → 404")

    def test_evaluation_confirm(self):
        section("Evaluations — Step 2: confirm")
        if not self.submission_id or not self.eval_id:
            skip("POST /submissions/{id}/evaluation:confirm", "no submission/eval"); self._skip(); return

        # Fetch current eval to build confirm body
        r_eval = _request("GET", self.url(f"/api/v1/evaluations/{self.eval_id}"),
                           label="fetch eval for confirm body", expected=200)
        self._pass()

        # Bump every marks_awarded by 0 (unchanged), just confirming as-is
        r = self.POST_json(
            f"/api/v1/submissions/{self.submission_id}/evaluation:confirm",
            {
                "student_info":             r_eval["student_info"],
                "extracted_answers":        r_eval.get("extracted_answers", []),
                "evaluation_summary":       r_eval["evaluation_summary"],
                "question_wise_evaluation": r_eval["question_wise_evaluation"],
            },
            label="POST /submissions/{id}/evaluation:confirm",
        )
        info("message", r.get("message"))

    def test_evaluation_confirm_errors(self):
        section("Evaluations — confirm error cases")
        if not self.submission_id or not self.eval_id:
            skip("confirm error tests", "no eval"); self._skip(); return

        # 409: already confirmed
        r_eval = _request("GET", self.url(f"/api/v1/evaluations/{self.eval_id}"),
                           label="fetch eval for duplicate confirm", expected=200)
        self._pass()
        self.expect_error(
            "POST",
            f"/api/v1/submissions/{self.submission_id}/evaluation:confirm",
            {
                "student_info":             r_eval["student_info"],
                "extracted_answers":        r_eval.get("extracted_answers", []),
                "evaluation_summary":       r_eval["evaluation_summary"],
                "question_wise_evaluation": r_eval["question_wise_evaluation"],
            },
            409,
            "POST /submissions/{id}/evaluation:confirm (already confirmed) → 409",
        )

        # 404: unknown submission
        self.expect_error(
            "POST",
            f"/api/v1/submissions/{uuid.uuid4()}/evaluation:confirm",
            {
                "student_info": {"student_name": "Ghost"},
                "extracted_answers": [],
                "evaluation_summary": {"full_marks": 0, "total_attempted": 0,
                                       "total_marks_awarded": 0, "percentage": 0,
                                       "overall_feedback": ""},
                "question_wise_evaluation": [],
            },
            404,
            "POST /submissions/{bad_id}/evaluation:confirm → 404",
        )

    # ── deletion tests (must run last in dependency order) ───────────────────

    def test_delete_submission_blocked(self):
        section("Submissions — delete blocked by evaluation")
        if not self.submission_id or not self.eval_id:
            skip("DELETE /submissions/{id} blocked test", "no eval"); self._skip(); return

        self.expect_error(
            "DELETE", f"/api/v1/submissions/{self.submission_id}", None, 409,
            "DELETE /submissions/{id} (evaluation exists) → 409",
        )

    def test_delete_evaluation(self):
        section("Evaluations — delete")
        if not self.eval_id:
            skip("DELETE /evaluations/{id}", "no eval_id"); self._skip(); return

        r = self.DELETE(
            f"/api/v1/evaluations/{self.eval_id}",
            label="DELETE /api/v1/evaluations/{id}",
        )
        info("message", r.get("message"))

        # 404 on second attempt
        self.expect_error("DELETE", f"/api/v1/evaluations/{self.eval_id}", None, 404,
                          "DELETE /evaluations/{id} (already deleted) → 404")
        self.eval_id = None

    def test_delete_submission(self):
        section("Submissions — delete (now that eval is gone)")
        if not self.submission_id:
            skip("DELETE /submissions/{id}", "no submission_id"); self._skip(); return

        r = self.DELETE(
            f"/api/v1/submissions/{self.submission_id}",
            label="DELETE /api/v1/submissions/{id}",
        )
        info("message", r.get("message"))

        self.expect_error("DELETE", f"/api/v1/submissions/{self.submission_id}", None, 404,
                          "DELETE /submissions/{id} (already deleted) → 404")
        self.submission_id = None

    def test_delete_paper(self):
        section("Papers — delete")
        if not self.paper_id:
            skip("DELETE /papers/{id}", "no paper_id"); self._skip(); return

        r = self.DELETE(
            f"/api/v1/papers/{self.paper_id}",
            label="DELETE /api/v1/papers/{id}",
        )
        info("message", r.get("message"))

        self.expect_error("DELETE", f"/api/v1/papers/{self.paper_id}", None, 404,
                          "DELETE /papers/{id} (already deleted) → 404")
        self.paper_id = None

    # ── summary ──────────────────────────────────────────────────────────────

    def summary(self):
        total = self.passed + self.failed + self.skipped
        print(f"\n{BOLD}{'═' * 60}{RESET}")
        print(f"{BOLD}  Results: "
              f"{_c(GREEN, str(self.passed))} passed  "
              f"{_c(RED,   str(self.failed))} failed  "
              f"{_c(YELLOW,str(self.skipped))} skipped  "
              f"({total} total){RESET}")
        print(f"{BOLD}{'═' * 60}{RESET}\n")
        if self.failed:
            sys.exit(1)

    # ── main run ─────────────────────────────────────────────────────────────

    def run(self):
        print(f"\n{BOLD}Question Paper API — Test Suite{RESET}")
        print(f"{DIM}Base URL: {self.base}{RESET}")

        try:
            self.test_health()
            self.test_papers_upload()
            self.test_papers_upload_duplicate()
            self.test_papers_errors()
            self.test_generate_rubric()
            self.test_generate_rubric_errors()
            self.test_papers_list()
            self.test_papers_get()
            self.test_confirm_paper()
            self.test_confirm_paper_errors()
            self.test_submissions_create()
            self.test_submissions_duplicate()
            self.test_submissions_errors()
            self.test_submissions_list()
            self.test_submissions_get()
            self.test_submissions_update_student_info()
            self.test_evaluation_generate()
            self.test_evaluation_generate_idempotent()
            self.test_evaluation_generate_errors()
            self.test_evaluations_list()
            self.test_evaluations_get()
            self.test_evaluation_confirm()
            self.test_evaluation_confirm_errors()
            self.test_delete_submission_blocked()
            self.test_delete_evaluation()
            self.test_delete_submission()
            self.test_delete_paper()
        except APIError as exc:
            print(f"\n{_c(RED, 'FATAL:')} unexpected API error — {exc}")
            self.failed += 1
        except KeyboardInterrupt:
            print(f"\n{_c(YELLOW, 'Interrupted.')}")

        self.summary()


# ── CLI ───────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Question Paper API test suite")
    parser.add_argument("--base",          default="http://localhost:8000",
                        help="API base URL  (default: http://localhost:8000)")
    parser.add_argument("--paper",         default=None,
                        help="Path to a real question paper PDF")
    parser.add_argument("--answer",        default=None,
                        help="Path to a real student answer PDF")
    parser.add_argument("--paper-id",      default=None,
                        help="Skip upload — use this paper_id (must already be confirmed)")
    parser.add_argument("--submission-id", default=None,
                        help="Skip submission upload — use this submission_id")
    parser.add_argument("--strictness",    default="medium",
                        choices=["easy", "medium", "hard", "extreme"],
                        help="Strictness level for rubric generation (default: medium)")
    args = parser.parse_args()

    runner = Runner(
        base=args.base,
        paper_pdf=args.paper,
        answer_pdf=args.answer,
        seed_paper_id=args.paper_id,
        seed_submission_id=args.submission_id,
        strictness=args.strictness,
    )
    runner.run()


if __name__ == "__main__":
    main()