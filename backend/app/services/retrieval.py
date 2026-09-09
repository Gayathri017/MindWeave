"""Retrieval-augmented answering over a single user's saved knowledge."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.orm import Chunk
from app.services.gemini_client import embed_text, generate_text

_SYSTEM_INSTRUCTION = (
    "You are Mindweave's assistant. Answer the user's question using ONLY "
    "the provided excerpts from their own saved notes and links. If the "
    "excerpts don't contain the answer, say so plainly instead of guessing."
)

_TOP_K = 6


async def answer_question(session: AsyncSession, user_id: str, question: str) -> tuple[str, list[str]]:
    """Return (answer, source_item_ids) for a question over the user's saved knowledge."""
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
        )

    context = "\n\n---\n\n".join(chunk.content for chunk in matches)
    prompt = f"Saved excerpts:\n\n{context}\n\nQuestion: {question}"

    answer = generate_text(prompt, system_instruction=_SYSTEM_INSTRUCTION)
    source_ids = list({str(chunk.item_id) for chunk in matches})
    return answer, source_ids
