"""HTTP routes for saving items and chatting with the user's saved knowledge."""

import asyncio
import base64
import logging
import uuid

import httpx
from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile, status
from slowapi import Limiter
from slowapi.util import get_remote_address
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_user_id
from app.config import get_settings
from app.database import get_db_for_request
from app.models.orm import ChatMessage
from app.models.schemas import (
    ChatMessageOut,
    ChatRequest,
    ChatResponse,
    CreateFolderRequest,
    ExplainerResponse,
    FolderSummary,
    ItemSummary,
    ItemWithConcepts,
    SaveItemRequest,
    TranscriptionResponse,
    UpdateItemFolderRequest,
)
from app.services.explainer import build_explainer
from app.services.file_signatures import looks_like_claimed_type
from app.services.folders import FolderNotFound, create_folder, delete_folder, list_folders
from app.services.gemini_client import transcribe_audio
from app.services.ingestion import save_audio_item, save_document_item, save_item
from app.services.items import delete_item, get_item, list_items, update_item_folder
from app.services.limits import DailyLimitExceeded, enforce_daily_limit
from app.services.retrieval import answer_question, answer_question_about_image, get_chat_history
from app.services.url_safety import UnsafeURLError

router = APIRouter()
limiter = Limiter(key_func=get_remote_address)
settings = get_settings()
logger = logging.getLogger(__name__)

_MAX_AUDIO_BYTES = 100 * 1024 * 1024  # 100 MB -- generous for a multi-hour lecture
_MAX_DOCUMENT_BYTES = 20 * 1024 * 1024  # 20 MB -- generous for a scanned paper or a photo
_ALLOWED_DOCUMENT_MIME_TYPES = {
    "application/pdf",
    "image/jpeg",
    "image/png",
    "image/webp",
    "image/heic",
    "image/heif",
}
# Deliberately generous (covers what browsers actually record, plus common
# uploaded-file formats) -- this exists to reject obviously-wrong uploads
# (a renamed video, an arbitrary binary) before they burn a 100 MB upload
# and a Gemini call, not to be maximally strict about audio codecs.
_ALLOWED_AUDIO_MIME_TYPES = {
    "audio/webm",
    "audio/ogg",
    "audio/mp3",
    "audio/mpeg",
    "audio/wav",
    "audio/x-wav",
    "audio/m4a",
    "audio/mp4",
    "audio/x-m4a",
    "audio/flac",
    "audio/aac",
}
_MAX_CHAT_IMAGE_BYTES = 10 * 1024 * 1024  # 10 MB -- plenty for a photo
_ALLOWED_CHAT_IMAGE_MIME_TYPES = {
    "image/jpeg",
    "image/png",
    "image/webp",
    "image/heic",
    "image/heif",
}
_READ_CHUNK_BYTES = 1024 * 1024  # 1 MB per chunk


async def _read_upload_limited(file: UploadFile, max_bytes: int, error_detail: str) -> bytes:
    """Read an upload in bounded chunks, aborting the moment it exceeds
    max_bytes.

    Plain `await file.read()` reads the entire body into memory before
    any size check can run -- Content-Length can't be trusted to catch
    this first (it can be absent, wrong, or the request can use chunked
    transfer encoding), so a client that just keeps sending bytes would
    force the server to buffer an unbounded amount of memory for a
    request that was always going to be rejected. Reading in chunks and
    checking as we go means memory use is capped at ~max_bytes regardless
    of what the client actually sends.
    """
    chunks = []
    total = 0
    while True:
        chunk = await file.read(_READ_CHUNK_BYTES)
        if not chunk:
            break
        total += len(chunk)
        if total > max_bytes:
            raise HTTPException(status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail=error_detail)
        chunks.append(chunk)
    return b"".join(chunks)


