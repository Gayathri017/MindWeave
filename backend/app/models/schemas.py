"""Pydantic request/response models for the public API."""

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class SaveItemRequest(BaseModel):
    source_type: Literal["url", "text"]
    content: str = Field(..., min_length=1, max_length=50_000, description="A URL, or raw text to save.")


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

class ChatRequest(BaseModel):
    question: str = Field(..., min_length=1, max_length=2_000)


class ChatResponse(BaseModel):
    answer: str
    sources: list[str] = Field(default_factory=list, description="Item ids the answer drew from.")


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