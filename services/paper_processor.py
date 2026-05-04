"""
services/paper_processor.py
----------------------------
Utility functions and the PaperProcessor orchestration class.
No logic changes — just updated imports for the new model names.
"""

import hashlib
import uuid

from services.ocr_service import OCRService
from services.rubric_service import RubricService
from models.schemas import ParsedPaper, Rubric


def compute_sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def generate_paper_id() -> str:
    return str(uuid.uuid4())


class PaperProcessor:
    """Orchestrates OCR → Rubric generation pipeline."""

    def __init__(self):
        self.ocr       = OCRService()
        self.rubric_gen = RubricService()

    async def process(self, pdf_bytes: bytes) -> tuple[ParsedPaper, Rubric]:
        parsed_paper = await self.ocr.extract_questions(pdf_bytes)
        rubric       = await self.rubric_gen.generate_rubric(parsed_paper)
        return parsed_paper, rubric