"""Retrieval-augmented answering over a single user's saved knowledge.

When the saved items don't actually cover a question, this falls back --
first to a Tavily web search if one is configured, otherwise to the
model's own general knowledge -- rather than just refusing. Either way,
the fallback answer is required to say up front, plainly, that it isn't
coming from the user's saved notes; that disclosure is the whole point of
the fallback existing at all, so a user is never left thinking a general-
knowledge answer was actually grounded in something they saved.
"""

import logging
import uuid

from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.orm import ChatMessage, Chunk, Item
from app.models.schemas import ChatMessageOut, ChatSource, WebSource
from app.services.gemini_client import embed_text, generate_image, generate_structured
from app.services.web_search import search_web

logger = logging.getLogger(__name__)

_SYSTEM_INSTRUCTION = (
    "You are Mindweave's assistant. Each excerpt below is numbered, e.g. "
    "'[3] ...'. First, decide: do these excerpts actually contain enough "
    "to answer the question -- not just related, genuinely sufficient? "
    "Some of the excerpts may be irrelevant noise from a broad first-pass "
    "search; ignore those when judging.\n\n"
    "If they're sufficient: set notes_sufficient to true, write the "
    "answer using ONLY those excerpts, and set used_excerpts to the "
    "numbers of exactly the ones you relied on -- don't include one you "
    "didn't use, don't omit one you did, since this drives citations.\n\n"
    "If they're NOT sufficient: set notes_sufficient to false, leave "
    "answer and used_excerpts empty, and set web_search_query to a short, "
    "effective web search query for this question instead.\n\n"
    "Separately (only relevant if notes_sufficient is true), decide "
    "whether a generated image would meaningfully help this specific "
    "answer -- e.g. the user is asking you to draw or visualize "
    "something, or a diagram/chart would make a described process, "
    "comparison, or figure easier to understand than text alone. Most "
    "questions don't need one. If one would help, set image_prompt to a "
    "detailed, self-contained description of exactly what to draw -- it "
    "will be sent to an image generator with no other context. Otherwise "
    "leave image_prompt null."
)

_WEB_FALLBACK_INSTRUCTION = (
    "The user's saved notes don't cover this question. Each numbered "
    "result below is a real web search result. Answer using ONLY these "
    "results. Start your answer by clearly and plainly telling the user "
    "this isn't from their saved notes -- e.g. \"This isn't in your "
    "saved notes, but based on a web search: ...\" -- then answer. Set "
    "used_results to the numbers of the results you actually relied on.\n\n"
    "Separately, decide whether a generated image would meaningfully "
    "help this answer (see the general rule: only for something worth "
    "drawing or diagramming, not most questions). If so, set image_prompt "
    "accordingly; otherwise leave it null."
)

_GENERAL_KNOWLEDGE_FALLBACK_INSTRUCTION = (
    "The user's saved notes don't cover this question, and no web search "
    "is available. Answer using your own general knowledge. Start your "
    "answer by clearly and plainly telling the user this isn't from "
    "their saved notes -- e.g. \"This isn't in your saved notes, but "
    "here's what I know generally: ...\" -- then answer.\n\n"
    "Separately, decide whether a generated image would meaningfully "
    "help this answer (see the general rule: only for something worth "
    "drawing or diagramming, not most questions). If so, set image_prompt "
    "accordingly; otherwise leave it null."
)

# Cast a wide net (cheap -- just a vector index scan) so the chat call
# below has enough candidates to actually pick the relevant ones out of;
# a narrow top-K straight from cosine similarity has no way to recover
# from a semantically-close-but-irrelevant match crowding out a better one.
_CANDIDATE_POOL_SIZE = 20
_FALLBACK_TITLE_LENGTH = 60
_HISTORY_LIMIT = 100
_WEB_RESULTS = 5


class _ChatAnswer(BaseModel):
    notes_sufficient: bool = Field(..., description="True only if the excerpts genuinely contain enough to answer.")
    answer: str | None = Field(default=None, description="The answer, ONLY if notes_sufficient is true.")
    used_excerpts: list[int] = Field(default_factory=list)
    web_search_query: str | None = Field(
        default=None, description="If notes_sufficient is false, a short web search query for this question."
    )
    image_prompt: str | None = Field(default=None)


class _FallbackAnswer(BaseModel):
    answer: str = Field(..., description="The answer, starting with a plain disclosure that it's not from saved notes.")
    used_results: list[int] = Field(default_factory=list, description="Numbers of the web results actually used.")
    image_prompt: str | None = Field(default=None)


class AnswerResult(BaseModel):
    """Everything one call to answer_question produces, bundled so the
    router doesn't have to juggle a long positional tuple.
    """

    answer: str
    sources: list[ChatSource] = Field(default_factory=list)
    web_sources: list[WebSource] = Field(default_factory=list)
    from_notes: bool = True
    image_bytes: bytes | None = None
    image_mime_type: str | None = None


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


