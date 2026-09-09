"""Reads the current user's concept graph -- nodes and weighted edges."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.orm import Concept, ConceptLink
from app.models.schemas import GraphEdge, GraphNode, GraphResponse


async def get_graph(session: AsyncSession, user_id: str) -> GraphResponse:
    concepts = (
        (await session.execute(select(Concept).where(Concept.user_id == user_id))).scalars().all()
    )
    links = (
        (await session.execute(select(ConceptLink).where(ConceptLink.user_id == user_id)))
        .scalars()
        .all()
    )

    nodes = [GraphNode(id=c.id, name=c.name) for c in concepts]
    edges = [
        GraphEdge(source=link.concept_a_id, target=link.concept_b_id, weight=link.weight)
        for link in links
    ]
    return GraphResponse(nodes=nodes, edges=edges)
