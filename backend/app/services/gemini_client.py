"""Thin, typed wrapper around the Gemini API.

This is the only module in the codebase that imports the Gemini SDK --
keeping every call in one place makes it easy to audit exactly what we
send Google, and to swap providers later without touching business logic.
This key is only ever read here, server-side; it never reaches the client.
"""

from typing import TypeVar

from google import genai
from pydantic import BaseModel

from app.config import get_settings

settings = get_settings()
_client = genai.Client(api_key=settings.gemini_api_key)

_SchemaT = TypeVar("_SchemaT", bound=BaseModel)


def embed_text(text: str) -> list[float]:
    """Return a single embedding vector for one piece of text."""
    return embed_texts([text])[0]


def embed_texts(texts: list[str]) -> list[list[float]]:
    """Embed one or more pieces of text in a single call.

    NOTE: verify the `output_dimensionality` config shape against
    https://ai.google.dev/gemini-api/docs/embeddings before relying on
    this in production -- Matryoshka dimension truncation was added
    recently and the exact kwarg may have shifted since this was written.
    """
    result = _client.models.embed_content(
        model=settings.gemini_embedding_model,
        contents=texts,
        config={"output_dimensionality": settings.embedding_dimensions},
    )
    return [embedding.values for embedding in result.embeddings]


def generate_structured(
    prompt: str, schema: type[_SchemaT], system_instruction: str | None = None
) -> _SchemaT:
    """Ask Gemini for a response that validates against a Pydantic schema."""
    interaction = _client.interactions.create(
        model=settings.gemini_chat_model,
        input=prompt,
        system_instruction=system_instruction,
        response_format={
            "type": "text",
            "mime_type": "application/json",
            "schema": schema.model_json_schema(),
        },
        store=False,  # We manage our own context; no reason for Google to retain this.
    )
    return schema.model_validate_json(interaction.output_text)


def generate_text(prompt: str, system_instruction: str | None = None) -> str:
    """Ask Gemini for a plain-text response (used for the RAG chat answer)."""
    interaction = _client.interactions.create(
        model=settings.gemini_chat_model,
        input=prompt,
        system_instruction=system_instruction,
        store=False,
    )
    return interaction.output_text