def _generate_image_safely(prompt: str | None, user_id: str) -> tuple[bytes | None, str | None]:
    if not prompt:
        return None, None
    try:
        return generate_image(prompt)
    except Exception:
        logger.exception("Image generation failed for user %s; returning text-only answer.", user_id)
        return None, None


def _answer_from_fallback(question: str, user_id: str) -> AnswerResult:
    """The saved notes didn't cover the question -- try a real web search
    first, and only drop to the model's unsourced general knowledge if
    Tavily isn't configured or the search itself comes back empty.
    """
    web_results = search_web(question)

    if web_results:
        context = "\n\n---\n\n".join(
            f"[{index}] {result.title}\n{result.url}\n{result.content}" for index, result in enumerate(web_results, start=1)
        )
        prompt = f"Web search results:\n\n{context}\n\nQuestion: {question}"
        result = generate_structured(prompt, _FallbackAnswer, system_instruction=_WEB_FALLBACK_INSTRUCTION)

        selected = {i for i in result.used_results if 1 <= i <= len(web_results)}
        used_results = [web_results[i - 1] for i in selected] if selected else web_results
        web_sources = [WebSource(title=r.title, url=r.url) for r in used_results]

        image_bytes, image_mime_type = _generate_image_safely(result.image_prompt, user_id)
        return AnswerResult(
            answer=result.answer,
            web_sources=web_sources,
            from_notes=False,
            image_bytes=image_bytes,
            image_mime_type=image_mime_type,
        )

    result = generate_structured(question, _FallbackAnswer, system_instruction=_GENERAL_KNOWLEDGE_FALLBACK_INSTRUCTION)
    image_bytes, image_mime_type = _generate_image_safely(result.image_prompt, user_id)
    return AnswerResult(answer=result.answer, from_notes=False, image_bytes=image_bytes, image_mime_type=image_mime_type)


async def _save_turn(session: AsyncSession, user_id: str, folder_id: uuid.UUID | None, question: str, result: AnswerResult) -> None:
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
            text=result.answer,
            sources=[source.model_dump(mode="json") for source in result.sources],
            web_sources=[source.model_dump(mode="json") for source in result.web_sources],
            from_notes=result.from_notes,
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
            web_sources=[WebSource.model_validate(source) for source in (row.web_sources or [])],
            from_notes=row.from_notes,
            created_at=row.created_at,
        )
        for row in rows
    ]


async def answer_question(session: AsyncSession, user_id: str, question: str, folder_id: uuid.UUID | None = None) -> AnswerResult:
    """Answer a question over the user's saved knowledge -- every item if
    folder_id is None, or only that folder's items otherwise. Falls back
    to a web search (or general knowledge, if no web search is available)
    when the saved items don't cover it, always disclosing that fallback
    plainly in the answer text itself.
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
        # Nothing saved at all (in this scope) to even check -- skip
        # straight to the fallback rather than spending a Gemini call
        # confirming what we already know.
        answer_result = _answer_from_fallback(question, user_id)
        await _save_turn(session, user_id, folder_id, question, answer_result)
        return answer_result

    context = "\n\n---\n\n".join(f"[{index}] {chunk.content}" for index, chunk in enumerate(matches, start=1))
    prompt = f"Saved excerpts:\n\n{context}\n\nQuestion: {question}"

    result = generate_structured(prompt, _ChatAnswer, system_instruction=_SYSTEM_INSTRUCTION)

    if not result.notes_sufficient:
        answer_result = _answer_from_fallback(result.web_search_query or question, user_id)
        await _save_turn(session, user_id, folder_id, question, answer_result)
        return answer_result

    # The model tells us which numbered excerpts it actually relied on --
    # that's the reranking step, folded into the same call rather than a
    # separate one. Fall back to every candidate only if it returned
    # nothing usable (e.g. an empty or out-of-range list), so a citation
    # is never silently dropped by a model quirk.
    selected = {i for i in result.used_excerpts if 1 <= i <= len(matches)}
    used_matches = [matches[i - 1] for i in selected] if selected else matches

    source_item_ids = list({chunk.item_id for chunk in used_matches})
    source_items = (await session.execute(select(Item).where(Item.id.in_(source_item_ids)))).scalars().all()
    sources = [ChatSource(id=item.id, title=_display_title(item)) for item in source_items]

    image_bytes, image_mime_type = _generate_image_safely(result.image_prompt, user_id)

    answer_result = AnswerResult(
        answer=result.answer or "",
        sources=sources,
        from_notes=True,
        image_bytes=image_bytes,
        image_mime_type=image_mime_type,
    )
    await _save_turn(session, user_id, folder_id, question, answer_result)
    return answer_result
