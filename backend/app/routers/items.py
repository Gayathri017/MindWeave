"""HTTP routes for saving items and chatting with the user's saved knowledge."""

import uuid

from fastapi import APIRouter, Depends, HTTPException, Request, status
from slowapi import Limiter
from slowapi.util import get_remote_address
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_user_id
from app.config import get_settings
from app.database import get_db_for_request
from app.models.schemas import ChatRequest, ChatResponse, ItemSummary, ItemWithConcepts, SaveItemRequest
from app.services.ingestion import DailyLimitExceeded, save_item
from app.services.items import delete_item, list_items
from app.services.retrieval import answer_question

router = APIRouter()
limiter = Limiter(key_func=get_remote_address)
settings = get_settings()


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
    answer, source_ids = await answer_question(session, user_id, body.question)
    return ChatResponse(answer=answer, sources=source_ids)