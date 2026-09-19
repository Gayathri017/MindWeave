"""Retrieval-augmented answering over a single user's saved knowledge."""

import logging
import uuid

from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.orm import ChatMessage, Chunk, Item
from app.models.schemas import ChatMessageOut, ChatSource
from app.services.gemini_client import embed_text, generate_image, generate_structured

logger = logging.getLogger(__name__)

_SYSTEM_INSTRUCTION = (
    "You are Mindweave's assistant. Each excerpt below is numbered, e.g. "
    "'[3] ...'. Answer the user's question using ONLY excerpts that are "
    "actually relevant -- you were given a broad first pass of possible "
    "matches, and some may be irrelevant noise; ignore those. If nothing "
    "relevant is here, say so plainly instead of guessing.\n\n"
    "Set used_excerpts to the numbers of exactly the excerpts you actually "
    "relied on to answer -- omit any that were provided but not relevant. "
    "This drives which sources get cited, so don't include one you didn't "
    "really use, and don't omit one you did.\n\n"
    "Separately, decide whether a generated image would meaningfully help "
    "this specific answer -- e.g. the user is asking you to draw or "
    "visualize something, or a diagram/chart would make a described "
    "process, comparison, or figure easier to understand than text alone. "
    "Most questions don't need one. If one would help, set image_prompt to "
    "a detailed, self-contained description of exactly what to draw -- it "
    "will be sent to an image generator with no other context. Otherwise "
    "leave image_prompt null."
)

# Cast a wide net (cheap -- just a vector index scan) so the chat call
# below has enough candidates to actually pick the relevant ones out of;
# a narrow top-K straight from cosine similarity has no way to recover
# from a semantically-close-but-irrelevant match crowding out a better one.
_CANDIDATE_POOL_SIZE = 20
_FALLBACK_TITLE_LENGTH = 60
_HISTORY_LIMIT = 100


class _ChatAnswer(BaseModel):
    answer: str = Field(..., description="The answer to the user's question.")
    used_excerpts: list[int] = Field(
        default_factory=list,
        description="The bracketed numbers (e.g. 3 for '[3]') of exactly the excerpts actually used to answer.",
    )
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


async def _save_turn(
    session: AsyncSession,
    user_id: str,
    folder_id: uuid.UUID | None,
    question: str,
    answer: str,
    sources: list[ChatSource],
) -> None:
    """Persist a question/answer pair to this scope's thread, so a folder's
    chat (or the global one) survives a page refresh. The generated image,
    if any, is deliberately not persisted -- it can be large, and it's
    cheap enough to regenerate if the user asks the same thing again.
    """
    session.add(ChatMessage(user_id=user_id, folder_id=folder_id, role="user", text=question))
    session.add(
        ChatMessage(
            user_id=user_id,
            folder_id=folder_id,
            role="answer",
            text=answer,
            sources=[source.model_dump(mode="json") for source in sources],
        )
    )
    await session.flush()


async def get_chat_history(
    session: AsyncSession, user_id: str, folder_id: uuid.UUID | None
) -> list[ChatMessageOut]:
    """The persisted thread for one scope (a folder, or the global chat if
    folder_id is None), oldest first, as the frontend expects to render it.
    """
    rows = (
        (
            await session.execute(
                select(ChatMessage)
                .where(ChatMessage.user_id == user_id, ChatMessage.folder_id == folder_id)
                .order_by(ChatMessage.created_at.asc())
                .limit(_HISTORY_LIMIT)
            )
        )
        .scalars()
        .all()
    )
    return [
        ChatMessageOut(
            role=row.role,
            text=row.text,
            sources=[ChatSource.model_validate(source) for source in (row.sources or [])],
            created_at=row.created_at,
        )
        for row in rows
    ]


async def answer_question(
    session: AsyncSession, user_id: str, question: str, folder_id: uuid.UUID | None = None
) -> tuple[str, list[ChatSource], bytes | None, str | None]:
    """Return (answer, sources, image_bytes, image_mime_type) for a
    question over the user's saved knowledge -- every item if folder_id is
    None, or only that folder's items otherwise. The image fields are None
    unless the model decided a generated image would help this answer.
    """
    query_vector = embed_text(question)

    chunk_query = select(Chunk).where(Chunk.user_id == user_id)
    if folder_id is not None:
        chunk_query = chunk_query.join(Item, Item.id == Chunk.item_id).where(Item.folder_id == folder_id)

    result = await session.execute(
        chunk_query.order_by(Chunk.embedding.cosine_distance(query_vector)).limit(_CANDIDATE_POOL_SIZE)
    )
    matches = result.scalars().all()

    if not matches:
        answer = (
            "You haven't saved anything here I can answer that from yet -- "
            "save something first, then ask me again."
        )
        await _save_turn(session, user_id, folder_id, question, answer, [])
        return answer, [], None, None

    context = "\n\n---\n\n".join(f"[{index}] {chunk.content}" for index, chunk in enumerate(matches, start=1))
    prompt = f"Saved excerpts:\n\n{context}\n\nQuestion: {question}"

    result = generate_structured(prompt, _ChatAnswer, system_instruction=_SYSTEM_INSTRUCTION)

    # The model tells us which numbered excerpts it actually relied on --
    # that's the reranking step, folded into the same call rather than a
    # separate one. Fall back to every candidate only if it returned
    # nothing usable (e.g. an empty or out-of-range list), so a citation
    # is never silently dropped by a model quirk.
    selected = {i for i in result.used_excerpts if 1 <= i <= len(matches)}
    used_matches = [matches[i - 1] for i in selected] if selected else matches

    source_item_ids = list({chunk.item_id for chunk in used_matches})
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

    await _save_turn(session, user_id, folder_id, question, result.answer, sources)
    return result.answer, sources, image_bytes, image_mime_type
