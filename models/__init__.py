"""
models package
Re-exports all public schema symbols so the rest of the codebase can continue
importing from `models.schemas` or directly from `models`.
"""

from models.rubric import (
    ExpectedDepth,
    Concept,
    PartialMarkingRule,
    RubricQuestion,
    Rubric,
    RubricResponse,
    build_rubric_response,
)

from models.paper import (
    PaperMetadata,
    ParsedPaper,
    PaperUploadResponse,
    PaperConfirmRequest,
    PaperConfirmResponse,
    PaperSummary,
    PaperDetailResponse,
    PaperDeleteResponse,
)

from models.evaluation import (
    StudentInfo,
    EvaluationSummary,
    build_evaluation_summary,
    ConceptVerdict,
    ConceptEvaluation,
    QuestionEvaluation,
    ExtractedAnswer,
    EvaluationReport,
    OcrResponse,
    OcrDeleteResponse,
    EvaluateRequest,
    EvaluationResponse,
    EvaluationSummaryResponse,
    EvaluationConfirmRequest,
    EvaluationConfirmResponse,
    EvaluationDeleteResponse,
)

__all__ = [
    # rubric
    "ExpectedDepth",
    "Concept",
    "PartialMarkingRule",
    "RubricQuestion",
    "Rubric",
    "RubricResponse",
    "build_rubric_response",
    # paper
    "PaperMetadata",
    "ParsedPaper",
    "PaperUploadResponse",
    "PaperConfirmRequest",
    "PaperConfirmResponse",
    "PaperSummary",
    "PaperDetailResponse",
    "PaperDeleteResponse",
    # evaluation
    "StudentInfo",
    "EvaluationSummary",
    "build_evaluation_summary",
    "ConceptVerdict",
    "ConceptEvaluation",
    "QuestionEvaluation",
    "ExtractedAnswer",
    "EvaluationReport",
    "OcrResponse",
    "EvaluateRequest",
    "EvaluationResponse",
    "EvaluationSummaryResponse",
    "EvaluationConfirmRequest",
    "EvaluationConfirmResponse",
    "EvaluationDeleteResponse",
]