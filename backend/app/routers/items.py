"""HTTP routes for saving items and chatting with the user's saved knowledge."""

import logging
import uuid

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile, status
from slowapi import Limiter
from slowapi.util import get_remote_address
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_user_id
from app.config import get_settings
from app.database import get_db_for_request
from app.models.schemas import ChatRequest, ChatResponse, ItemSummary, ItemWithConcepts, SaveItemRequest
from app.services.ingestion import DailyLimitExceeded, save_audio_item, save_item
from app.services.items import delete_item, list_items
from app.services.retrieval import answer_question

router = APIRouter()
limiter = Limiter(key_func=get_remote_address)
settings = get_settings()
logger = logging.getLogger(__name__)

_MAX_AUDIO_BYTES = 100 * 1024 * 1024  # 100 MB -- generous for a multi-hour lecture


@router.post("/items", response_model=ItemSummary, status_code=status.HTTP_201_CREATED)
@limiter.limit("20/minute")
async def create_item(
    request: Request,
    body: SaveItemRequest,
    user_id: str = Depends(get_current_user_id),
    session: AsyncSession = Depends(get_db_for_request),
) -> ItemSummary:
    try:
        item = await save_item(session, user_id, body, settings.max_items_per_user_per_day)
    except DailyLimitExceeded as exc:
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail=str(exc)) from exc

    return ItemSummary(
        id=item.id,
        source_type=item.source_type,
        source_url=item.source_url,
        title=item.title,
        created_at=item.created_at,
    )


@router.post("/items/audio", response_model=ItemSummary, status_code=status.HTTP_201_CREATED)
@limiter.limit("10/minute")
async def upload_audio_item(
    request: Request,
    file: UploadFile = File(...),
    timezone: str | None = Form(default=None),
    user_id: str = Depends(get_current_user_id),
    session: AsyncSession = Depends(get_db_for_request),
) -> ItemSummary:
    """Accepts an audio recording -- whether just captured live in the
    browser or picked from an existing file, both arrive here the same
    way -- transcribes it, and saves it through the normal pipeline.
    """
    audio_bytes = await file.read()
    if len(audio_bytes) > _MAX_AUDIO_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"Audio file is too large (max {_MAX_AUDIO_BYTES // (1024 * 1024)} MB).",
        )

    mime_type = file.content_type or "audio/webm"

    try:
        item = await save_audio_item(
            session, user_id, audio_bytes, mime_type, timezone, settings.max_items_per_user_per_day
        )
    except DailyLimitExceeded as exc:
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail=str(exc)) from exc
    except Exception as exc:
        # Broad and deliberate, same reasoning as the chat endpoint --
        # transcription failures shouldn't surface as a raw 500.
        logger.exception("Audio transcription failed for user %s", user_id)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Could not transcribe that recording. Please try again in a few seconds.",
        ) from exc

    return ItemSummary(
        id=item.id,
        source_type=item.source_type,
        source_url=item.source_url,
        title=item.title,
        created_at=item.created_at,
    )


@router.get("/items", response_model=list[ItemWithConcepts])
async def read_items(
    user_id: str = Depends(get_current_user_id),
    session: AsyncSession = Depends(get_db_for_request),
) -> list[ItemWithConcepts]:
    return await list_items(session, user_id)


@router.delete("/items/{item_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_item(
    item_id: uuid.UUID,
    user_id: str = Depends(get_current_user_id),
    session: AsyncSession = Depends(get_db_for_request),
) -> None:
    deleted = await delete_item(session, user_id, item_id)
    if not deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Item not found.")


@router.post("/chat", response_model=ChatResponse)
@limiter.limit("30/minute")
async def chat(
    request: Request,
    body: ChatRequest,
    user_id: str = Depends(get_current_user_id),
    session: AsyncSession = Depends(get_db_for_request),
) -> ChatResponse:
    try:
        answer, source_ids = await answer_question(session, user_id, body.question)
    except Exception as exc:
        # Catching broadly and deliberately: the Gemini SDK's specific
        # exception classes live in a private module we shouldn't depend
        # on (it could change without notice), and every failure mode
        # here -- rate limits, timeouts, a transient outage -- deserves
        # the same friendly response, not a raw 500 with a stack trace.
        logger.exception("Chat failed for user %s", user_id)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="The AI service is busy or temporarily unavailable. Please try again in a few seconds.",
        ) from exc

    return ChatResponse(answer=answer, sources=source_ids)
