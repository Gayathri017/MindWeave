"""HTTP route for reading the current user's concept graph."""

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_user_id
from app.database import get_db_for_request
from app.models.schemas import GraphResponse
from app.services.graph import get_graph

router = APIRouter()


@router.get("/graph", response_model=GraphResponse)
async def read_graph(
    user_id: str = Depends(get_current_user_id),
    session: AsyncSession = Depends(get_db_for_request),
) -> GraphResponse:
    return await get_graph(session, user_id)