@router.post("/items", response_model=ItemSummary, status_code=status.HTTP_201_CREATED)
@limiter.limit("20/minute")
async def create_item(
    request: Request,
    body: SaveItemRequest,
    user_id: str = Depends(get_current_user_id),
    session: AsyncSession = Depends(get_db_for_request),
) -> ItemSummary:
    try:
        item = await save_item(
            session, user_id, body, settings.max_items_per_user_per_day, settings.max_items_per_day_global
        )
    except DailyLimitExceeded as exc:
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail=str(exc)) from exc
    except FolderNotFound as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except UnsafeURLError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except (httpx.HTTPError, httpx.TooManyRedirects) as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Could not fetch that URL. Check it's correct and try again."
        ) from exc

    return ItemSummary(
        id=item.id,
        source_type=item.source_type,
        source_url=item.source_url,
        title=item.title,
        folder_id=item.folder_id,
        created_at=item.created_at,
    )


@router.post("/items/audio", response_model=ItemSummary, status_code=status.HTTP_201_CREATED)
@limiter.limit("10/minute")
async def upload_audio_item(
    request: Request,
    file: UploadFile = File(...),
    timezone: str | None = Form(default=None),
    folder_id: uuid.UUID | None = Form(default=None),
    user_id: str = Depends(get_current_user_id),
    session: AsyncSession = Depends(get_db_for_request),
) -> ItemSummary:
    """Accepts an audio recording -- whether just captured live in the
    browser or picked from an existing file, both arrive here the same
    way -- transcribes it, and saves it through the normal pipeline.
    """
    mime_type = file.content_type or "audio/webm"
    if mime_type not in _ALLOWED_AUDIO_MIME_TYPES:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail="Unsupported audio type. Please record or upload a common audio format (WebM, MP3, WAV, M4A, OGG, FLAC, AAC).",
        )

    audio_bytes = await _read_upload_limited(
        file, _MAX_AUDIO_BYTES, f"Audio file is too large (max {_MAX_AUDIO_BYTES // (1024 * 1024)} MB)."
    )

    try:
        item = await save_audio_item(
            session, user_id, audio_bytes, mime_type, timezone,
            settings.max_items_per_user_per_day, settings.max_items_per_day_global, folder_id,
        )
    except DailyLimitExceeded as exc:
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail=str(exc)) from exc
    except FolderNotFound as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
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
        folder_id=item.folder_id,
        created_at=item.created_at,
    )


@router.post("/items/document", response_model=ItemSummary, status_code=status.HTTP_201_CREATED)
@limiter.limit("10/minute")
async def upload_document_item(
    request: Request,
    file: UploadFile = File(...),
    timezone: str | None = Form(default=None),
    folder_id: uuid.UUID | None = Form(default=None),
    user_id: str = Depends(get_current_user_id),
    session: AsyncSession = Depends(get_db_for_request),
) -> ItemSummary:
    """Accepts a PDF or a photo -- a research paper, a receipt, a form,
    whatever it turns out to be -- extracts its text and any structured
    data it contains, and saves it through the normal pipeline.
    """
    mime_type = file.content_type or "application/octet-stream"
    if mime_type not in _ALLOWED_DOCUMENT_MIME_TYPES:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail="Unsupported file type. Please upload a PDF or an image (JPEG, PNG, WEBP, HEIC).",
        )

    file_bytes = await _read_upload_limited(
        file, _MAX_DOCUMENT_BYTES, f"File is too large (max {_MAX_DOCUMENT_BYTES // (1024 * 1024)} MB)."
    )
    if not looks_like_claimed_type(file_bytes, mime_type):
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail="This file's content doesn't match its claimed type. Please check the file and try again.",
        )

    try:
        item = await save_document_item(
            session, user_id, file_bytes, mime_type, timezone,
            settings.max_items_per_user_per_day, settings.max_items_per_day_global, folder_id,
        )
    except DailyLimitExceeded as exc:
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail=str(exc)) from exc
    except FolderNotFound as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("Document extraction failed for user %s", user_id)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Could not read that document. Please try again in a few seconds.",
        ) from exc

    return ItemSummary(
        id=item.id,
        source_type=item.source_type,
        source_url=item.source_url,
        title=item.title,
        folder_id=item.folder_id,
        created_at=item.created_at,
    )


