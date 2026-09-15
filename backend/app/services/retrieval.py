"""Retrieval-augmented answering over a single user's saved knowledge."""

import logging

from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.orm import Chunk, Item
from app.models.schemas import ChatSource
from app.services.gemini_client import embed_text, generate_image, generate_structured

logger = logging.getLogger(__name__)

_SYSTEM_INSTRUCTION = (
    "You are Mindweave's assistant. Answer the user's question using ONLY "
    "the provided excerpts from their own saved notes and links. If the "
    "excerpts don't contain the answer, say so plainly instead of guessing.\n\n"
    "Separately, decide whether a generated image would meaningfully help "
    "this specific answer -- e.g. the user is asking you to draw or "
    "visualize something, or a diagram/chart would make a described "
    "process, comparison, or figure easier to understand than text alone. "
    "Most questions don't need one. If one would help, set image_prompt to "
    "a detailed, self-contained description of exactly what to draw -- it "
    "will be sent to an image generator with no other context. Otherwise "
    "leave image_prompt null."
)

_TOP_K = 6
_FALLBACK_TITLE_LENGTH = 60


class _ChatAnswer(BaseModel):
    answer: str = Field(..., description="The answer to the user's question.")
    image_prompt: str | None = Field(
        default=None,
        description="A detailed prompt for an image generator, only if an image would meaningfully help this answer.",
    )


def _display_title(item: Item) -> str:
    """A title if the item has one, otherwise the start of its text --
    mirrors the preview shown in the saved-items list, so a citation reads
    the same as the item does everywhere else in the app.
    """
    if item.title:
        return item.title
    stripped = item.raw_text.strip()
    if len(stripped) <= _FALLBACK_TITLE_LENGTH:
        return stripped
    return stripped[:_FALLBACK_TITLE_LENGTH].rsplit(" ", 1)[0] + "…"


async def answer_question(
    session: AsyncSession, user_id: str, question: str
) -> tuple[str, list[ChatSource], bytes | None, str | None]:
    """Return (answer, sources, image_bytes, image_mime_type) for a
    question over the user's saved knowledge. The image fields are None
    unless the model decided a generated image would help this answer.
    """
    query_vector = embed_text(question)

    result = await session.execute(
        select(Chunk)
        .where(Chunk.user_id == user_id)
        .order_by(Chunk.embedding.cosine_distance(query_vector))
        .limit(_TOP_K)
    )
    matches = result.scalars().all()

    if not matches:
        return (
            "You haven't saved anything I can answer that from yet -- "
            "save a link or note first, then ask me again.",
            [],
            None,
            None,
        )

    context = "\n\n---\n\n".join(chunk.content for chunk in matches)
    prompt = f"Saved excerpts:\n\n{context}\n\nQuestion: {question}"

    result = generate_structured(prompt, _ChatAnswer, system_instruction=_SYSTEM_INSTRUCTION)

    source_item_ids = list({chunk.item_id for chunk in matches})
    source_items = (
        (await session.execute(select(Item).where(Item.id.in_(source_item_ids)))).scalars().all()
    )
    sources = [ChatSource(id=item.id, title=_display_title(item)) for item in source_items]

    image_bytes, image_mime_type = None, None
    if result.image_prompt:
        try:
            image_bytes, image_mime_type = generate_image(result.image_prompt)
        except Exception:
            logger.exception("Image generation failed for user %s; returning text-only answer.", user_id)

    return result.answer, sources, image_bytes, image_mime_type
