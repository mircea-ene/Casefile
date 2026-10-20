import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class DocumentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    filename: str
    size_bytes: int
    content_type: str
    status: Literal["processing", "ready", "failed"]
    created_at: datetime


class DocumentFileUrl(BaseModel):
    url: str
    expires_at: datetime
    filename: str
    content_type: str


class DocumentList(BaseModel):
    documents: list[DocumentOut]


class ChatRequest(BaseModel):
    question: str = Field(max_length=4000)
    # Kept as strings so unknown or malformed ids get the contract's 404, not a 422.
    document_ids: list[str] | None = None
    # Omitted or null starts a new conversation.
    conversation_id: str | None = None

    @field_validator("question")
    @classmethod
    def question_not_blank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Question must not be empty")
        return value


class BoundingBox(BaseModel):
    """Fractions of the page size (0-1), origin top-left."""

    page: int
    x: float
    y: float
    width: float
    height: float


class Location(BaseModel):
    """Where a chunk sits in its document."""

    id: str  # chunk id
    document_id: str
    document_name: str
    page: int | None  # first page
    page_end: int | None
    section: str | None  # last element of heading_path, e.g. "12.2 Notice"
    heading_path: str | None  # e.g. "Lease Agreement > 12. Termination > 12.2 Notice"
    element_type: Literal["text", "table", "definition"]
    text_source: Literal["text_layer", "ocr"]
    # The chunk's paragraphs on the page (the whole chunk, not just the quote).
    bboxes: list[BoundingBox]


class Citation(Location):
    quote: str


class Source(Location):
    """A chunk the LLM was given to answer from."""

    content: str
    similarity: float
    # The [n] marker that cites this source in `answer`, or null if it isn't cited.
    citation: int | None
    # "hit": found by search; "section": included because the rest of its section
    # was relevant. Turns saved before 2026-10-19 lack it, hence the default.
    match: Literal["hit", "section"] = "hit"


class ChatAnswer(BaseModel):
    answer: str
    citations: list[Citation]
    sources: list[Source]
    insufficient_evidence: bool


class TurnOut(ChatAnswer):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    question: str
    document_ids: list[uuid.UUID] | None
    created_at: datetime


class ChatResponse(TurnOut):
    conversation_id: uuid.UUID


class ConversationOut(BaseModel):
    id: uuid.UUID
    # The user's title if set, else the generated one, else the start of the first question.
    title: str
    title_is_custom: bool
    # True until the generated title is written; poll GET /conversations meanwhile.
    title_pending: bool
    created_at: datetime
    updated_at: datetime


class ConversationList(BaseModel):
    conversations: list[ConversationOut]


class ConversationDetail(ConversationOut):
    turns: list[TurnOut]


class ConversationUpdate(BaseModel):
    # null or blank goes back to the generated title.
    title: str | None = Field(max_length=200)

    @field_validator("title")
    @classmethod
    def blank_is_none(cls, value: str | None) -> str | None:
        value = (value or "").strip()
        return value or None
