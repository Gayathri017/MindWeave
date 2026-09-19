"""Turns any saved item's text into a short narrated slideshow on request --
a script broken into a handful of scenes, each with a generated image and
generated narration audio. Deliberately not an actual encoded video: no
video-generation model is available through this Gemini SDK, and a
slideshow the frontend plays through is far cheaper (and still genuinely
explains the content) than a per-second-billed third-party video API would
be -- see the request that led here for that comparison.
"""

import base64
import logging

from pydantic import BaseModel, Field

from app.models.schemas import ExplainerResponse, ExplainerSceneOut
from app.services.gemini_client import generate_image, generate_speech, generate_structured

logger = logging.getLogger(__name__)

_MAX_INPUT_CHARS = 8000
_MIN_SCENES = 3
_MAX_SCENES = 5

_SYSTEM_INSTRUCTION = (
    "Turn this content into a short narrated explainer, broken into "
    f"{_MIN_SCENES}-{_MAX_SCENES} scenes. For each scene:\n"
    "- narration: 1-3 sentences of spoken narration, written to be read "
    "aloud -- clear, conversational, no bullet points or markdown.\n"
    "- visual_description: a detailed, self-contained description of an "
    "image to show during this scene. It will be sent to an image "
    "generator with no other context, so describe exactly what should "
    "appear -- don't just repeat the narration.\n"
    "Order the scenes so they build on each other and cover the content's "
    "most important points, not everything in it."
)


class ExplainerScene(BaseModel):
    narration: str = Field(..., min_length=1)
    visual_description: str = Field(..., min_length=1)


class ExplainerScript(BaseModel):
    title: str
    scenes: list[ExplainerScene] = Field(..., min_length=_MIN_SCENES, max_length=_MAX_SCENES)


def _data_url(mime_type: str, data: bytes) -> str:
    return f"data:{mime_type};base64,{base64.b64encode(data).decode()}"


def build_explainer(text: str) -> ExplainerResponse:
    """Generate the script, then render each scene's image and narration
    audio. A scene whose image or audio generation fails still comes back
    with its narration text -- one flaky generation shouldn't sink the
    whole explainer.
    """
    script = generate_structured(text[:_MAX_INPUT_CHARS], ExplainerScript, system_instruction=_SYSTEM_INSTRUCTION)

    scenes = []
    for scene in script.scenes:
        image_url = None
        try:
            image_bytes, image_mime = generate_image(scene.visual_description)
            image_url = _data_url(image_mime, image_bytes)
        except Exception:
            logger.exception("Explainer scene image generation failed; continuing without it.")

        audio_url = None
        try:
            audio_bytes, audio_mime = generate_speech(scene.narration)
            audio_url = _data_url(audio_mime, audio_bytes)
        except Exception:
            logger.exception("Explainer scene narration generation failed; continuing without it.")

        scenes.append(ExplainerSceneOut(narration=scene.narration, image=image_url, audio=audio_url))

    return ExplainerResponse(title=script.title, scenes=scenes)
