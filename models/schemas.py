"""
Backwards-compatibility shim.
All symbols imported from their canonical modules and re-exported here
so that `from models.schemas import X` keeps working everywhere.
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
    Strictness,
    PaperMetadata,
    ParsedQuestion,
    ParsedPaper,
    PaperOcrResponse,
    PaperUploadResponse,
    RubricGenerateRequest,
    RubricGenerateResponse,
    PaperConfirmRequest,
    PaperConfirmResponse,
    PaperSummary,
    PaperDetailResponse,
    PaperDeleteResponse,
)

from models.evaluation import (
    StudentInfo,
    EvaluationSummary,
    ConceptVerdict,
    ConceptEvaluation,
    QuestionEvaluation,
    ExtractedAnswer,
    EvaluationReport,
    build_evaluation_summary,
    # Submission models (new public names)
    SubmissionResponse,
    SubmissionSummaryResponse,
    SubmissionStudentInfoUpdateRequest,
    SubmissionDeleteResponse,
    # Evaluation models
    EvaluateRequest,
    EvaluationResponse,
    EvaluationSummaryResponse,
    EvaluationConfirmRequest,
    EvaluationConfirmResponse,
    EvaluationDeleteResponse,
    # Legacy aliases
    OcrResponse,
    OcrSummaryResponse,
    OcrStudentInfoUpdateRequest,
    OcrDeleteResponse,
)

__all__ = [
    # rubric
    "ExpectedDepth", "Concept", "PartialMarkingRule", "RubricQuestion",
    "Rubric", "RubricResponse", "build_rubric_response",
    # paper
    "Strictness", "PaperMetadata", "ParsedQuestion", "ParsedPaper",
    "PaperOcrResponse", "PaperUploadResponse",
    "RubricGenerateRequest", "RubricGenerateResponse",
    "PaperConfirmRequest", "PaperConfirmResponse",
    "PaperSummary", "PaperDetailResponse", "PaperDeleteResponse",
    # evaluation core
    "StudentInfo", "EvaluationSummary", "ConceptVerdict", "ConceptEvaluation",
    "QuestionEvaluation", "ExtractedAnswer", "EvaluationReport",
    "build_evaluation_summary",
    # submission API
    "SubmissionResponse", "SubmissionSummaryResponse",
    "SubmissionStudentInfoUpdateRequest", "SubmissionDeleteResponse",
    # evaluation API
    "EvaluateRequest", "EvaluationResponse", "EvaluationSummaryResponse",
    "EvaluationConfirmRequest", "EvaluationConfirmResponse", "EvaluationDeleteResponse",
    # legacy
    "OcrResponse", "OcrSummaryResponse", "OcrStudentInfoUpdateRequest", "OcrDeleteResponse",
]