"""
models/paper.py
---------------
Data models for question papers.

Key design decisions
--------------------
* question_id is now a **string** everywhere (e.g. "1", "1a", "1.1", "Q1",
  "I", "ii").  Integer IDs are dead.
* Questions are organised as a **tree** of QuestionNode objects.
  A node may have children (sub-questions) and / or belong to a ChoiceGroup
  (either-or alternatives at the same level).
* PaperSection still groups top-level nodes for "Answer any N of M" logic,
  but now references string question_ids.
* The flat `questions` list on ParsedPaper is kept as a **derived convenience
  property** that returns every leaf node in DFS order so that legacy code
  (rubric generation, evaluator prompt building) that iterates all questions
  keeps working with zero changes.
"""

from __future__ import annotations

from typing import List, Optional, Literal
from pydantic import BaseModel, Field, model_validator
from enum import Enum

from models.rubric import Rubric, RubricResponse


# ---------------------------------------------------------------------------
# Strictness
# ---------------------------------------------------------------------------

class Strictness(str, Enum):
    easy    = "easy"
    medium  = "medium"
    hard    = "hard"
    extreme = "extreme"


# ---------------------------------------------------------------------------
# Paper Metadata
# ---------------------------------------------------------------------------

class PaperMetadata(BaseModel):
    subject_name:    str
    subject_code:    str
    degree:          str
    stream:          str
    exam_type:       str
    set_no:          str
    full_marks:      str
    total_duration:  float
    total_pages:     int


# ---------------------------------------------------------------------------
# ChoiceGroup — either-or alternatives
#
# Represents a group of mutually-exclusive questions where the student must
# answer exactly ONE (or occasionally more, governed by required_count).
#
# Examples
#   "Solve Q3a OR Q3b"
#   "Answer either (i) or (ii)"
#
# The IDs in `question_ids` reference sibling QuestionNodes that are tagged
# with choice_group_id == this group's id.
# ---------------------------------------------------------------------------

class ChoiceGroup(BaseModel):
    """A set of alternative questions where the student answers required_count of them."""
    choice_group_id: str            # unique within the paper, e.g. "cg_1a_1b"
    question_ids:    List[str]      # the question_id values of the alternatives
    required_count:  int = 1        # how many must be answered (almost always 1)
    label:           Optional[str] = None  # human-readable label, e.g. "OR"


# ---------------------------------------------------------------------------
# QuestionNode — the recursive tree unit
# ---------------------------------------------------------------------------

class QuestionNode(BaseModel):
    """
    A single node in the question hierarchy.

    Leaf nodes (no children) are actual answerable questions.
    Parent nodes group sub-questions but are not answered directly.

    Fields
    ------
    question_id         : string exactly as printed ("1", "1a", "Q.2", "III", "2(b)(ii)")
    display_id          : optional cleaned display label if the raw id is awkward
    question_markdown   : the question text (empty string for pure-group nodes)
    max_score           : marks for this question (0 for pure-group nodes)
    course_outcome      : e.g. "CO1", "CO2" — from paper if printed
    bloom_level         : e.g. "Remember", "L3" — from paper if printed
    section_name        : which section this node belongs to (e.g. "Part A")
    question_type       : "descriptive" | "mcq" | "group"
                          "group" = parent node that only contains children
    options             : MCQ choices exactly as printed (only for mcq nodes)
    children            : sub-questions (QuestionNode list, recursive)
    choice_group_id     : if set, this node is one alternative in an either-or group;
                          the value matches a ChoiceGroup.choice_group_id
    is_or_alternative   : True when this node is one branch of an OR choice
                          (convenience flag derived from choice_group_id being set)
    """
    question_id:       str
    display_id:        Optional[str]       = None
    question_markdown: str                 = ""
    max_score:         float               = 0.0
    course_outcome:    Optional[str]       = None
    bloom_level:       Optional[str]       = None
    section_name:      Optional[str]       = None
    question_type:     str                 = "descriptive"   # "descriptive" | "mcq" | "group"
    options:           Optional[List[str]] = None
    children:          List["QuestionNode"] = Field(default_factory=list)
    choice_group_id:   Optional[str]       = None
    is_or_alternative: bool                = False

    # Allow recursive model
    model_config = {"arbitrary_types_allowed": True}

    @model_validator(mode="after")
    def _sync_or_flag(self) -> "QuestionNode":
        if self.choice_group_id and not self.is_or_alternative:
            self.is_or_alternative = True
        return self

    # ------------------------------------------------------------------
    # Tree helpers
    # ------------------------------------------------------------------

    def is_leaf(self) -> bool:
        """A leaf node is directly answerable (not a pure group)."""
        return self.question_type != "group" and not self.children

    def leaves(self) -> List["QuestionNode"]:
        """Return all leaf descendants (DFS, left-to-right), including self if leaf."""
        if self.is_leaf():
            return [self]
        result: List["QuestionNode"] = []
        for child in self.children:
            result.extend(child.leaves())
        return result

    def all_nodes(self) -> List["QuestionNode"]:
        """Return self + all descendants (DFS)."""
        result = [self]
        for child in self.children:
            result.extend(child.all_nodes())
        return result


