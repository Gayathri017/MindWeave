"""Pydantic request/response models for the public API."""

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator


class SaveItemRequest(BaseModel):
    source_type: Literal["url", "text"]
    content: str = Field(..., min_length=1, max_length=50_000, description="A URL, or raw text to save.")
    folder_id: uuid.UUID | None = Field(default=None, description="Folder to file this item into, if any.")
    timezone: str | None = Field(
        default=None,
        description="IANA timezone name (e.g. 'Asia/Kolkata'), detected client-side. Falls back to UTC if omitted or not a real timezone.",
    )


class ItemSummary(BaseModel):
    id: uuid.UUID
    source_type: str
    source_url: str | None
    title: str | None
    folder_id: uuid.UUID | None = None
    created_at: datetime


class ItemWithConcepts(ItemSummary):
    concepts: list[str] = Field(default_factory=list)
    preview: str = Field(
        default="", description="First ~100 characters of the saved text, for display when there's no title."
    )
    extracted_data: dict | None = Field(
        default=None,
        description="Structured fields pulled from a document (key_fields, line_items, figures), if any.",
    )


class UpdateItemFolderRequest(BaseModel):
    folder_id: uuid.UUID | None = Field(default=None, description="Folder to move this item into, or null to unfile it.")


class CreateFolderRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)


class FolderSummary(BaseModel):
    id: uuid.UUID
    name: str
    item_count: int = 0
    created_at: datetime


class ChatRequest(BaseModel):
    question: str = Field(..., min_length=1, max_length=2_000)
    folder_id: uuid.UUID | None = Field(
        default=None, description="Scope the question (and its history) to one folder's items, or omit for global."
    )


class TranscriptionResponse(BaseModel):
    text: str


class ChatSource(BaseModel):
    id: uuid.UUID
    title: str


class WebSource(BaseModel):
    title: str
    url: str
    content: str = Field(default="", exclude=True, repr=False)
    """The excerpt Tavily returned, kept only long enough to build the
    citation prompt -- excluded from every response/persisted payload so
    it never bloats the API response or the stored chat history."""

    @field_validator("url")
    @classmethod
    def _url_must_be_http(cls, value: str) -> str:
        # Defense in depth: this is rendered as a clickable <a href> in the
        # frontend, so a non-http(s) scheme (e.g. javascript:) sneaking in
        # here -- from a compromised/misbehaving search API, or a future
        # bug -- would otherwise become an executable link, not just data.
        if not value.lower().startswith(("http://", "https://")):
            raise ValueError(f"Web source URL must be http(s), got: {value!r}")
        return value


class ChatResponse(BaseModel):
    answer: str
    sources: list[ChatSource] = Field(default_factory=list, description="The items the answer drew from.")
    web_sources: list[WebSource] = Field(
        default_factory=list,
        description="Web pages the answer drew from, only present when the saved items didn't cover the question.",
    )
    from_notes: bool = Field(
        default=True, description="False when this answer came from the web/general knowledge, not the saved items."
    )
    image: str | None = Field(
        default=None, description="A data URL (data:<mime>;base64,...) for a generated image, if one was made."
    )


class ChatMessageOut(BaseModel):
    role: Literal["user", "answer"]
    text: str
    sources: list[ChatSource] = Field(default_factory=list)
    web_sources: list[WebSource] = Field(default_factory=list)
    from_notes: bool = True
    created_at: datetime


class ExplainerSceneOut(BaseModel):
    narration: str
    image: str | None = Field(default=None, description="A data URL for this scene's generated image, if one was made.")
    audio: str | None = Field(default=None, description="A data URL for this scene's narration audio, if it was made.")


class ExplainerResponse(BaseModel):
    title: str
    scenes: list[ExplainerSceneOut]


class GraphNode(BaseModel):
    id: uuid.UUID
    name: str


class GraphEdge(BaseModel):
    source: uuid.UUID
    target: uuid.UUID
    weight: int


class GraphResponse(BaseModel):
    nodes: list[GraphNode]
    edges: list[GraphEdge]
