from typing import Any, Dict, List, Literal
from pydantic import BaseModel


# ---------------------------------------------------------------------------
# Rubric history
# ---------------------------------------------------------------------------

class RubricHistoryRecord(BaseModel):
    """A single snapshot of rubric + parsed-paper state before a confirm."""
    paper_id: str
    rubric_json: Dict[str, Any]        # deserialised Rubric payload
    parsed_paper_json: Dict[str, Any]  # deserialised ParsedPaper payload
    changed_at: str                    # ISO-8601 datetime string from SQLite
    action: Literal["confirm", "edit"]


class RubricHistoryResponse(BaseModel):
    paper_id: str
    history: List[RubricHistoryRecord]


# ---------------------------------------------------------------------------
# Evaluation history
# ---------------------------------------------------------------------------

class EvaluationHistoryRecord(BaseModel):
    """A single snapshot of an EvaluationReport state before a confirm."""
    eval_id: str
    evaluation_json: Dict[str, Any]    # deserialised EvaluationReport payload
    changed_at: str
    action: Literal["confirm", "edit"]


class EvaluationHistoryResponse(BaseModel):
    eval_id: str
    history: List[EvaluationHistoryRecord]