@router.post("/transcribe", response_model=TranscriptionResponse)
@limiter.limit("20/minute")
async def transcribe(
    request: Request,
    file: UploadFile = File(...),
    user_id: str = Depends(get_current_user_id),
) -> TranscriptionResponse:
    """Transcribe a short recording without saving it as an item -- used
    for asking a chat question by voice instead of typing it.
    """
    mime_type = file.content_type or "audio/webm"
    if mime_type not in _ALLOWED_AUDIO_MIME_TYPES:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail="Unsupported audio type. Please record or upload a common audio format (WebM, MP3, WAV, M4A, OGG, FLAC, AAC).",
        )

    audio_bytes = await _read_upload_limited(
        file, _MAX_AUDIO_BYTES, f"Audio file is too large (max {_MAX_AUDIO_BYTES // (1024 * 1024)} MB)."
    )

    try:
        text = await asyncio.to_thread(transcribe_audio, audio_bytes, mime_type)
    except Exception as exc:
        logger.exception("Voice question transcription failed for user %s", user_id)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Could not transcribe that. Please try again in a few seconds.",
        ) from exc

    return TranscriptionResponse(text=text)


@router.get("/items", response_model=list[ItemWithConcepts])
async def read_items(
    folder_id: uuid.UUID | None = None,
    user_id: str = Depends(get_current_user_id),
    session: AsyncSession = Depends(get_db_for_request),
) -> list[ItemWithConcepts]:
    """All items regardless of folder if folder_id is omitted (the main
    list), or just that folder's items if given.
    """
    return await list_items(session, user_id, folder_id=folder_id)


@router.delete("/items/{item_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_item(
    item_id: uuid.UUID,
    user_id: str = Depends(get_current_user_id),
    session: AsyncSession = Depends(get_db_for_request),
) -> None:
    deleted = await delete_item(session, user_id, item_id)
    if not deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Item not found.")


@router.patch("/items/{item_id}/folder", response_model=ItemSummary)
async def move_item(
    item_id: uuid.UUID,
    body: UpdateItemFolderRequest,
    user_id: str = Depends(get_current_user_id),
    session: AsyncSession = Depends(get_db_for_request),
) -> ItemSummary:
    """File an item into a folder, or back to the main list (folder_id: null)."""
    try:
        item = await update_item_folder(session, user_id, item_id, body.folder_id)
    except FolderNotFound as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

    if item is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Item not found.")

    return ItemSummary(
        id=item.id,
        source_type=item.source_type,
        source_url=item.source_url,
        title=item.title,
        folder_id=item.folder_id,
        created_at=item.created_at,
    )


@router.post("/items/{item_id}/explain", response_model=ExplainerResponse)
@limiter.limit("5/hour;15/day")
async def explain_item(
    request: Request,
    item_id: uuid.UUID,
    user_id: str = Depends(get_current_user_id),
    session: AsyncSession = Depends(get_db_for_request),
) -> ExplainerResponse:
    """Turn a saved item into a short narrated slideshow -- a script broken
    into scenes, each with a generated image and generated narration audio.
    Tightly rate-limited: each call is one script generation plus up to
    five image and five audio generations, far pricier than a normal
    chat turn.
    """
    item = await get_item(session, user_id, item_id)
    if item is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Item not found.")

    try:
        return await asyncio.to_thread(build_explainer, item.raw_text)
    except Exception as exc:
        logger.exception("Explainer generation failed for item %s", item_id)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Could not generate an explainer for this item. Please try again in a few seconds.",
        ) from exc


@router.post("/folders", response_model=FolderSummary, status_code=status.HTTP_201_CREATED)
@limiter.limit("20/minute")
async def create_folder_route(
    request: Request,
    body: CreateFolderRequest,
    user_id: str = Depends(get_current_user_id),
    session: AsyncSession = Depends(get_db_for_request),
) -> FolderSummary:
    folder = await create_folder(session, user_id, body.name)
    return FolderSummary(id=folder.id, name=folder.name, item_count=0, created_at=folder.created_at)


