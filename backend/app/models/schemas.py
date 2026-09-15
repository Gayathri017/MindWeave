"""Pydantic request/response models for the public API."""

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class SaveItemRequest(BaseModel):
    source_type: Literal["url", "text"]
    content: str = Field(..., min_length=1, max_length=50_000, description="A URL, or raw text to save.")
    timezone: str | None = Field(
        default=None,
        description="IANA timezone name (e.g. 'Asia/Kolkata'), detected client-side. Falls back to UTC if omitted or not a real timezone.",
    )


class ItemSummary(BaseModel):
    id: uuid.UUID
    source_type: str
    source_url: str | None
    title: str | None
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


class ChatRequest(BaseModel):
    question: str = Field(..., min_length=1, max_length=2_000)


class TranscriptionResponse(BaseModel):
    text: str


class ChatSource(BaseModel):
    id: uuid.UUID
    title: str


class ChatResponse(BaseModel):
    answer: str
    sources: list[ChatSource] = Field(default_factory=list, description="The items the answer drew from.")
    image: str | None = Field(
        default=None, description="A data URL (data:<mime>;base64,...) for a generated image, if one was made."
    )


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