# ---------------------------------------------------------------------------
# ParsedPaper
# ---------------------------------------------------------------------------

class ParsedPaper(BaseModel):
    """
    Represents a fully OCR'd question paper.

    `question_tree` is the authoritative hierarchical structure.
    `sections` groups top-level questions for "Answer any N of M" logic.
    `choice_groups` lists all either-or groups in the paper.

    The `questions` property is a derived flat list of all *leaf* nodes,
    kept for backwards compatibility with services that iterate questions.
    """
    metadata:      PaperMetadata
    question_tree: List[QuestionNode]     = Field(default_factory=list)
    sections:      List["PaperSection"]   = Field(default_factory=list)
    choice_groups: List[ChoiceGroup]      = Field(default_factory=list)

    # ------------------------------------------------------------------
    # Convenience: flat leaf list (computed, not stored)
    # ------------------------------------------------------------------

    @property
    def questions(self) -> List[QuestionNode]:
        """All leaf QuestionNodes in DFS order."""
        leaves: List[QuestionNode] = []
        for node in self.question_tree:
            leaves.extend(node.leaves())
        return leaves

    @property
    def all_nodes(self) -> List[QuestionNode]:
        """Every node (including groups) in DFS order."""
        nodes: List[QuestionNode] = []
        for node in self.question_tree:
            nodes.extend(node.all_nodes())
        return nodes

    def find_node(self, question_id: str) -> Optional[QuestionNode]:
        """Find any node by question_id (DFS)."""
        for node in self.all_nodes:
            if node.question_id == question_id:
                return node
        return None

    def find_leaf(self, question_id: str) -> Optional[QuestionNode]:
        """Find a leaf node by question_id."""
        for node in self.questions:
            if node.question_id == question_id:
                return node
        return None


# ---------------------------------------------------------------------------
# PaperSection — "Answer any N of M questions"
# ---------------------------------------------------------------------------

class PaperSection(BaseModel):
    """
    Represents one answerable section, e.g. "Part A (2 × 5)".

    question_ids now references the top-level QuestionNode IDs that
    belong to this section.  For papers with sub-questions, these are
    the parent IDs (e.g. "1", "2", "3") and the scoring logic counts
    the whole question (sum of its leaves) as one attempt.
    """
    section_name:       str
    required_count:     int
    marks_per_question: float
    question_ids:       List[str]   # string IDs


# Resolve forward references
QuestionNode.model_rebuild()
ParsedPaper.model_rebuild()


# ---------------------------------------------------------------------------
# API Request / Response Models
# ---------------------------------------------------------------------------

class PaperOcrResponse(BaseModel):
    paper_id:     str
    sha256_hash:  str
    is_duplicate: bool
    parsed_paper: ParsedPaper
    message:      str


class PaperUploadResponse(BaseModel):
    """Kept for backwards compatibility. rubric is None until generated."""
    paper_id:     str
    sha256_hash:  str
    is_duplicate: bool
    parsed_paper: ParsedPaper
    rubric:       Optional[RubricResponse] = None
    message:      str


class RubricGenerateRequest(BaseModel):
    strictness: Strictness = Strictness.medium


class RubricGenerateResponse(BaseModel):
    paper_id:   str
    strictness: Strictness
    parsed_paper: ParsedPaper
    rubric:     RubricResponse
    message:    str


class PaperConfirmRequest(BaseModel):
    parsed_paper: ParsedPaper
    rubric:       Rubric


class PaperConfirmResponse(BaseModel):
    paper_id: str
    parsed_paper: ParsedPaper
    rubric: RubricResponse
    message:  str


class PaperSummary(BaseModel):
    paper_id:     str
    sha256_hash:  str
    subject_name: str
    subject_code: str
    exam_type:    str
    confirmed:    bool
    has_rubric:   bool


class PaperDetailResponse(BaseModel):
    paper_id:     str
    sha256_hash:  str
    confirmed:    bool
    parsed_paper: ParsedPaper
    rubric:       Optional[RubricResponse] = None


class PaperDeleteResponse(BaseModel):
    paper_id:              str
    message:               str
    ocr_results_deleted:   int = 0
    evaluations_deleted:   int = 0