@router.get("/folders", response_model=list[FolderSummary])
async def read_folders(
    user_id: str = Depends(get_current_user_id),
    session: AsyncSession = Depends(get_db_for_request),
) -> list[FolderSummary]:
    return await list_folders(session, user_id)


@router.delete("/folders/{folder_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_folder(
    folder_id: uuid.UUID,
    user_id: str = Depends(get_current_user_id),
    session: AsyncSession = Depends(get_db_for_request),
) -> None:
    """Delete a folder and everything filed in it."""
    deleted = await delete_folder(session, user_id, folder_id)
    if not deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Folder not found.")


@router.get("/chat/messages", response_model=list[ChatMessageOut])
async def read_chat_messages(
    folder_id: uuid.UUID | None = None,
    user_id: str = Depends(get_current_user_id),
    session: AsyncSession = Depends(get_db_for_request),
) -> list[ChatMessageOut]:
    """The persisted thread for the global chat (folder_id omitted) or one folder."""
    return await get_chat_history(session, user_id, folder_id)


@router.post("/chat/image", response_model=ChatResponse)
@limiter.limit("15/minute")
async def chat_about_image(
    request: Request,
    file: UploadFile = File(...),
    question: str = Form(default="What's in this image?"),
    folder_id: uuid.UUID | None = Form(default=None),
    user_id: str = Depends(get_current_user_id),
    session: AsyncSession = Depends(get_db_for_request),
) -> ChatResponse:
    """Ask a question about an image attached directly to the chat --
    answered on the spot from the image itself, not saved as an item and
    not drawn from the user's saved knowledge.
    """
    mime_type = file.content_type or "application/octet-stream"
    if mime_type not in _ALLOWED_CHAT_IMAGE_MIME_TYPES:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail="Unsupported image type. Please attach a JPEG, PNG, WEBP, or HEIC image.",
        )

    image_bytes = await _read_upload_limited(
        file, _MAX_CHAT_IMAGE_BYTES, f"Image is too large (max {_MAX_CHAT_IMAGE_BYTES // (1024 * 1024)} MB)."
    )
    if not looks_like_claimed_type(image_bytes, mime_type):
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail="This file's content doesn't match its claimed type. Please check the file and try again.",
        )

    try:
        await enforce_daily_limit(
            session,
            ChatMessage,
            (ChatMessage.user_id == user_id) & (ChatMessage.role == "user"),
            settings.max_chat_messages_per_user_per_day,
            settings.max_chat_messages_per_day_global,
            "question",
        )
    except DailyLimitExceeded as exc:
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail=str(exc)) from exc

    try:
        result = await answer_question_about_image(session, user_id, folder_id, image_bytes, mime_type, question)
    except Exception as exc:
        logger.exception("Image chat failed for user %s", user_id)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Could not read that image. Please try again in a few seconds.",
        ) from exc

    return ChatResponse(answer=result.answer, from_notes=result.from_notes)


@router.post("/chat", response_model=ChatResponse)
@limiter.limit("30/minute")
async def chat(
    request: Request,
    body: ChatRequest,
    user_id: str = Depends(get_current_user_id),
    session: AsyncSession = Depends(get_db_for_request),
) -> ChatResponse:
    try:
        await enforce_daily_limit(
            session,
            ChatMessage,
            (ChatMessage.user_id == user_id) & (ChatMessage.role == "user"),
            settings.max_chat_messages_per_user_per_day,
            settings.max_chat_messages_per_day_global,
            "question",
        )
    except DailyLimitExceeded as exc:
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail=str(exc)) from exc

    try:
        result = await answer_question(session, user_id, body.question, body.folder_id)
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

    image = None
    if result.image_bytes and result.image_mime_type:
        image = f"data:{result.image_mime_type};base64,{base64.b64encode(result.image_bytes).decode()}"

    return ChatResponse(
        answer=result.answer,
        sources=result.sources,
        web_sources=result.web_sources,
        from_notes=result.from_notes,
        image=image,
    )
