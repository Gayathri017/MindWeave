"""Thin, typed wrapper around the Gemini API.

This is the only module in the codebase that imports the Gemini SDK --
keeping every call in one place makes it easy to audit exactly what we
send Google, and to swap providers later without touching business logic.
This key is only ever read here, server-side; it never reaches the client.
"""

import base64
import io
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


def generate_structured_from_file(
    file_bytes: bytes,
    mime_type: str,
    schema: type[_SchemaT],
    system_instruction: str | None = None,
) -> _SchemaT:
    """Like `generate_structured`, but the input is a file (PDF or image)
    rather than text -- used for pulling structured data out of documents,
    the same way `transcribe_audio` uploads audio.

    The API distinguishes a "document" content block (PDF only) from an
    "image" one (JPEG/PNG/WEBP/HEIC/etc) -- passing an image as "document"
    is rejected, so the block type has to follow the actual mime type.
    """
    file_stream = io.BytesIO(file_bytes)
    uploaded_file = _client.files.upload(file=file_stream, config={"mime_type": mime_type})

    content_type = "document" if mime_type == "application/pdf" else "image"
    interaction = _client.interactions.create(
        model=settings.gemini_chat_model,
        input=[{"type": content_type, "uri": uploaded_file.uri, "mime_type": uploaded_file.mime_type}],
        system_instruction=system_instruction,
        response_format={
            "type": "text",
            "mime_type": "application/json",
            "schema": schema.model_json_schema(),
        },
        store=False,
    )
    return schema.model_validate_json(interaction.output_text)


def generate_text_from_file(
    file_bytes: bytes,
    mime_type: str,
    question: str,
    system_instruction: str | None = None,
) -> str:
    """Like `generate_structured_from_file`, but for a plain conversational
    answer rather than a schema-validated extraction -- used for "here's a
    picture, answer this question about it" chat, not saving structured
    data. Same document-vs-image content-type distinction applies.
    """
    file_stream = io.BytesIO(file_bytes)
    uploaded_file = _client.files.upload(file=file_stream, config={"mime_type": mime_type})

    content_type = "document" if mime_type == "application/pdf" else "image"
    interaction = _client.interactions.create(
        model=settings.gemini_chat_model,
        input=[
            {"type": "text", "text": question},
            {"type": content_type, "uri": uploaded_file.uri, "mime_type": uploaded_file.mime_type},
        ],
        system_instruction=system_instruction,
        store=False,
    )
    return interaction.output_text


def generate_structured_from_video_url(
    video_url: str,
    schema: type[_SchemaT],
    system_instruction: str | None = None,
) -> _SchemaT:
    """Like `generate_structured_from_file`, but for a video the model can
    fetch itself by URL (e.g. a YouTube link) -- no upload step, since
    there are no local bytes to send. Gemini watches (video + audio) and
    understands the actual content, not just a scraped transcript.
    """
    interaction = _client.interactions.create(
        model=settings.gemini_chat_model,
        input=[{"type": "video", "uri": video_url}],
        system_instruction=system_instruction,
        response_format={
            "type": "text",
            "mime_type": "application/json",
            "schema": schema.model_json_schema(),
        },
        store=False,
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


_TRANSCRIBE_INSTRUCTION = (
    "Transcribe this audio exactly as spoken. Detect the spoken language "
    "automatically and write the transcript in that same language -- do "
    "not translate it into English or any other language, even if "
    "multiple languages are mixed together in the recording."
)


def transcribe_audio(audio_bytes: bytes, mime_type: str) -> str:
    """Upload a recording and return its transcript, in whatever language
    it was spoken in.

    Uses a dedicated transcription model rather than the general chat
    model -- it's built specifically for accurate speech-to-text (a full
    lecture, not a quick voice memo), and the audio never touches disk on
    our side: it goes from memory straight to Gemini's Files API and is
    discarded once this function returns.

    The transcription model doesn't accept `system_instruction` (it
    rejects the request outright if given one), so the language
    instruction is passed as a plain text part alongside the audio instead.
    """
    audio_stream = io.BytesIO(audio_bytes)
    uploaded_file = _client.files.upload(file=audio_stream, config={"mime_type": mime_type})

    interaction = _client.interactions.create(
        model=settings.gemini_transcribe_model,
        input=[
            {"type": "text", "text": _TRANSCRIBE_INSTRUCTION},
            {"type": "audio", "uri": uploaded_file.uri, "mime_type": uploaded_file.mime_type},
        ],
        store=False,
    )
    return interaction.output_text


def generate_image(prompt: str) -> tuple[bytes, str]:
    """Ask Gemini's image model to generate an image from a text prompt.

    Returns (image_bytes, mime_type). Raises if the model didn't return an
    image (e.g. it refused the prompt) -- callers decide how to degrade.
    """
    interaction = _client.interactions.create(
        model=settings.gemini_image_model,
        input=prompt,
        response_format={"type": "image"},
        store=False,
    )
    image = interaction.output_image
    if image is None or not image.data:
        raise RuntimeError("Gemini did not return an image for this prompt.")
    return base64.b64decode(image.data), image.mime_type or "image/png"


def generate_speech(text: str) -> tuple[bytes, str]:
    """Ask Gemini's TTS model to read a piece of text aloud.

    Returns (audio_bytes, mime_type). Raises if the model didn't return
    audio -- callers decide how to degrade (e.g. show the caption alone).
    """
    interaction = _client.interactions.create(
        model=settings.gemini_tts_model,
        input=text,
        response_format={"type": "audio"},
        store=False,
    )
    audio = interaction.output_audio
    if audio is None or not audio.data:
        raise RuntimeError("Gemini did not return audio for this text.")
    return base64.b64decode(audio.data), audio.mime_type or "audio/mp3"


def generate_title(text: str, max_chars_considered: int = 3000) -> str:
    """A short, descriptive title for a long piece of text, e.g. a lecture
    transcript -- unlike a short note, the first 100 characters of a
    transcript usually aren't a meaningful title on their own.
    """
    system_instruction = (
        "Write a short, specific title for this content -- six words or "
        "fewer, no quotation marks, no trailing punctuation."
    )
    title = generate_text(text[:max_chars_considered], system_instruction=system_instruction)
    return title.strip().strip('"')
