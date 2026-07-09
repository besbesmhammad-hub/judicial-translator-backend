from pydantic import BaseModel, Field


class TranslateRequest(BaseModel):
    text: str = Field(..., min_length=1)
    source_lang: str = "auto"
    target_lang: str | None = None
    notes: str | None = None
    document_kind: str | None = None
    structure_notes: str | None = None


class AccountingChatRequest(BaseModel):
    message: str = Field(..., min_length=1)
    context: str | None = None
    language: str = "francais"


class RetrievedTerm(BaseModel):
    id: str
    source: str
    target: str
    guidance: str


class TranslateResponse(BaseModel):
    success: bool
    translation: str
    summary: list[str]
    quality_notes: list[str]
    metadata: dict
    source_lang: str
    target_lang: str
    document_kind: str
    skill_profile: str
    route: str | None = None
    classification: dict | None = None
    active_skills: list[str]
    retrieved_terms: list[RetrievedTerm]
    chunks: int
    model: str


class AnalyzeResponse(BaseModel):
    success: bool
    text: str
    document_kind: str
    file_format: str | None = None
    structure_notes: str
    active_skills: list[str]
    characters: int
