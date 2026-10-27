"""
models.py - The fixed "shapes" of data.

Every AI agent must answer in one of these shapes. Pydantic checks the answer:
if a field is missing or wrong, we ask the AI once more. This is how we stop
messy AI output from breaking the pipeline.
"""

from typing import Literal

from pydantic import BaseModel, Field, field_validator


# ---------------------------------------------------------------------------
# Helpers used by several models
# ---------------------------------------------------------------------------
def _clean_severity(value) -> str:
    """Normalise severities like 'HIGH', 'Critical', 'info' into our 4 levels."""
    text = str(value or "low").strip().lower()
    if text in ("critical", "blocker"):
        return "critical"
    if text in ("high", "major", "error"):
        return "high"
    if text in ("medium", "moderate", "warning"):
        return "medium"
    return "low"


def _clean_line(value):
    """AI sometimes writes line numbers as text ('12', 'N/A'); keep a number or None."""
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


# ---------------------------------------------------------------------------
# Agent 1: Business Analyst
# ---------------------------------------------------------------------------
class Requirement(BaseModel):
    id: str                                   # e.g. "REQ-01"
    text: str
    type: str = "functional"                  # functional | non_functional


class UserStory(BaseModel):
    id: str                                   # e.g. "US-01"
    text: str                                 # "As a customer, I want ..., so that ..."


class AcceptanceCriterion(BaseModel):
    id: str                                   # e.g. "AC-01"
    requirement_id: str                       # which REQ it proves
    text: str                                 # measurable: "valid update returns HTTP 200"


class AnalysisResult(BaseModel):
    title: str = "Feature"
    summary: str = ""
    requirements: list[Requirement]
    user_stories: list[UserStory] = []
    acceptance_criteria: list[AcceptanceCriterion]
    business_rules: list[str] = []
    dependencies: list[str] = []
    assumptions: list[str] = []               # things WE assumed (never silently turned into requirements)
    questions: list[str] = []                 # things the human should answer
    ambiguities: list[str] = []               # unclear or contradictory parts


# ---------------------------------------------------------------------------
# Agent 2: Solution Designer
# ---------------------------------------------------------------------------
class Endpoint(BaseModel):
    method: str
    path: str
    description: str = ""
    request_model: str = ""
    response_model: str = ""
    status_codes: list[str] = []


class DataModel(BaseModel):
    name: str
    fields: list[str] = []


class DesignResult(BaseModel):
    overview: str = ""
    components: list[str] = []
    endpoints: list[Endpoint] = []
    data_models: list[DataModel] = []
    validation_rules: list[str] = []
    error_handling: list[str] = []
    logging: list[str] = []
    security: list[str] = []
    file_structure: list[str] = []


# ---------------------------------------------------------------------------
# Agents 5 & 6: Code Reviewer and Security Agent
# ---------------------------------------------------------------------------
class Finding(BaseModel):
    severity: str = "low"
    category: str = ""
    file: str = ""
    line: int | None = None
    title: str
    evidence: str = ""
    recommendation: str = ""

    _sev = field_validator("severity", mode="before")(_clean_severity)
    _line = field_validator("line", mode="before")(_clean_line)


class ReviewResult(BaseModel):
    summary: str = ""
    findings: list[Finding] = []


# ---------------------------------------------------------------------------
# Agent 4: Test Engineer (mapping part; the test code comes as file blocks)
# ---------------------------------------------------------------------------
class AcTestMapping(BaseModel):
    acceptance_criterion: str
    tests: list[str] = []


# ---------------------------------------------------------------------------
# API request bodies (what the dashboard sends)
# ---------------------------------------------------------------------------
class CreateRunRequest(BaseModel):
    requirement: str = Field(min_length=10, description="The feature request in plain words")
    title: str | None = None


class ApprovalRequest(BaseModel):
    decision: Literal["approve", "reject"]
    comment: str = ""
    approver: str = "developer"
    # Only for design approval: where to go back to when rejecting.
    target: Literal["requirements", "design"] | None = None


class GateUpdateRequest(BaseModel):
    values: dict
